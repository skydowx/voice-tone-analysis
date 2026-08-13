from __future__ import annotations

import statistics
from collections import Counter
from typing import Any, Iterable


TONE_CLASSES = ("neutral", "satisfied", "frustrated", "upset", "distressed")
CATEGORICAL_FIELDS = (
    "emotional_tone",
    "emotional_intensity",
    "background_noise_present",
    "background_noise_type",
    "background_noise_severity",
    "audio_quality",
    "speaker_overlap_present",
    "long_silence_present",
)


def normalized_noise(value: str) -> str:
    normalized = " ".join(str(value).lower().strip().split())
    aliases = {
        "tv": "television",
        "sharp static noise": "sharp static",
        "static": "sharp static",
    }
    return aliases.get(normalized, normalized)


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


def field_matches(field: str, expected: Any, predicted: Any) -> bool:
    if field == "background_noise_type":
        return noise_type_matches(str(expected), str(predicted))
    return expected == predicted


def compare_predictions(expected: dict[str, Any], predicted: dict[str, Any]) -> dict[str, Any]:
    fields = {
        field: {
            "expected": expected[field],
            "predicted": predicted[field],
            "match": field_matches(field, expected[field], predicted[field]),
        }
        for field in CATEGORICAL_FIELDS
    }
    confidence_error = abs(float(expected["confidence"]) - float(predicted["confidence"]))
    return {
        "fields": fields,
        "matched_fields": sum(entry["match"] for entry in fields.values()),
        "field_count": len(fields),
        "exact_match": all(entry["match"] for entry in fields.values()),
        "confidence_error": confidence_error,
    }


def class_metrics(expected_values: list[str], predicted_values: list[str]) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for label in TONE_CLASSES:
        true_positive = sum(e == label and p == label for e, p in zip(expected_values, predicted_values))
        false_positive = sum(e != label and p == label for e, p in zip(expected_values, predicted_values))
        false_negative = sum(e == label and p != label for e, p in zip(expected_values, predicted_values))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[label] = {"precision": precision, "recall": recall, "f1": f1}
    return metrics


def summarize_pairs(pairs: Iterable[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any] | None:
    materialized = list(pairs)
    if not materialized:
        return None

    comparisons = [compare_predictions(expected, predicted) for expected, predicted in materialized]
    expected_tones = [expected["emotional_tone"] for expected, _ in materialized]
    predicted_tones = [predicted["emotional_tone"] for _, predicted in materialized]
    tone_metrics = class_metrics(expected_tones, predicted_tones)
    observed_classes = sorted(set(expected_tones))
    confusion = Counter(zip(expected_tones, predicted_tones))
    field_accuracy = {
        field: statistics.fmean(comparison["fields"][field]["match"] for comparison in comparisons)
        for field in CATEGORICAL_FIELDS
    }
    return {
        "sample_count": len(materialized),
        "field_accuracy": field_accuracy,
        "exact_match_rate": statistics.fmean(comparison["exact_match"] for comparison in comparisons),
        "confidence_mae": statistics.fmean(comparison["confidence_error"] for comparison in comparisons),
        "emotional_tone_accuracy": field_accuracy["emotional_tone"],
        "emotional_tone_macro_f1": statistics.fmean(metric["f1"] for metric in tone_metrics.values()),
        "emotional_tone_macro_f1_observed_classes": statistics.fmean(
            tone_metrics[label]["f1"] for label in observed_classes
        ),
        "emotional_tone_per_class": tone_metrics,
        "tone_confusion": [
            {"expected": expected, "predicted": predicted, "count": count}
            for (expected, predicted), count in sorted(confusion.items())
        ],
    }

