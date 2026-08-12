#!/usr/bin/env python3
"""Score predictions against labels and produce a reproducible report."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
import statistics
from collections import Counter
from pathlib import Path

from app.schemas.prediction import Prediction


CATEGORICAL_FIELDS = [
    "emotional_tone",
    "emotional_intensity",
    "background_noise_present",
    "background_noise_severity",
    "audio_quality",
    "speaker_overlap_present",
    "long_silence_present",
]


def load_csv(path: Path) -> dict[str, dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    result: dict[str, dict] = {}
    for row in rows:
        if not row.get("result_json"):
            continue
        result[row["name"]] = Prediction.model_validate_json(row["result_json"]).model_dump(mode="json")
    return result


def normalized_noise(value: str) -> str:
    value = " ".join(value.lower().strip().split())
    aliases = {"tv": "television", "sharp static noise": "sharp static", "static": "sharp static"}
    return aliases.get(value, value)


def noise_type_matches(expected: str, predicted: str) -> bool:
    expected_value = normalized_noise(expected)
    predicted_value = normalized_noise(predicted)
    if expected_value == predicted_value:
        return True
    synonym_groups = (
        {"tv", "television", "movie", "radio"},
        {"static", "crackle", "sharp static"},
    )
    return any(
        any(term in expected_value for term in group)
        and any(term in predicted_value for term in group)
        for group in synonym_groups
    )


def class_metrics(expected_values: list[str], predicted_values: list[str], classes: list[str]) -> dict:
    metrics = {}
    for label in classes:
        true_positive = sum(e == label and p == label for e, p in zip(expected_values, predicted_values))
        false_positive = sum(e != label and p == label for e, p in zip(expected_values, predicted_values))
        false_negative = sum(e == label and p != label for e, p in zip(expected_values, predicted_values))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[label] = {"precision": precision, "recall": recall, "f1": f1}
    return metrics


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--labels", type=Path, default=Path("labels.csv"))
    parser.add_argument("--predictions", type=Path, default=Path("artifacts/provided_predictions.csv"))
    parser.add_argument("--audit", type=Path, default=Path("artifacts/provided_audit.json"))
    parser.add_argument("--json-output", type=Path, default=Path("artifacts/evaluation.json"))
    parser.add_argument("--markdown-output", type=Path, default=Path("docs/EVALUATION.md"))
    parser.add_argument("--experiment-id", default=None)
    parser.add_argument("--experiment-description", default="")
    parser.add_argument("--experiment-log", type=Path, default=Path("artifacts/experiments.json"))
    args = parser.parse_args()

    expected = load_csv(args.labels)
    predicted = load_csv(args.predictions)
    names = sorted(expected.keys() & predicted.keys())
    if not names:
        parser.error("No matching labelled predictions")

    accuracy = {
        field: sum(expected[name][field] == predicted[name][field] for name in names) / len(names)
        for field in CATEGORICAL_FIELDS
    }
    noise_type_accuracy = sum(
        noise_type_matches(
            expected[name]["background_noise_type"], predicted[name]["background_noise_type"]
        )
        for name in names
    ) / len(names)
    confidence_mae = statistics.fmean(
        abs(expected[name]["confidence"] - predicted[name]["confidence"]) for name in names
    )
    exact_match = sum(
        all(expected[name][field] == predicted[name][field] for field in CATEGORICAL_FIELDS)
        and noise_type_matches(
            expected[name]["background_noise_type"], predicted[name]["background_noise_type"]
        )
        for name in names
    ) / len(names)
    confusion = Counter(
        (expected[name]["emotional_tone"], predicted[name]["emotional_tone"]) for name in names
    )
    tone_classes = ["neutral", "satisfied", "frustrated", "upset", "distressed"]
    tone_metrics = class_metrics(
        [expected[name]["emotional_tone"] for name in names],
        [predicted[name]["emotional_tone"] for name in names],
        tone_classes,
    )
    macro_f1 = statistics.fmean(metric["f1"] for metric in tone_metrics.values())
    observed_tone_classes = sorted({expected[name]["emotional_tone"] for name in names})
    observed_macro_f1 = statistics.fmean(tone_metrics[label]["f1"] for label in observed_tone_classes)

    audit_payload = json.loads(args.audit.read_text(encoding="utf-8")) if args.audit.exists() else {"items": []}
    audit_items = audit_payload.get("items", [])
    latencies = [float(item["latency_seconds"]) for item in audit_items]
    total_cost = sum(float(item["estimated_cost_usd"]) for item in audit_items)
    total_minutes = sum(float(item["duration_seconds"]) for item in audit_items) / 60
    total_latency = sum(latencies)
    cost_per_minute = total_cost / total_minutes if total_minutes else 0.0
    item_costs_per_minute = [
        float(item.get("cost_per_audio_minute_usd", 0.0)) for item in audit_items
    ]
    max_item_cost_per_minute = max(item_costs_per_minute, default=0.0)
    cost_ceiling = 0.003
    all_items_within_ceiling = all(value <= cost_ceiling for value in item_costs_per_minute)
    real_time_factor = total_latency / (total_minutes * 60) if total_minutes else 0.0
    confidence_score = max(0.0, 1.0 - confidence_mae)
    tone_score = (accuracy["emotional_tone"] + observed_macro_f1) / 2
    assessment_quality_score = (
        0.50 * tone_score
        + 0.10 * accuracy["emotional_intensity"]
        + 0.07 * accuracy["background_noise_present"]
        + 0.06 * accuracy["background_noise_severity"]
        + 0.05 * noise_type_accuracy
        + 0.08 * accuracy["audio_quality"]
        + 0.07 * accuracy["speaker_overlap_present"]
        + 0.04 * accuracy["long_silence_present"]
        + 0.03 * confidence_score
    )

    report = {
        "sample_count": len(names),
        "model": audit_items[0].get("model") if audit_items else audit_payload.get("model"),
        "prompt_version": audit_payload.get("prompt_version"),
        "field_accuracy": {**accuracy, "background_noise_type_normalized": noise_type_accuracy},
        "exact_match_rate": exact_match,
        "emotional_tone_macro_f1": macro_f1,
        "emotional_tone_macro_f1_observed_classes": observed_macro_f1,
        "emotional_tone_per_class": tone_metrics,
        "confidence_mae": confidence_mae,
        "assessment_quality_score": assessment_quality_score,
        "tone_confusion": [
            {"expected": expected_tone, "predicted": predicted_tone, "count": count}
            for (expected_tone, predicted_tone), count in sorted(confusion.items())
        ],
        "latency_seconds": {
            "total": total_latency,
            "mean": statistics.fmean(latencies) if latencies else 0.0,
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "real_time_factor": real_time_factor,
        },
        "cost": {
            "total_usd": total_cost,
            "audio_minutes": total_minutes,
            "usd_per_audio_minute": cost_per_minute,
            "max_item_usd_per_audio_minute": max_item_cost_per_minute,
            "ceiling_usd_per_audio_minute": cost_ceiling,
            "all_items_within_ceiling": all_items_within_ceiling,
            "within_ceiling": cost_per_minute <= cost_ceiling and all_items_within_ceiling,
        },
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.experiment_id:
        experiments = []
        if args.experiment_log.exists():
            experiments = json.loads(args.experiment_log.read_text(encoding="utf-8"))
        record = {
            "id": args.experiment_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "description": args.experiment_description,
            "model": report["model"],
            "prompt_version": report["prompt_version"],
            "assessment_quality_score": assessment_quality_score,
            "tone_accuracy": accuracy["emotional_tone"],
            "tone_macro_f1_observed": observed_macro_f1,
            "field_accuracy": report["field_accuracy"],
            "cost_per_audio_minute_usd": cost_per_minute,
            "real_time_factor": real_time_factor,
            "within_cost_ceiling": report["cost"]["within_ceiling"],
        }
        experiments = [item for item in experiments if item.get("id") != args.experiment_id]
        experiments.append(record)
        args.experiment_log.parent.mkdir(parents=True, exist_ok=True)
        args.experiment_log.write_text(json.dumps(experiments, indent=2), encoding="utf-8")

    field_rows = "\n".join(
        f"| `{field}` | {value:.1%} |" for field, value in report["field_accuracy"].items()
    )
    confusion_rows = "\n".join(
        f"| {row['expected']} | {row['predicted']} | {row['count']} |"
        for row in report["tone_confusion"]
    )
    args.markdown_output.write_text(
        f"""# Evaluation report

This report was generated by `scripts/evaluate_predictions.py` from the supplied labelled set. The
sample is intentionally reported as **n={len(names)}**; it is a smoke benchmark, not a statistically
reliable production estimate.

- Model: `{report['model']}`
- Prompt: `{report['prompt_version']}`
- Exact categorical match: **{exact_match:.1%}**
- Assessment-weighted quality score: **{assessment_quality_score:.3f}**
- Emotional-tone macro F1 (classes observed in n=3): **{observed_macro_f1:.3f}**
- Emotional-tone macro F1 (all five allowed classes): **{macro_f1:.3f}**
- Confidence mean absolute error: **{confidence_mae:.3f}**
- Total measured latency: **{total_latency:.2f}s** ({real_time_factor:.2f}× real time)
- Estimated cost: **${cost_per_minute:.6f}/audio minute** against the **$0.003** ceiling
- Maximum per-clip cost: **${max_item_cost_per_minute:.6f}/audio minute**

## Field accuracy

| Field | Accuracy |
|---|---:|
{field_rows}

## Emotional-tone confusion

| Expected | Predicted | Count |
|---|---|---:|
{confusion_rows}

## Interpretation

Treat discrepancies as a prompt/calibration signal, not as a model leaderboard. The hidden evaluation
set is the meaningful test; no prompt change should be accepted solely because it improves these three
visible examples.
""",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0 if report["cost"]["within_ceiling"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
