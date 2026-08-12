#!/usr/bin/env python3
"""Run the labelled assessment clips through the real configured Gemini model."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from app.config import Settings
from app.services.classifier import AudioClassifier
from app.services.inference.gemini import GeminiProvider


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=Path("labels.csv"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/live"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--thinking-level", choices=("minimal", "low"), default=None)
    parser.add_argument(
        "--emotion-strategy",
        choices=(
            "direct",
            "latent",
            "episodes",
            "speaker_profiles",
            "transcript_local",
            "transcript_local_tagged",
            "transcript_local_profiles",
        ),
        default=None,
    )
    parser.add_argument("--audio-view", choices=("full", "speech_compact", "dual"), default=None)
    args = parser.parse_args()

    settings = Settings()
    if args.thinking_level:
        settings.gemini_thinking_level = args.thinking_level
    if args.emotion_strategy:
        settings.gemini_emotion_strategy = args.emotion_strategy
    if args.audio_view:
        settings.gemini_audio_view = args.audio_view
    if settings.gemini_api_key is None:
        parser.error("GEMINI_API_KEY is not configured")
    settings.ensure_directories()
    model = args.model or settings.gemini_model
    provider = GeminiProvider(settings)
    classifier = AudioClassifier(provider, settings)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    with args.labels.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    predictions: list[dict[str, str]] = []
    audit: list[dict] = []
    for index, row in enumerate(rows, start=1):
        name = row["name"]
        source = args.labels.parent / name
        print(f"[{index}/{len(rows)}] analyzing {name} with {model}", flush=True)
        envelope = classifier.analyze(source, model=model)
        payload = envelope.prediction.model_dump(mode="json")
        predictions.append({"name": name, "result_json": json.dumps(payload, separators=(",", ":"))})
        audit.append({"name": name, **envelope.model_dump(mode="json")})
        print(
            f"  complete in {envelope.latency_seconds:.2f}s; "
            f"${envelope.cost_per_audio_minute_usd:.6f}/audio-min",
            flush=True,
        )

    with (args.output_dir / "predictions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "result_json"])
        writer.writeheader()
        writer.writerows(predictions)
    (args.output_dir / "audit.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "model": model,
                "prompt_version": audit[0]["prompt_version"] if audit else None,
                "items": audit,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {args.output_dir / 'predictions.csv'} and audit.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
