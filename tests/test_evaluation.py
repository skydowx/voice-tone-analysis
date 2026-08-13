from app.services.evaluation import compare_predictions, noise_type_matches, summarize_pairs
from scripts.evaluate_oss_emotion import normalize_label


def prediction(**updates):
    value = {
        "emotional_tone": "neutral",
        "emotional_intensity": "medium",
        "background_noise_present": True,
        "background_noise_type": "television",
        "background_noise_severity": "medium",
        "audio_quality": "clear",
        "speaker_overlap_present": True,
        "long_silence_present": False,
        "confidence": 0.82,
    }
    value.update(updates)
    return value


def test_noise_type_matching_is_normalized_but_bounded():
    assert noise_type_matches("TV", "radio")
    assert noise_type_matches("sharp static", "static")
    assert not noise_type_matches("road noise", "television")


def test_comparison_reports_each_field_and_confidence_error():
    expected = prediction()
    predicted = prediction(emotional_tone="frustrated", confidence=0.70)
    comparison = compare_predictions(expected, predicted)

    assert comparison["matched_fields"] == 7
    assert comparison["field_count"] == 8
    assert comparison["exact_match"] is False
    assert comparison["fields"]["emotional_tone"]["match"] is False
    assert comparison["confidence_error"] == 0.12


def test_summary_reports_tone_metrics_and_confusion():
    expected = prediction()
    summary = summarize_pairs([(expected, prediction()), (expected, prediction(emotional_tone="upset"))])

    assert summary is not None
    assert summary["sample_count"] == 2
    assert summary["emotional_tone_accuracy"] == 0.5
    assert summary["emotional_tone_macro_f1_observed_classes"] == 2 / 3
    assert summary["tone_confusion"] == [
        {"expected": "neutral", "predicted": "neutral", "count": 1},
        {"expected": "neutral", "predicted": "upset", "count": 1},
    ]


def test_empty_summary_is_hidden_for_unlabelled_batches():
    assert summarize_pairs([]) is None


def test_oss_native_unknown_label_is_normalized_before_mapping():
    assert normalize_label("<unk>") == "unknown"
    assert normalize_label("/m/happy") == "happy"
