from __future__ import annotations

from google.genai import types

from app.services.audio import AcousticFeatures
from app.services.inference.gemini import GeminiProvider, _prompt


def test_config_uses_json_schema_transport_without_legacy_response_schema(settings):
    settings.gemini_emotion_strategy = "direct"
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


def test_latent_emotion_mapping_is_deterministic():
    prediction = GeminiProvider._prediction_from_latent(
        [-0.7, 0.85, 0.05, 0.75, 0.8, 0.1, 0.9, False, "", "none", "clear", False, False, 0.88]
    )
    assert prediction.emotional_tone == "upset"
    assert prediction.emotional_intensity == "high"
    assert prediction.confidence == 0.88


def test_latent_config_uses_evidence_schema(settings):
    settings.gemini_emotion_strategy = "latent"
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._types = types
    provider._settings = settings
    config = provider._config("gemini-3.1-flash-lite")
    assert config.response_json_schema["minItems"] == 14


def test_episode_mapping_selects_highest_salience_customer_episode():
    prediction = GeminiProvider._prediction_from_episodes(
        [
            [["neutral", "medium", 0.3, 0.8], ["satisfied", "medium", 0.9, 0.2]],
            0.84,
            True,
            "television",
            "medium",
            "clear",
            True,
            False,
            0.9,
        ]
    )
    assert prediction.emotional_tone == "satisfied"
    assert prediction.emotional_intensity == "medium"
    assert prediction.confidence == 0.84


def test_speaker_profile_mapping_selects_service_seeker_not_provider():
    prediction, diagnostics = GeminiProvider._prediction_from_speaker_profiles(
        [
            [
                ["neutral", "low", 0.1, 0.95, 0.0, 0.55, 0.9],
                ["upset", "high", 0.95, 0.05, 0.0, 0.45, 0.85],
                ["frustrated", "medium", 0.0, 0.0, 0.95, 0.2, 0.8],
            ],
            True,
            "television",
            "medium",
            "clear",
            True,
            False,
            0.9,
        ]
    )
    assert prediction.emotional_tone == "upset"
    assert prediction.emotional_intensity == "high"
    assert prediction.confidence <= 0.85
    assert diagnostics["speaker_profile_count"] == 3.0


def test_single_speaker_profile_uses_conservative_but_not_ambiguous_confidence():
    prediction, _ = GeminiProvider._prediction_from_speaker_profiles(
        [
            [["neutral", "medium", 0.9, 0.1, 0.0, 1.0, 0.9]],
            False,
            "",
            "none",
            "clear",
            False,
            False,
            0.9,
        ]
    )
    assert prediction.confidence == 0.78


def test_local_transcript_strategy_returns_to_exact_compact_result_schema(settings):
    settings.gemini_emotion_strategy = "transcript_local"
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._types = types
    provider._settings = settings
    config = provider._config("gemini-3-flash-preview")
    assert config.response_json_schema["minItems"] == 9


def test_tagged_transcript_strategy_returns_to_exact_compact_result_schema(settings):
    settings.gemini_emotion_strategy = "transcript_local_tagged"
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._types = types
    provider._settings = settings
    config = provider._config("gemini-3.1-flash-lite")
    assert config.response_json_schema["minItems"] == 9


def test_transcript_profile_strategy_uses_profile_schema(settings):
    settings.gemini_emotion_strategy = "transcript_local_profiles"
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._types = types
    provider._settings = settings
    config = provider._config("gemini-3.1-flash-lite")
    assert config.response_json_schema["minItems"] == 8


def test_emotion_profile_strategy_uses_profile_schema(settings):
    settings.gemini_emotion_strategy = "emotion_profiles"
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._types = types
    provider._settings = settings
    config = provider._config("gemini-3.1-flash-lite")
    assert config.response_json_schema["minItems"] == 8


def test_prompt_uses_primary_customer_tone_contract_without_peak_instruction():
    features = AcousticFeatures(
        duration_seconds=30.0,
        rms_dbfs=-20.0,
        peak_dbfs=-2.0,
        clipping_ratio=0.0,
        active_audio_ratio=0.9,
        max_silence_seconds=1.0,
        broadband_transient_seconds=0.0,
        broadband_transient_bursts=0,
        long_silence_present=False,
        heuristic_audio_quality="clear",
    )
    prompt = _prompt(features)
    normalized_prompt = " ".join(prompt.split())
    assert "primary emotional tone expressed by the customer" in normalized_prompt
    assert "clearest salient" not in prompt
    assert "Frustrated means annoyed, impatient, or dissatisfied without strong anger" in normalized_prompt
