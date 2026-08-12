from __future__ import annotations

from app.services.audio import analyze_pcm, normalize_audio, probe_audio
from app.services.classifier import _reconcile
from app.schemas.prediction import Prediction

from .conftest import write_wav


def test_probe_normalize_and_signal_features(tmp_path):
    source = write_wav(tmp_path / "source.wav", seconds=1.0)
    normalized = tmp_path / "normalized.wav"
    probe = normalize_audio(source, normalized)
    features = analyze_pcm(normalized, long_silence_seconds=2.0)

    assert 0.95 <= probe.duration_seconds <= 1.05
    assert probe_audio(normalized).sample_rate == 16_000
    assert features.active_audio_ratio > 0.9
    assert features.long_silence_present is False


def test_long_silence_detector(tmp_path):
    source = write_wav(tmp_path / "silence.wav", seconds=3.5, silence_after=0.5)
    features = analyze_pcm(source, long_silence_seconds=2.0)
    assert features.long_silence_present is True
    assert features.max_silence_seconds >= 2.9


def test_deterministic_silence_overrides_model_false_positive(tmp_path):
    source = write_wav(tmp_path / "ordinary.wav", seconds=1.0)
    features = analyze_pcm(source, long_silence_seconds=2.0)
    prediction = Prediction(
        emotional_tone="neutral",
        emotional_intensity="low",
        background_noise_present=True,
        background_noise_type="static",
        background_noise_severity="low",
        audio_quality="slightly_impaired",
        speaker_overlap_present=False,
        long_silence_present=True,
        confidence=0.99,
    )
    result = _reconcile(prediction, features)
    assert result.long_silence_present is False
    assert result.audio_quality == "clear"
    assert result.confidence == 0.85
