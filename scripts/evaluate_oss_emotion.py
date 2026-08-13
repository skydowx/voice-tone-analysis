#!/usr/bin/env python3
"""Reproduce the local emotion2vec+ tone challenger on the labelled calls."""

from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
import statistics
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.evaluation import class_metrics


MODEL_ID = "emotion2vec/emotion2vec_plus_base"
MODEL_REVISION = "b318240bfe67db81a8c572ecb37ce9c3759b81c9"
CHUNK_SECONDS = 30
LABEL_MAP = {
    "angry": "upset",
    "disgusted": "frustrated",
    "fearful": "distressed",
    "happy": "satisfied",
    "neutral": "neutral",
    "other": "neutral",
    "sad": "distressed",
    "surprised": "neutral",
    "unknown": "neutral",
}


def normalize_label(value: str) -> str:
    label = value.lower().strip()
    if "/" in label:
        label = label.rsplit("/", 1)[-1]
    label = label.strip(" _-")
    return "unknown" if label in {"<unk>", "unk"} else label


def expected_tones(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {
        row["name"]: json.loads(row["result_json"])["emotional_tone"]
        for row in rows
        if row.get("result_json")
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=Path("labels.csv"))
    parser.add_argument("--cache-dir", type=Path, default=Path("/tmp/autoace-oss-cache"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/oss_emotion2vec_evaluation.json"))
    args = parser.parse_args()

    from funasr import AutoModel
    from huggingface_hub import snapshot_download

    args.cache_dir.mkdir(parents=True, exist_ok=True)
    download_started = time.perf_counter()
    model_path = snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        cache_dir=args.cache_dir,
    )
    download_seconds = time.perf_counter() - download_started
    load_started = time.perf_counter()
    model = AutoModel(model=model_path, device="cpu", disable_update=True)
    load_seconds = time.perf_counter() - load_started

    expected = expected_tones(args.labels)
    items = []
    with tempfile.TemporaryDirectory(prefix="autoace-oss-eval-") as temp_dir:
        for index, (name, expected_tone) in enumerate(sorted(expected.items()), start=1):
            chunk_dir = Path(temp_dir) / str(index)
            chunk_dir.mkdir()
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(args.labels.parent / name),
                    "-f",
                    "segment",
                    "-segment_time",
                    str(CHUNK_SECONDS),
                    "-reset_timestamps",
                    "1",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    str(chunk_dir / "%03d.wav"),
                ],
                check=True,
            )
            started = time.perf_counter()
            score_totals: dict[str, float] = {}
            total_seconds = 0.0
            chunks = sorted(chunk_dir.glob("*.wav"))
            for chunk in chunks:
                with wave.open(str(chunk), "rb") as handle:
                    chunk_seconds = handle.getnframes() / handle.getframerate()
                result = model.generate(
                    input=str(chunk),
                    granularity="utterance",
                    extract_embedding=False,
                )[0]
                for native, score in zip(result["labels"], result["scores"]):
                    label = normalize_label(native)
                    score_totals[label] = score_totals.get(label, 0.0) + float(score) * chunk_seconds
                total_seconds += chunk_seconds
            latency = time.perf_counter() - started
            ranked = sorted(
                ((label, score / total_seconds) for label, score in score_totals.items()),
                key=lambda pair: pair[1],
                reverse=True,
            )
            native_label, top_score = ranked[0]
            predicted_tone = LABEL_MAP[native_label]
            items.append(
                {
                    "name": name,
                    "expected_tone": expected_tone,
                    "native_label": native_label,
                    "predicted_tone": predicted_tone,
                    "top_score": top_score,
                    "chunk_count": len(chunks),
                    "latency_seconds": latency,
                    "native_scores": dict(ranked),
                }
            )
            print(
                f"[{index}/{len(expected)}] {name}: {native_label} -> {predicted_tone} "
                f"(expected {expected_tone}, {latency:.2f}s)",
                flush=True,
            )

    expected_values = [item["expected_tone"] for item in items]
    predicted_values = [item["predicted_tone"] for item in items]
    per_class = class_metrics(expected_values, predicted_values)
    observed = sorted(set(expected_values))
    payload = {
        "experiment_id": "oss_emotion2vec_plus_base_v1",
        "model": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "model_license": "custom model license; research challenger only, review before production use",
        "scope": "whole-call emotional_tone challenger only; no customer diarization and no other schema fields",
        "aggregation": f"duration-weighted mean of non-overlapping {CHUNK_SECONDS}-second utterance scores",
        "label_mapping": LABEL_MAP,
        "sample_count": len(items),
        "tone_accuracy": statistics.fmean(e == p for e, p in zip(expected_values, predicted_values)),
        "tone_macro_f1_observed": statistics.fmean(per_class[label]["f1"] for label in observed),
        "tone_per_class": per_class,
        "cost_per_audio_minute_usd": 0.0,
        "checkpoint_download_seconds_this_run": download_seconds,
        "checkpoint_download_note": "Excluded from inference latency; cached runs should be near zero.",
        "model_load_seconds": load_seconds,
        "inference_latency_seconds": {
            "total": sum(item["latency_seconds"] for item in items),
            "mean": statistics.fmean(item["latency_seconds"] for item in items),
        },
        "runtime": {
            package: importlib.metadata.version(package)
            for package in ("torch", "torchaudio", "funasr", "huggingface-hub", "soundfile")
        },
        "items": items,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({key: payload[key] for key in ("tone_accuracy", "tone_macro_f1_observed", "inference_latency_seconds")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
