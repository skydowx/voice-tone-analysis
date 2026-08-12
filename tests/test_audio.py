from __future__ import annotations

import struct
import wave

from app.services.audio import analyze_pcm, compact_active_speech, normalize_audio, probe_audio
from app.services.classifier import AudioClassifier, _reconcile
from app.schemas.prediction import Prediction
from app.services.inference.base import InferenceOutcome, Usage

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


def test_speech_compaction_removes_long_silence_but_preserves_signal(tmp_path):
    source = write_wav(tmp_path / "sparse.wav", seconds=5.0, silence_after=1.0)
    destination = tmp_path / "compact.wav"
    ratio = compact_active_speech(source, destination)
    probe = probe_audio(destination)
    features = analyze_pcm(destination)
    assert 0.15 < ratio < 0.5
    assert 1.0 < probe.duration_seconds < 2.5
    assert features.active_audio_ratio > 0.5


def test_dual_view_keeps_full_tone_and_focused_detection(tmp_path, settings):
    class SequencedProvider:
        def __init__(self):
            self.calls = 0

        def analyze(self, audio_path, features, model=None):
            self.calls += 1
            full = self.calls == 1
            return InferenceOutcome(
                prediction=Prediction(
                    emotional_tone="upset" if full else "neutral",
                    emotional_intensity="high" if full else "medium",
                    background_noise_present=not full,
                    background_noise_type="television" if not full else "",
                    background_noise_severity="medium" if not full else "none",
                    audio_quality="clear",
                    speaker_overlap_present=not full,
                    long_silence_present=False,
                    confidence=0.8,
                ),
                model="gemini-3.1-flash-lite",
                latency_seconds=0.1,
                usage=Usage(input_tokens=100, output_tokens=20, total_tokens=120),
            )

    source = write_wav(tmp_path / "dual.wav", seconds=5.0, silence_after=1.0)
    settings.gemini_audio_view = "dual"
    provider = SequencedProvider()
    envelope = AudioClassifier(provider, settings).analyze(source)
    assert provider.calls == 2
    assert envelope.prediction.emotional_tone == "upset"
    assert envelope.prediction.emotional_intensity == "medium"
    assert envelope.prediction.background_noise_type == "television"
    assert envelope.input_tokens == 200


def test_broadband_transient_detector_recovers_sharp_static(tmp_path):
    source = tmp_path / "static.wav"
    rate = 16_000
    samples = [0] * (rate * 2)
    for burst in range(8):
        start = int((0.15 + burst * 0.20) * rate)
        for index in range(start, start + int(0.06 * rate)):
            samples[index] = 9_000 if index % 2 == 0 else -9_000
    with wave.open(str(source), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(struct.pack("<h", value) for value in samples))

    features = analyze_pcm(source)
    assert features.broadband_transient_seconds >= 0.20
    assert features.broadband_transient_bursts >= 3
    prediction = Prediction(
        emotional_tone="neutral",
        emotional_intensity="low",
        background_noise_present=False,
        background_noise_type="",
        background_noise_severity="none",
        audio_quality="clear",
        speaker_overlap_present=False,
        long_silence_present=False,
        confidence=0.8,
    )
    result = _reconcile(prediction, features)
    assert result.background_noise_present is True
    assert result.background_noise_type == "sharp static"
    assert result.background_noise_severity == "medium"
