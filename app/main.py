from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings
from app.repositories.batches import BatchRepository
from app.routes import auth, batches
from app.security import LoginRateLimiter
from app.services.analytics import Analytics, AnalyticsSink
from app.services.classifier import AudioClassifier
from app.services.inference.base import InferenceProvider
from app.services.inference.gemini import GeminiProvider
from app.services.processor import BatchProcessor


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


class UnavailableProvider:
    def analyze(self, *args, **kwargs):
        raise RuntimeError("GEMINI_API_KEY is not configured; live inference is unavailable")


def create_app(
    settings: Settings | None = None,
    provider: InferenceProvider | None = None,
    analytics: AnalyticsSink | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_directories()
    if analytics is None:
        analytics = Analytics(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.repository.recover_incomplete()
        app.state.analytics.capture("application started")
        try:
            yield
        finally:
            app.state.processor.shutdown()
            app.state.analytics.shutdown()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/api/docs" if settings.app_env != "production" else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    base_dir = Path(__file__).resolve().parent
    app.mount("/static", StaticFiles(directory=base_dir / "static"), name="static")
    app.state.settings = settings
    app.state.analytics = analytics
    app.state.templates = Jinja2Templates(directory=base_dir / "templates")
    posthog_project_token = (
        settings.posthog_project_token.get_secret_value() if settings.posthog_project_token else ""
    )
    app.state.templates.env.globals.update(
        posthog_session_replay=bool(settings.posthog_session_replay and posthog_project_token),
        posthog_project_token=posthog_project_token,
        posthog_host=str(settings.posthog_host).rstrip("/"),
    )
    app.state.repository = BatchRepository(settings.database_path)
    selected_provider = provider
    if selected_provider is None:
        selected_provider = GeminiProvider(settings) if settings.gemini_api_key else UnavailableProvider()
    app.state.classifier = AudioClassifier(selected_provider, settings)
    app.state.processor = BatchProcessor(
        app.state.repository,
        app.state.classifier,
        settings,
        analytics=app.state.analytics,
    )
    app.state.login_limiter = LoginRateLimiter()

    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie="autoace_session",
        max_age=settings.session_max_age_seconds,
        same_site="lax",
        https_only=settings.cookie_secure,
    )

    app.include_router(auth.router)
    app.include_router(batches.router)

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def ready() -> dict[str, str]:
        with app.state.repository._connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return {"status": "ready"}

    @app.exception_handler(401)
    async def unauthenticated(request: Request, exc):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)

    return app


app = create_app()
