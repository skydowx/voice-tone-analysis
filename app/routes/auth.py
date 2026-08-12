from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER

from app.dependencies import settings_from
from app.security import ensure_csrf_token, verify_csrf, verify_login


router = APIRouter()


@router.get("/login")
async def login_page(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)
    return request.app.state.templates.TemplateResponse(
        request,
        "login.html",
        {"csrf_token": ensure_csrf_token(request), "error": None},
    )


@router.post("/login")
async def login(
    request: Request,
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    csrf_token: Annotated[str, Form()],
):
    verify_csrf(request, csrf_token)
    client_key = request.client.host if request.client else "unknown"
    request.app.state.login_limiter.check(client_key)
    if not verify_login(settings_from(request), username, password):
        return request.app.state.templates.TemplateResponse(
            request,
            "login.html",
            {"csrf_token": ensure_csrf_token(request), "error": "Invalid username or password"},
            status_code=401,
        )
    request.app.state.login_limiter.reset(client_key)
    request.session.clear()
    request.session["user"] = username
    ensure_csrf_token(request)
    return RedirectResponse("/", status_code=HTTP_303_SEE_OTHER)


@router.post("/logout")
async def logout(request: Request, csrf_token: Annotated[str, Form()]):
    verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/login", status_code=HTTP_303_SEE_OTHER)
