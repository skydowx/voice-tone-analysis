from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import Settings
from app.schemas.prediction import Prediction
from app.services.audio import AcousticFeatures
from app.services.inference.base import InferenceOutcome, Usage


PROMPT_VERSION = "2026-08-11.v5"

COMPACT_KEYS = (
    "emotional_tone",
    "emotional_intensity",
    "background_noise_present",
    "background_noise_type",
    "background_noise_severity",
    "audio_quality",
    "speaker_overlap_present",
    "long_silence_present",
    "confidence",
)

COMPACT_SCHEMA = {
    "type": "array",
    "prefixItems": [
        {
            "type": "string",
            "enum": ["neutral", "satisfied", "frustrated", "upset", "distressed"],
            "description": "customer emotional tone",
        },
        {"type": "string", "enum": ["low", "medium", "high"], "description": "emotion intensity"},
        {"type": "boolean", "description": "meaningful background noise present"},
        {
            "type": "string",
            "maxLength": 80,
            "description": "dominant noise source under five words; empty if absent; never rationale",
        },
        {
            "type": "string",
            "enum": ["none", "low", "medium", "high"],
            "description": "background noise severity",
        },
        {
            "type": "string",
            "enum": ["clear", "slightly_impaired", "severely_impaired"],
            "description": "technical audio quality",
        },
        {"type": "boolean", "description": "material speaker overlap present"},
        {"type": "boolean", "description": "unusually long dead air present"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "calibrated confidence"},
    ],
    "minItems": 9,
    "maxItems": 9,
}


SYSTEM_INSTRUCTION = """You are a careful quality analyst for real customer-service call audio.
Classify the foreground CUSTOMER, never the agent or speech from a TV/radio. Infer roles from the greeting,
questions, requests, and service behavior. Use meaning and prosody together; loudness alone is not emotion.
Keep emotion, background sound, overlap, and technical quality independent. Return only the requested
structured object and never return a transcript or identifying details."""


def _prompt(features: AcousticFeatures) -> str:
    return """Analyze the entire clip against the schema definitions. Use the customer's clearest salient
emotion across the call, not simply the emotion occupying the most seconds. Appreciative, relieved, or
clearly positive customer speech is satisfied; clear sustained anger or agitation is upset; frustration is
the milder dissatisfied class. A calm customer can have medium intensity when that tone is sustained.

Treat background TV/radio dialogue as noise and possible overlap, but never as the customer's emotion.
Meaningful noise excludes faint codec artifacts. Describe only the dominant noise source. Technical audio
quality is independent of noise. Ordinary turn-taking pauses are not long silence. Use conservative,
calibrated confidence, especially when roles or sound sources are ambiguous. The fourth array value is
only a short noise-source label, never analysis or rationale."""


class GeminiProvider:
    def __init__(self, settings: Settings):
        if settings.gemini_api_key is None:
            raise ValueError("GEMINI_API_KEY is required for Gemini inference")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("google-genai is not installed") from exc

        self._types = types
        self._settings = settings
        self._client = genai.Client(
            api_key=settings.gemini_api_key.get_secret_value(),
            http_options=types.HttpOptions(timeout=settings.gemini_timeout_seconds * 1000),
        )

    def _config(self, model: str):
        if model.startswith("gemini-2.5"):
            thinking_config = self._types.ThinkingConfig(thinking_budget=0, include_thoughts=False)
        else:
            thinking_config = self._types.ThinkingConfig(
                thinking_level=(
                    self._types.ThinkingLevel.LOW
                    if self._settings.gemini_thinking_level == "low"
                    else self._types.ThinkingLevel.MINIMAL
                ),
                include_thoughts=False,
            )
        kwargs = {
            "system_instruction": SYSTEM_INSTRUCTION,
            "temperature": 0.0,
            "max_output_tokens": self._settings.gemini_max_output_tokens,
            "thinking_config": thinking_config,
            "response_mime_type": "application/json",
            # The compact transport cuts paid output tokens; strict object validation
            # and the exact public field names are restored immediately after parsing.
            "response_json_schema": COMPACT_SCHEMA,
        }
        return self._types.GenerateContentConfig(**kwargs)

    def analyze(self, audio_path: Path, features: AcousticFeatures, model: str | None = None) -> InferenceOutcome:
        selected_model = model or self._settings.gemini_model
        audio_bytes = audio_path.read_bytes()
        if len(audio_bytes) > 19 * 1024 * 1024:
            raise ValueError("Normalized audio exceeds the 20 MB inline request limit")

        contents = [
            self._types.Part.from_bytes(data=audio_bytes, mime_type="audio/wav"),
            _prompt(features),
        ]
        last_error: Exception | None = None
        started = time.perf_counter()
        for attempt in range(self._settings.gemini_max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=selected_model,
                    contents=contents,
                    config=self._config(selected_model),
                )
                if getattr(response, "parsed", None) is not None:
                    raw_prediction = response.parsed
                else:
                    if not response.text:
                        candidates = getattr(response, "candidates", None) or []
                        finish_reason = getattr(candidates[0], "finish_reason", "unknown") if candidates else "none"
                        usage = getattr(response, "usage_metadata", None)
                        raise ValueError(
                            "Gemini returned no structured output "
                            f"(finish_reason={finish_reason}, usage={usage})"
                        )
                    raw_prediction = json.loads(response.text or "[]")
                if not isinstance(raw_prediction, (list, tuple)) or len(raw_prediction) != len(COMPACT_KEYS):
                    raise ValueError("Gemini response did not match the compact nine-value contract")
                prediction = Prediction.model_validate(dict(zip(COMPACT_KEYS, raw_prediction)))
                usage_meta = getattr(response, "usage_metadata", None)
                input_tokens = int(getattr(usage_meta, "prompt_token_count", 0) or 0)
                output_tokens = int(getattr(usage_meta, "candidates_token_count", 0) or 0)
                thinking_tokens = int(getattr(usage_meta, "thoughts_token_count", 0) or 0)
                total_tokens = int(getattr(usage_meta, "total_token_count", 0) or 0)
                request_id = None
                sdk_response = getattr(response, "sdk_http_response", None)
                if sdk_response is not None:
                    headers = getattr(sdk_response, "headers", {}) or {}
                    request_id = headers.get("x-request-id") or headers.get("x-goog-request-id")
                return InferenceOutcome(
                    prediction=prediction,
                    model=selected_model,
                    latency_seconds=time.perf_counter() - started,
                    usage=Usage(input_tokens, output_tokens, thinking_tokens, total_tokens),
                    provider_request_id=request_id,
                )
            except Exception as exc:  # Provider errors have changed across SDK versions.
                last_error = exc
                status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
                if isinstance(status_code, int) and 400 <= status_code < 500 and status_code not in {
                    408,
                    409,
                    429,
                }:
                    break
                if attempt >= self._settings.gemini_max_retries:
                    break
                time.sleep(1.5 * (2**attempt))
        raise RuntimeError(f"Gemini inference failed after retries: {last_error}") from last_error
