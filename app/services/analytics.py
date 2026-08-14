from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Protocol

from app.config import Settings


logger = logging.getLogger(__name__)


ALLOWED_EVENT_PROPERTIES: dict[str, frozenset[str]] = {
    "application started": frozenset(),
    "batch uploaded": frozenset(
        {
            "batch_id",
            "total_items",
            "processable",
            "validation_error_count",
            "validation_warning_count",
        }
    ),
    "batch completed": frozenset(
        {
            "batch_id",
            "status",
            "total_items",
            "completed_items",
            "failed_items",
            "audio_seconds",
            "estimated_cost_usd",
            "processing_seconds",
        }
    ),
    "batch item failed": frozenset({"batch_id", "error_category"}),
    "results downloaded": frozenset(
        {"batch_id", "format", "status", "completed_items", "failed_items"}
    ),
}


class AnalyticsSink(Protocol):
    def capture(self, event: str, properties: Mapping[str, object] | None = None) -> None: ...

    def shutdown(self) -> None: ...


def categorize_processing_error(error: Exception | str) -> str:
    """Reduce provider/internal errors to a non-sensitive operational category."""
    message = str(error).lower()
    if "429" in message or "resource_exhausted" in message or "rate limit" in message:
        return "provider_rate_limited"
    if "503" in message or "unavailable" in message or "high demand" in message:
        return "provider_unavailable"
    if "timeout" in message or "timed out" in message or "deadline" in message:
        return "provider_timeout"
    if "schema" in message or "structured output" in message:
        return "provider_schema_error"
    if "gemini" in message or "provider" in message:
        return "provider_error"
    return "processing_error"


class Analytics:
    """Small fail-open PostHog adapter with a strict data minimization boundary."""

    def __init__(self, settings: Settings, client: Any | None = None):
        self.environment = settings.app_env
        self.release = settings.app_version
        self._client = client
        if self._client is None and settings.posthog_project_token:
            from posthog import Posthog

            self._client = Posthog(
                settings.posthog_project_token.get_secret_value(),
                host=str(settings.posthog_host).rstrip("/"),
                disable_geoip=True,
                enable_exception_autocapture=False,
                max_retries=1,
                timeout=3,
            )

    @property
    def enabled(self) -> bool:
        return self._client is not None

    def capture(self, event: str, properties: Mapping[str, object] | None = None) -> None:
        if self._client is None:
            return
        allowed = ALLOWED_EVENT_PROPERTIES.get(event)
        if allowed is None:
            logger.warning("Dropped unregistered analytics event", extra={"analytics_event": event})
            return

        supplied = properties or {}
        safe_properties = {key: supplied[key] for key in allowed if key in supplied}
        safe_properties.update(
            {
                "environment": self.environment,
                "release": self.release,
                "$process_person_profile": False,
            }
        )
        try:
            self._client.capture(
                event,
                distinct_id=f"autoace-{self.environment}",
                properties=safe_properties,
            )
        except Exception:
            logger.warning("PostHog event capture failed", exc_info=True)

    def shutdown(self) -> None:
        if self._client is None:
            return
        try:
            self._client.shutdown()
        except Exception:
            logger.warning("PostHog shutdown flush failed", exc_info=True)
