from __future__ import annotations

import math
import tempfile
import time
from pathlib import Path

from app.config import Settings
from app.schemas.prediction import AudioQuality, Prediction, PredictionEnvelope
from app.services.audio import AcousticFeatures, analyze_pcm, normalize_audio
from app.services.inference.base import InferenceProvider
from app.services.inference.gemini import PROMPT_VERSION


MODEL_RATES = {
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-3.1-flash-lite": (0.50, 1.50),
    "gemini-3.5-flash": (1.50, 9.00),
    "gemini-3-flash-preview": (1.00, 3.00),
    "gemini-2.5-flash": (1.00, 2.50),
}


def estimate_cost(model: str, input_tokens: int, output_tokens: int, thinking_tokens: int) -> float:
    # Unknown models use a deliberately conservative rate so configuration drift
    # cannot make the dashboard under-report cost.
    input_rate, output_rate = MODEL_RATES.get(model, (1.50, 9.00))
    return (input_tokens * input_rate + (output_tokens + thinking_tokens) * output_rate) / 1_000_000


def _reconcile(prediction: Prediction, features: AcousticFeatures) -> Prediction:
    data = prediction.model_dump()
    # A fixed signal definition is more reproducible than an LLM's subjective
    # interpretation of ordinary conversational pauses.
    data["long_silence_present"] = features.long_silence_present

    severe_signal_problem = (
        features.clipping_ratio >= 0.08
        or features.rms_dbfs <= -42
        or features.active_audio_ratio < 0.05
    )
    if severe_signal_problem and prediction.audio_quality == AudioQuality.clear:
        data["audio_quality"] = AudioQuality.severely_impaired.value
    elif (
        features.heuristic_audio_quality == AudioQuality.clear
        and prediction.audio_quality == AudioQuality.slightly_impaired
        and prediction.background_noise_present
    ):
        # Prevent an audible background source from being double-counted as a
        # technical defect when the signal itself is healthy.
        data["audio_quality"] = AudioQuality.clear.value

    penalty = 0.0
    if features.duration_seconds < 10:
        penalty += 0.12
    if features.active_audio_ratio < 0.12:
        penalty += 0.12
    if severe_signal_problem and prediction.audio_quality == AudioQuality.clear:
        penalty += 0.10
    data["confidence"] = round(max(0.05, min(0.85, prediction.confidence - penalty)), 3)
    return Prediction.model_validate(data)


class AudioClassifier:
    def __init__(self, provider: InferenceProvider, settings: Settings):
        self.provider = provider
        self.settings = settings

    def analyze(self, source: Path, model: str | None = None) -> PredictionEnvelope:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="autoace-audio-") as temp_dir:
            normalized = Path(temp_dir) / "normalized.wav"
            original_probe = normalize_audio(source, normalized)
            features = analyze_pcm(normalized, self.settings.long_silence_seconds)
            outcome = self.provider.analyze(normalized, features, model=model)
        prediction = _reconcile(outcome.prediction, features)
        cost = estimate_cost(
            outcome.model,
            outcome.usage.input_tokens,
            outcome.usage.output_tokens,
            outcome.usage.thinking_tokens,
        )
        duration_minutes = max(original_probe.duration_seconds / 60.0, 1 / 60.0)
        return PredictionEnvelope(
            prediction=prediction,
            model=outcome.model,
            prompt_version=PROMPT_VERSION,
            duration_seconds=round(original_probe.duration_seconds, 3),
            latency_seconds=round(time.perf_counter() - started, 3),
            input_tokens=outcome.usage.input_tokens,
            output_tokens=outcome.usage.output_tokens,
            thinking_tokens=outcome.usage.thinking_tokens,
            estimated_cost_usd=round(cost, 8),
            cost_per_audio_minute_usd=round(cost / duration_minutes, 8),
            features=features.as_dict(),
        )
