from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.schemas.prediction import Prediction
from app.services.audio import AcousticFeatures


@dataclass(frozen=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True)
class InferenceOutcome:
    prediction: Prediction
    model: str
    latency_seconds: float
    usage: Usage
    provider_request_id: str | None = None
    diagnostics: dict[str, float | bool | str] | None = None


class InferenceProvider(Protocol):
    def analyze(self, audio_path: Path, features: AcousticFeatures, model: str | None = None) -> InferenceOutcome:
        ...
