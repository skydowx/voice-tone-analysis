from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from array import array
from dataclasses import asdict, dataclass
from pathlib import Path


class AudioProcessingError(RuntimeError):
    pass


@dataclass(frozen=True)
class AudioProbe:
    duration_seconds: float
    codec: str
    sample_rate: int
    channels: int
    bit_rate: int | None
    format_name: str


@dataclass(frozen=True)
class AcousticFeatures:
    duration_seconds: float
    rms_dbfs: float
    peak_dbfs: float
    clipping_ratio: float
    active_audio_ratio: float
    max_silence_seconds: float
    long_silence_present: bool
    heuristic_audio_quality: str

    def as_dict(self) -> dict[str, float | bool | str]:
        return asdict(self)


def _require_binary(name: str) -> str:
    binary = shutil.which(name)
    if not binary:
        raise AudioProcessingError(f"Required executable is not installed: {name}")
    return binary


def probe_audio(path: Path) -> AudioProbe:
    command = [
        _require_binary("ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration,bit_rate,format_name:stream=codec_name,sample_rate,channels",
        "-select_streams",
        "a:0",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        fmt = payload["format"]
        duration = float(fmt.get("duration") or 0)
        if duration <= 0:
            raise ValueError("duration is zero")
        return AudioProbe(
            duration_seconds=duration,
            codec=str(stream.get("codec_name") or "unknown"),
            sample_rate=int(stream.get("sample_rate") or 0),
            channels=int(stream.get("channels") or 0),
            bit_rate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None,
            format_name=str(fmt.get("format_name") or "unknown"),
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, KeyError, ValueError, json.JSONDecodeError) as exc:
        detail = getattr(exc, "stderr", None) or str(exc)
        raise AudioProcessingError(f"Unsupported or malformed audio: {detail.strip()}") from exc


def normalize_audio(source: Path, destination: Path) -> AudioProbe:
    probe = probe_audio(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    command = [
        _require_binary("ffmpeg"),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(destination),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=120)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        destination.unlink(missing_ok=True)
        detail = getattr(exc, "stderr", None) or str(exc)
        raise AudioProcessingError(f"Audio normalization failed: {detail.strip()}") from exc
    return probe


def _dbfs(value: float) -> float:
    if value <= 0:
        return -120.0
    return 20.0 * math.log10(value / 32768.0)


def analyze_pcm(path: Path, long_silence_seconds: float = 10.0) -> AcousticFeatures:
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise AudioProcessingError("Expected normalized 16-bit mono WAV")
            rate = wav.getframerate()
            samples = array("h", wav.readframes(wav.getnframes()))
    except (wave.Error, OSError) as exc:
        raise AudioProcessingError(f"Could not read normalized audio: {exc}") from exc

    if not samples or rate <= 0:
        raise AudioProcessingError("Normalized audio contains no samples")

    squared = sum(float(sample) * float(sample) for sample in samples)
    rms = math.sqrt(squared / len(samples))
    peak = max(abs(sample) for sample in samples)
    clipping_ratio = sum(1 for sample in samples if abs(sample) >= 32700) / len(samples)

    frame_size = max(1, int(rate * 0.02))
    silence_threshold = 32768.0 * (10 ** (-45.0 / 20.0))
    active_threshold = 32768.0 * (10 ** (-42.0 / 20.0))
    silent_run = 0
    longest_silent_run = 0
    active_frames = 0
    total_frames = 0
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        if not frame:
            continue
        frame_rms = math.sqrt(sum(float(x) * float(x) for x in frame) / len(frame))
        total_frames += 1
        if frame_rms >= active_threshold:
            active_frames += 1
        if frame_rms < silence_threshold:
            silent_run += 1
            longest_silent_run = max(longest_silent_run, silent_run)
        else:
            silent_run = 0

    active_ratio = active_frames / max(total_frames, 1)
    max_silence = longest_silent_run * frame_size / rate
    rms_dbfs = _dbfs(rms)
    if clipping_ratio >= 0.08 or rms_dbfs <= -42 or active_ratio < 0.05:
        quality = "severely_impaired"
    elif clipping_ratio >= 0.01 or rms_dbfs <= -32 or active_ratio < 0.15:
        quality = "slightly_impaired"
    else:
        quality = "clear"

    return AcousticFeatures(
        duration_seconds=len(samples) / rate,
        rms_dbfs=round(rms_dbfs, 3),
        peak_dbfs=round(_dbfs(float(peak)), 3),
        clipping_ratio=round(clipping_ratio, 8),
        active_audio_ratio=round(active_ratio, 5),
        max_silence_seconds=round(max_silence, 3),
        long_silence_present=max_silence >= long_silence_seconds,
        heuristic_audio_quality=quality,
    )
