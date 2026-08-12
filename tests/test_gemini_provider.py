from __future__ import annotations

from google.genai import types

from app.services.inference.gemini import GeminiProvider


def test_config_uses_json_schema_transport_without_legacy_response_schema(settings):
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._types = types
    provider._settings = settings
    config = provider._config("gemini-3-flash-preview")

    assert config.response_schema is None
    assert config.thinking_config.thinking_level == types.ThinkingLevel.MINIMAL
    assert config.response_json_schema["type"] == "array"
    assert config.response_json_schema["minItems"] == 9
    assert len(config.response_json_schema["prefixItems"]) == 9


def test_gemini_25_disables_thinking_to_protect_cost(settings):
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._types = types
    provider._settings = settings
    config = provider._config("gemini-2.5-flash")
    assert config.thinking_config.thinking_budget == 0
