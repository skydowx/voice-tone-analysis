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
    broadband_transient_seconds: float
    broadband_transient_bursts: int
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
    broadband_transient_frames = 0
    broadband_transient_bursts = 0
    transient_run = 0
    for start in range(0, len(samples), frame_size):
        frame = samples[start : start + frame_size]
        if not frame:
            continue
        frame_rms = math.sqrt(sum(float(x) * float(x) for x in frame) / len(frame))
        zero_crossing_ratio = sum(
            (frame[index] < 0) != (frame[index - 1] < 0) for index in range(1, len(frame))
        ) / max(len(frame) - 1, 1)
        difference_rms = math.sqrt(
            sum(
                float(frame[index] - frame[index - 1]) ** 2
                for index in range(1, len(frame))
            )
            / max(len(frame) - 1, 1)
        )
        is_broadband_transient = (
            frame_rms >= 32768.0 * (10 ** (-30.0 / 20.0))
            and zero_crossing_ratio >= 0.45
            and difference_rms / max(frame_rms, 1.0) >= 1.30
        )
        if is_broadband_transient:
            broadband_transient_frames += 1
            transient_run += 1
        else:
            if transient_run >= 2:
                broadband_transient_bursts += 1
            transient_run = 0
        total_frames += 1
        if frame_rms >= active_threshold:
            active_frames += 1
        if frame_rms < silence_threshold:
            silent_run += 1
            longest_silent_run = max(longest_silent_run, silent_run)
        else:
            silent_run = 0
    if transient_run >= 2:
        broadband_transient_bursts += 1

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
        broadband_transient_seconds=round(broadband_transient_frames * frame_size / rate, 3),
        broadband_transient_bursts=broadband_transient_bursts,
        long_silence_present=max_silence >= long_silence_seconds,
        heuristic_audio_quality=quality,
    )


def compact_active_speech(source: Path, destination: Path) -> float:
    """Remove long low-energy regions while preserving short turn boundaries.

    This is intentionally an energy view rather than claimed diarization. It is
    cheap, language-independent, reversible, and keeps 300 ms of context around
    activity so consonants and normal conversational pauses are not clipped.
    Returns the compacted/original duration ratio.
    """
    try:
        with wave.open(str(source), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            raw = wav.readframes(wav.getnframes())
    except (wave.Error, OSError) as exc:
        raise AudioProcessingError(f"Could not compact normalized audio: {exc}") from exc
    if channels != 1 or width != 2 or rate <= 0:
        raise AudioProcessingError("Speech compaction requires normalized 16-bit mono WAV")

    samples = array("h")
    samples.frombytes(raw)
    frame_samples = max(1, int(rate * 0.02))
    energies: list[float] = []
    for start in range(0, len(samples), frame_samples):
        frame = samples[start : start + frame_samples]
        energies.append(math.sqrt(sum(float(x) * float(x) for x in frame) / max(len(frame), 1)))
    if not energies:
        raise AudioProcessingError("Speech compaction received empty audio")

    sorted_energies = sorted(energies)
    noise_floor = sorted_energies[max(0, int(len(sorted_energies) * 0.20) - 1)]
    absolute_floor = 32768.0 * (10 ** (-48.0 / 20.0))
    threshold = max(absolute_floor, noise_floor * 3.0)
    active = [energy >= threshold for energy in energies]

    pad_frames = int(0.30 / 0.02)
    bridge_frames = int(0.50 / 0.02)
    active_indices = [index for index, value in enumerate(active) if value]
    if not active_indices:
        shutil.copyfile(source, destination)
        return 1.0
    ranges: list[list[int]] = []
    for index in active_indices:
        start = max(0, index - pad_frames)
        end = min(len(active), index + pad_frames + 1)
        if ranges and start <= ranges[-1][1] + bridge_frames:
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([start, end])

    separator = array("h", [0] * int(rate * 0.12))
    compacted = array("h")
    for number, (start_frame, end_frame) in enumerate(ranges):
        if number:
            compacted.extend(separator)
        compacted.extend(samples[start_frame * frame_samples : min(len(samples), end_frame * frame_samples)])
    if len(compacted) / max(len(samples), 1) > 0.92:
        shutil.copyfile(source, destination)
        return 1.0

    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(compacted.tobytes())
    return len(compacted) / len(samples)
