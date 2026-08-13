from __future__ import annotations

import json
import time
from pathlib import Path

from app.config import Settings
from app.schemas.prediction import Prediction
from app.services.audio import AcousticFeatures
from app.services.inference.base import InferenceOutcome, Usage
from app.services.transcript_emotion import analyze_transcript_emotion


PROMPT_VERSION = "2026-08-13.v9"

CUSTOMER_EMOTION_INSTRUCTION = """Analyze the entire call and identify the foreground CUSTOMER from
conversational function, not voice order. Ignore the agent, television, radio, bystanders, and unrelated
speech. Return the customer's primary emotional tone over the call using these assessment definitions:
- neutral: no clear positive or negative emotion
- satisfied: pleased, relieved, appreciative, or clearly positive
- frustrated: annoyed, impatient, or dissatisfied without strong anger or distress
- upset: clearly angry, agitated, or strongly dissatisfied
- distressed: highly emotional, overwhelmed, panicked, crying, or otherwise emotionally escalated
Return intensity as low for subtle or mild, medium for clear and sustained, or high for strong, escalated,
or likely to require attention. Use wording and prosody together. Do not select the most intense isolated
moment unless it represents the customer's primary tone. Do not infer emotion from loudness alone. Return
only the requested structured array and no transcript or identifying details."""

TRANSCRIPT_INSTRUCTION = """Create a concise speaker-turn transcript for internal classification.
Infer CUSTOMER versus AGENT from conversational function. Mark television, radio, or unrelated people as
BACKGROUND, never CUSTOMER. Preserve sentiment-bearing wording and disfluency, but replace names, phone
numbers, addresses, account identifiers, and other identifying values with [REDACTED]. Do not summarize,
explain, or add facts. Format one turn per line as ROLE: words."""

TAGGED_TRANSCRIPT_INSTRUCTION = """Create a concise speaker-turn transcript for internal classification.
Infer CUSTOMER versus AGENT from conversational function. Mark television, radio, or unrelated people as
BACKGROUND, never CUSTOMER. For every turn, classify that speaker's audible tone and intensity using both
meaning and prosody. Allowed tones are neutral, satisfied, frustrated, upset, distressed. Allowed intensities
are low, medium, high. Preserve sentiment-bearing wording and disfluency, but replace names, phone numbers,
addresses, account identifiers, and other identifying values with [REDACTED]. Do not summarize, explain, or
add facts. Format exactly one turn per line as ROLE|TONE|INTENSITY: words."""

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

CUSTOMER_EMOTION_KEYS = (
    "emotional_tone",
    "emotional_intensity",
    "role_certainty",
    "emotion_confidence",
)

CUSTOMER_EMOTION_SCHEMA = {
    "type": "array",
    "prefixItems": [
        {
            "type": "string",
            "enum": ["neutral", "satisfied", "frustrated", "upset", "distressed"],
            "description": "primary emotional tone expressed by the customer over the call",
        },
        {
            "type": "string",
            "enum": ["low", "medium", "high"],
            "description": "strength of the customer's primary emotional tone",
        },
        {"type": "number", "minimum": 0, "maximum": 1, "description": "certainty customer was identified"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "confidence in tone and intensity"},
    ],
    "minItems": 4,
    "maxItems": 4,
}

LATENT_KEYS = (
    "valence",
    "arousal",
    "satisfaction",
    "frustration",
    "anger",
    "distress",
    "role_certainty",
    "background_noise_present",
    "background_noise_type",
    "background_noise_severity",
    "audio_quality",
    "speaker_overlap_present",
    "long_silence_present",
    "confidence",
)

LATENT_SCHEMA = {
    "type": "array",
    "prefixItems": [
        {"type": "number", "minimum": -1, "maximum": 1, "description": "customer valence"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "customer arousal"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "customer satisfaction or relief"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "customer frustration or impatience"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "customer anger or agitation"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "customer distress, panic, or overwhelm"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "certainty that the customer was identified"},
        {"type": "boolean", "description": "meaningful background noise present"},
        {"type": "string", "maxLength": 80, "description": "dominant noise source under five words; empty if absent"},
        {"type": "string", "enum": ["none", "low", "medium", "high"], "description": "noise severity"},
        {"type": "string", "enum": ["clear", "slightly_impaired", "severely_impaired"], "description": "technical quality"},
        {"type": "boolean", "description": "material speaker overlap"},
        {"type": "boolean", "description": "unusually long dead air"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "overall evidence confidence"},
    ],
    "minItems": 14,
    "maxItems": 14,
}

EPISODE_KEYS = (
    "customer_emotion_episodes",
    "role_certainty",
    "background_noise_present",
    "background_noise_type",
    "background_noise_severity",
    "audio_quality",
    "speaker_overlap_present",
    "long_silence_present",
    "confidence",
)

EPISODE_SCHEMA = {
    "type": "array",
    "prefixItems": [
        {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "description": "distinct CUSTOMER emotional episodes, strongest operationally salient first",
            "items": {
                "type": "array",
                "prefixItems": [
                    {
                        "type": "string",
                        "enum": ["neutral", "satisfied", "frustrated", "upset", "distressed"],
                        "description": "customer tone in this episode using the assessment definitions",
                    },
                    {"type": "string", "enum": ["low", "medium", "high"], "description": "episode intensity"},
                    {"type": "number", "minimum": 0, "maximum": 1, "description": "episode salience"},
                    {"type": "number", "minimum": 0, "maximum": 1, "description": "fraction of customer speech"},
                ],
                "minItems": 4,
                "maxItems": 4,
            },
        },
        {"type": "number", "minimum": 0, "maximum": 1, "description": "certainty customer was identified"},
        {"type": "boolean", "description": "meaningful background noise"},
        {"type": "string", "maxLength": 80, "description": "dominant noise under five words; empty if absent"},
        {"type": "string", "enum": ["none", "low", "medium", "high"], "description": "noise severity"},
        {"type": "string", "enum": ["clear", "slightly_impaired", "severely_impaired"], "description": "technical quality"},
        {"type": "boolean", "description": "material overlap"},
        {"type": "boolean", "description": "unusually long dead air"},
        {"type": "number", "minimum": 0, "maximum": 1, "description": "overall confidence"},
    ],
    "minItems": 9,
    "maxItems": 9,
}

SPEAKER_PROFILE_KEYS = (
    "speaker_profiles",
    "background_noise_present",
    "background_noise_type",
    "background_noise_severity",
    "audio_quality",
    "speaker_overlap_present",
    "long_silence_present",
    "confidence",
)

SPEAKER_PROFILE_SCHEMA = {
    "type": "array",
    "prefixItems": [
        {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "description": "one profile per distinct audible voice, in first-appearance order",
            "items": {
                "type": "array",
                "prefixItems": [
                    {"type": "string", "enum": ["neutral", "satisfied", "frustrated", "upset", "distressed"], "description": "primary tone of this voice over the call"},
                    {"type": "string", "enum": ["low", "medium", "high"], "description": "strength of that primary tone"},
                    {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "observable service-seeker behavior: states own issue, asks for help, accepts/rejects resolution",
                    },
                    {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "observable service-provider behavior: company greeting, verification, troubleshooting, offers resolution",
                    },
                    {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                        "description": "likelihood voice is TV, radio, bystander, or unrelated background speech",
                    },
                    {"type": "number", "minimum": 0, "maximum": 1, "description": "fraction of foreground conversation speech"},
                    {"type": "number", "minimum": 0, "maximum": 1, "description": "voice tracking and profile confidence"},
                ],
                "minItems": 7,
                "maxItems": 7,
            },
        },
        {"type": "boolean", "description": "meaningful background noise"},
        {"type": "string", "maxLength": 80, "description": "dominant noise under five words; empty if absent"},
        {"type": "string", "enum": ["none", "low", "medium", "high"]},
        {"type": "string", "enum": ["clear", "slightly_impaired", "severely_impaired"]},
        {"type": "boolean", "description": "material overlap"},
        {"type": "boolean", "description": "unusually long dead air"},
        {"type": "number", "minimum": 0, "maximum": 1},
    ],
    "minItems": 8,
    "maxItems": 8,
}


SYSTEM_INSTRUCTION = """You are a careful quality analyst for real customer-service call audio.
Classify the foreground CUSTOMER, never the agent or speech from a TV/radio. Infer roles from the greeting,
questions, requests, and service behavior. Use meaning and prosody together; loudness alone is not emotion.
Keep emotion, background sound, overlap, and technical quality independent. Return only the requested
structured object and never return a transcript or identifying details."""


def _prompt(features: AcousticFeatures) -> str:
    return """Analyze the entire clip against the assessment schema. The emotional_tone field is the primary
emotional tone expressed by the customer over the call. Neutral means no clear positive or negative emotion.
Satisfied means pleased, relieved, appreciative, or clearly positive. Frustrated means annoyed, impatient,
or dissatisfied without strong anger or distress. Upset means clearly angry, agitated, or strongly
dissatisfied. Distressed means highly emotional, overwhelmed, panicked, crying, or otherwise emotionally
escalated. Low intensity is subtle or mild; medium is clear and sustained; high is strong, escalated, or
likely to require attention. Do not choose an isolated peak merely because it is the strongest moment.

Treat background TV/radio dialogue as noise and possible overlap, but never as the customer's emotion.
Meaningful noise excludes faint codec artifacts. Describe only the dominant noise source. Technical audio
quality is independent of noise. Ordinary turn-taking pauses are not long silence. Use conservative,
calibrated confidence, especially when roles or sound sources are ambiguous. The fourth array value is
only a short noise-source label in the direct schema, never analysis or rationale. If the schema requests
continuous emotion evidence, score each dimension independently from 0 (absent) to 1 (strong and sustained),
and use valence from -1 (strongly negative) to 1 (strongly positive). If the schema requests customer
emotion episodes, mentally diarize the call, exclude agent and TV/radio speech, list distinct CUSTOMER
episodes strongest first, and never output words from the call. If the schema requests speaker profiles,
track each distinct voice across the clip and report only observable service-seeker, service-provider, and
background-source behavior scores; do not choose or rename a customer, and never output spoken words."""


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
            "response_json_schema": {
                "latent": LATENT_SCHEMA,
                "episodes": EPISODE_SCHEMA,
                "speaker_profiles": SPEAKER_PROFILE_SCHEMA,
                "transcript_local_profiles": SPEAKER_PROFILE_SCHEMA,
                "emotion_profiles": SPEAKER_PROFILE_SCHEMA,
            }.get(self._settings.gemini_emotion_strategy, COMPACT_SCHEMA),
        }
        return self._types.GenerateContentConfig(**kwargs)

    @staticmethod
    def _prediction_from_latent(values: list | tuple) -> Prediction:
        evidence = dict(zip(LATENT_KEYS, values))
        distress = float(evidence["distress"])
        anger = float(evidence["anger"])
        frustration = float(evidence["frustration"])
        satisfaction = float(evidence["satisfaction"])
        valence = float(evidence["valence"])
        arousal = float(evidence["arousal"])

        if distress >= 0.67:
            tone = "distressed"
        elif anger >= 0.62:
            tone = "upset"
        elif frustration >= 0.55 or valence <= -0.35:
            tone = "frustrated"
        elif satisfaction >= 0.55 or valence >= 0.35:
            tone = "satisfied"
        else:
            tone = "neutral"

        salience = max(distress, anger, frustration, satisfaction, abs(valence))
        combined_intensity = 0.60 * arousal + 0.40 * salience
        if combined_intensity >= 0.68:
            intensity = "high"
        elif combined_intensity >= 0.34:
            intensity = "medium"
        else:
            intensity = "low"

        confidence = min(float(evidence["confidence"]), float(evidence["role_certainty"]))
        return Prediction.model_validate(
            {
                "emotional_tone": tone,
                "emotional_intensity": intensity,
                "background_noise_present": evidence["background_noise_present"],
                "background_noise_type": evidence["background_noise_type"],
                "background_noise_severity": evidence["background_noise_severity"],
                "audio_quality": evidence["audio_quality"],
                "speaker_overlap_present": evidence["speaker_overlap_present"],
                "long_silence_present": evidence["long_silence_present"],
                "confidence": confidence,
            }
        )

    @staticmethod
    def _prediction_from_episodes(values: list | tuple) -> Prediction:
        evidence = dict(zip(EPISODE_KEYS, values))
        episodes = evidence["customer_emotion_episodes"]
        if not isinstance(episodes, list) or not episodes:
            raise ValueError("Customer emotion episodes cannot be empty")
        # The schema asks for strongest operational salience first, but score it
        # explicitly so imperfect ordering does not control the result.
        ranked = sorted(
            episodes,
            key=lambda item: float(item[2]) * (0.70 + 0.30 * float(item[3])),
            reverse=True,
        )
        tone, intensity, _, _ = ranked[0]
        confidence = min(float(evidence["confidence"]), float(evidence["role_certainty"]), 0.90)
        return Prediction.model_validate(
            {
                "emotional_tone": tone,
                "emotional_intensity": intensity,
                "background_noise_present": evidence["background_noise_present"],
                "background_noise_type": evidence["background_noise_type"],
                "background_noise_severity": evidence["background_noise_severity"],
                "audio_quality": evidence["audio_quality"],
                "speaker_overlap_present": evidence["speaker_overlap_present"],
                "long_silence_present": evidence["long_silence_present"],
                "confidence": confidence,
            }
        )

    @staticmethod
    def _prediction_from_speaker_profiles(
        values: list | tuple,
    ) -> tuple[Prediction, dict[str, float | bool | str]]:
        evidence = dict(zip(SPEAKER_PROFILE_KEYS, values))
        profiles = evidence["speaker_profiles"]
        if not isinstance(profiles, list) or not profiles:
            raise ValueError("Speaker profiles cannot be empty")

        scored: list[tuple[float, list | tuple]] = []
        for profile in profiles:
            _, _, seeker, provider, background, speech_fraction, certainty = profile
            role_score = (
                float(seeker)
                - 0.70 * float(provider)
                - 1.50 * float(background)
                + 0.05 * float(speech_fraction)
                + 0.05 * float(certainty)
            )
            scored.append((role_score, profile))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected_score, selected = scored[0]
        tone, intensity, _, _, _, _, profile_confidence = selected
        role_margin = selected_score - scored[1][0] if len(scored) > 1 else 0.0
        role_confidence = (
            0.78
            if len(scored) == 1
            else max(0.45, min(0.90, 0.60 + 0.25 * role_margin))
        )
        confidence = min(
            float(evidence["confidence"]),
            float(profile_confidence),
            role_confidence,
        )
        prediction = Prediction.model_validate(
            {
                "emotional_tone": tone,
                "emotional_intensity": intensity,
                "background_noise_present": evidence["background_noise_present"],
                "background_noise_type": evidence["background_noise_type"],
                "background_noise_severity": evidence["background_noise_severity"],
                "audio_quality": evidence["audio_quality"],
                "speaker_overlap_present": evidence["speaker_overlap_present"],
                "long_silence_present": evidence["long_silence_present"],
                "confidence": confidence,
            }
        )
        diagnostics: dict[str, float | bool | str] = {
            "speaker_profile_count": float(len(profiles)),
            "customer_role_score": round(selected_score, 3),
            "customer_role_margin": round(role_margin, 3),
        }
        for index, (role_score, profile) in enumerate(scored):
            tone_value, intensity_value, seeker, provider, background, speech_fraction, certainty = profile
            prefix = f"speaker_profile_{index + 1}"
            diagnostics.update(
                {
                    f"{prefix}_tone": str(tone_value),
                    f"{prefix}_intensity": str(intensity_value),
                    f"{prefix}_role_score": round(role_score, 3),
                    f"{prefix}_seeker": round(float(seeker), 3),
                    f"{prefix}_provider": round(float(provider), 3),
                    f"{prefix}_background": round(float(background), 3),
                    f"{prefix}_speech_fraction": round(float(speech_fraction), 3),
                    f"{prefix}_certainty": round(float(certainty), 3),
                }
            )
        return prediction, diagnostics

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
                prior_usage = Usage()
                diagnostics = None
                response_model = selected_model
                request_contents = contents
                transcript: str | None = None
                emotion_evidence: dict[str, float | str] | None = None
                transcript_strategies = {
                    "transcript_local",
                    "transcript_local_tagged",
                    "transcript_local_profiles",
                }
                if self._settings.gemini_emotion_strategy in transcript_strategies:
                    transcript_instruction = (
                        TAGGED_TRANSCRIPT_INSTRUCTION
                        if self._settings.gemini_emotion_strategy == "transcript_local_tagged"
                        else TRANSCRIPT_INSTRUCTION
                    )
                    transcript_response = self._client.models.generate_content(
                        model=selected_model,
                        contents=[contents[0], transcript_instruction],
                        config=self._types.GenerateContentConfig(
                            temperature=0.0,
                            max_output_tokens=4096,
                            thinking_config=self._types.ThinkingConfig(
                                thinking_level=self._types.ThinkingLevel.MINIMAL,
                                include_thoughts=False,
                            ),
                        ),
                    )
                    transcript = (transcript_response.text or "").strip()
                    if not transcript:
                        raise ValueError("Gemini returned no ephemeral speaker-turn transcript")
                    transcript_usage = getattr(transcript_response, "usage_metadata", None)
                    prior_usage = Usage(
                        input_tokens=int(getattr(transcript_usage, "prompt_token_count", 0) or 0),
                        output_tokens=int(getattr(transcript_usage, "candidates_token_count", 0) or 0),
                        thinking_tokens=int(getattr(transcript_usage, "thoughts_token_count", 0) or 0),
                        total_tokens=int(getattr(transcript_usage, "total_token_count", 0) or 0),
                    )
                elif self._settings.gemini_emotion_strategy == "emotion_profiles":
                    emotion_response = self._client.models.generate_content(
                        model=selected_model,
                        contents=[contents[0], CUSTOMER_EMOTION_INSTRUCTION],
                        config=self._types.GenerateContentConfig(
                            system_instruction=SYSTEM_INSTRUCTION,
                            temperature=0.0,
                            max_output_tokens=128,
                            thinking_config=self._types.ThinkingConfig(
                                thinking_level=self._types.ThinkingLevel.MINIMAL,
                                include_thoughts=False,
                            ),
                            response_mime_type="application/json",
                            response_json_schema=CUSTOMER_EMOTION_SCHEMA,
                        ),
                    )
                    if getattr(emotion_response, "parsed", None) is not None:
                        raw_emotion = emotion_response.parsed
                    elif emotion_response.text:
                        raw_emotion = json.loads(emotion_response.text)
                    else:
                        raise ValueError("Gemini returned no structured customer-emotion output")
                    if not isinstance(raw_emotion, (list, tuple)) or len(raw_emotion) != len(CUSTOMER_EMOTION_KEYS):
                        raise ValueError("Gemini customer-emotion response did not match the compact contract")
                    emotion_evidence = dict(zip(CUSTOMER_EMOTION_KEYS, raw_emotion))
                    emotion_usage = getattr(emotion_response, "usage_metadata", None)
                    prior_usage = Usage(
                        input_tokens=int(getattr(emotion_usage, "prompt_token_count", 0) or 0),
                        output_tokens=int(getattr(emotion_usage, "candidates_token_count", 0) or 0),
                        thinking_tokens=int(getattr(emotion_usage, "thoughts_token_count", 0) or 0),
                        total_tokens=int(getattr(emotion_usage, "total_token_count", 0) or 0),
                    )
                response = self._client.models.generate_content(
                    model=response_model,
                    contents=request_contents,
                    config=self._config(response_model),
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
                expected_length = {
                    "latent": len(LATENT_KEYS),
                    "episodes": len(EPISODE_KEYS),
                    "speaker_profiles": len(SPEAKER_PROFILE_KEYS),
                    "transcript_local_profiles": len(SPEAKER_PROFILE_KEYS),
                    "emotion_profiles": len(SPEAKER_PROFILE_KEYS),
                }.get(self._settings.gemini_emotion_strategy, len(COMPACT_KEYS))
                if not isinstance(raw_prediction, (list, tuple)) or len(raw_prediction) != expected_length:
                    raise ValueError("Gemini response did not match the configured compact contract")
                if self._settings.gemini_emotion_strategy == "latent":
                    prediction = self._prediction_from_latent(raw_prediction)
                elif self._settings.gemini_emotion_strategy == "episodes":
                    prediction = self._prediction_from_episodes(raw_prediction)
                elif self._settings.gemini_emotion_strategy in {
                    "speaker_profiles",
                    "transcript_local_profiles",
                    "emotion_profiles",
                }:
                    prediction, diagnostics = self._prediction_from_speaker_profiles(raw_prediction)
                else:
                    prediction = Prediction.model_validate(dict(zip(COMPACT_KEYS, raw_prediction)))
                if self._settings.gemini_emotion_strategy in {
                    "transcript_local",
                    "transcript_local_tagged",
                    "transcript_local_profiles",
                } and transcript is not None:
                    prediction, transcript_diagnostics = analyze_transcript_emotion(transcript, prediction)
                    diagnostics = {**(diagnostics or {}), **transcript_diagnostics}
                if emotion_evidence is not None:
                    emotion_data = prediction.model_dump()
                    emotion_data["emotional_tone"] = emotion_evidence["emotional_tone"]
                    emotion_data["emotional_intensity"] = emotion_evidence["emotional_intensity"]
                    emotion_data["confidence"] = min(
                        float(prediction.confidence),
                        float(emotion_evidence["role_certainty"]),
                        float(emotion_evidence["emotion_confidence"]),
                    )
                    prediction = Prediction.model_validate(emotion_data)
                    diagnostics = {
                        **(diagnostics or {}),
                        "emotion_role_certainty": round(float(emotion_evidence["role_certainty"]), 3),
                        "emotion_confidence": round(float(emotion_evidence["emotion_confidence"]), 3),
                    }
                usage_meta = getattr(response, "usage_metadata", None)
                input_tokens = prior_usage.input_tokens + int(getattr(usage_meta, "prompt_token_count", 0) or 0)
                output_tokens = prior_usage.output_tokens + int(getattr(usage_meta, "candidates_token_count", 0) or 0)
                thinking_tokens = prior_usage.thinking_tokens + int(getattr(usage_meta, "thoughts_token_count", 0) or 0)
                total_tokens = prior_usage.total_tokens + int(getattr(usage_meta, "total_token_count", 0) or 0)
                request_id = None
                sdk_response = getattr(response, "sdk_http_response", None)
                if sdk_response is not None:
                    headers = getattr(sdk_response, "headers", {}) or {}
                    request_id = headers.get("x-request-id") or headers.get("x-goog-request-id")
                return InferenceOutcome(
                    prediction=prediction,
                    model=(
                        f"{selected_model}+{response_model}"
                        if self._settings.gemini_emotion_strategy in transcript_strategies | {"emotion_profiles"}
                        else selected_model
                    ),
                    latency_seconds=time.perf_counter() - started,
                    usage=Usage(input_tokens, output_tokens, thinking_tokens, total_tokens),
                    provider_request_id=request_id,
                    diagnostics=diagnostics,
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
