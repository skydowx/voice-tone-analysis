from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EmotionalTone(str, Enum):
    neutral = "neutral"
    satisfied = "satisfied"
    frustrated = "frustrated"
    upset = "upset"
    distressed = "distressed"


class EmotionalIntensity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class BackgroundNoiseSeverity(str, Enum):
    none = "none"
    low = "low"
    medium = "medium"
    high = "high"


class AudioQuality(str, Enum):
    clear = "clear"
    slightly_impaired = "slightly_impaired"
    severely_impaired = "severely_impaired"


class Prediction(BaseModel):
    """The exact public contract required by the assessment."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    emotional_tone: EmotionalTone = Field(
        description="Primary emotional tone expressed by the customer, not the agent."
    )
    emotional_intensity: EmotionalIntensity = Field(
        description="Strength and sustained nature of the customer's emotional tone."
    )
    background_noise_present: bool = Field(
        description="Whether meaningful non-speech background sound is audible."
    )
    background_noise_type: str = Field(
        max_length=80,
        description="Concise dominant noise description; empty when noise is absent."
    )
    background_noise_severity: BackgroundNoiseSeverity
    audio_quality: AudioQuality
    speaker_overlap_present: bool
    long_silence_present: bool
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator("background_noise_type")
    @classmethod
    def normalize_noise_type(cls, value: str) -> str:
        return " ".join(value.strip().split())

    @model_validator(mode="after")
    def validate_noise_consistency(self) -> "Prediction":
        if not self.background_noise_present:
            if self.background_noise_type:
                raise ValueError("background_noise_type must be empty when noise is absent")
            if self.background_noise_severity != "none":
                raise ValueError("background_noise_severity must be none when noise is absent")
        else:
            if not self.background_noise_type:
                raise ValueError("background_noise_type is required when noise is present")
            if self.background_noise_severity == "none":
                raise ValueError("noise severity cannot be none when noise is present")
        return self


class PredictionEnvelope(BaseModel):
    prediction: Prediction
    model: str
    prompt_version: str
    duration_seconds: float
    latency_seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    estimated_cost_usd: float = 0.0
    cost_per_audio_minute_usd: float = 0.0
    features: dict[str, float | bool | str]
