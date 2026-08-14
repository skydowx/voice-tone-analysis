from __future__ import annotations

from app.services.analytics import Analytics, categorize_processing_error


class RecordingClient:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail
        self.shutdown_called = False

    def capture(self, *args, **kwargs):
        if self.fail:
            raise RuntimeError("telemetry unavailable")
        self.calls.append((args, kwargs))

    def shutdown(self):
        if self.fail:
            raise RuntimeError("telemetry unavailable")
        self.shutdown_called = True


def test_analytics_allows_only_registered_non_sensitive_properties(settings):
    client = RecordingClient()
    analytics = Analytics(settings, client=client)

    analytics.capture(
        "batch item failed",
        {
            "batch_id": "abc123",
            "error_category": "provider_unavailable",
            "filename": "private-call.wav",
            "raw_error": "sensitive provider response",
        },
    )

    _, kwargs = client.calls[0]
    assert kwargs["distinct_id"] == "autoace-test"
    assert kwargs["properties"] == {
        "batch_id": "abc123",
        "error_category": "provider_unavailable",
        "environment": "test",
        "release": "development",
        "$process_person_profile": False,
    }


def test_analytics_drops_unknown_events_and_never_breaks_the_app(settings):
    client = RecordingClient(fail=True)
    analytics = Analytics(settings, client=client)

    analytics.capture("unknown event", {"anything": "value"})
    analytics.capture("application started")
    analytics.shutdown()

    assert client.calls == []


def test_processing_errors_are_reduced_to_safe_categories():
    assert categorize_processing_error("503 UNAVAILABLE: high demand") == "provider_unavailable"
    assert categorize_processing_error("429 RESOURCE_EXHAUSTED") == "provider_rate_limited"
    assert categorize_processing_error("request timed out") == "provider_timeout"
    assert categorize_processing_error("customer name appeared here") == "processing_error"
