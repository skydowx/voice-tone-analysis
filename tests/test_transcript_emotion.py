from app.schemas.prediction import Prediction
from app.services.transcript_emotion import reconcile_transcript_emotion


def base_prediction():
    return Prediction(
        emotional_tone="neutral",
        emotional_intensity="low",
        background_noise_present=False,
        background_noise_type="",
        background_noise_severity="none",
        audio_quality="clear",
        speaker_overlap_present=False,
        long_silence_present=False,
        confidence=0.85,
    )


def test_only_customer_turns_affect_local_emotion():
    transcript = "BACKGROUND: This is terrible and unacceptable!\nCUSTOMER: Thank you, that works perfectly."
    result = reconcile_transcript_emotion(transcript, base_prediction())
    assert result.emotional_tone == "satisfied"
    assert result.emotional_intensity == "medium"


def test_strong_customer_complaint_maps_to_upset_high():
    transcript = "CUSTOMER: This is unacceptable and terrible! I want a supervisor!"
    result = reconcile_transcript_emotion(transcript, base_prediction())
    assert result.emotional_tone == "upset"
    assert result.emotional_intensity == "high"


def test_no_identified_customer_preserves_audio_prediction():
    original = base_prediction()
    assert reconcile_transcript_emotion("SPEAKER 1: hello", original) == original


def test_tagged_customer_prosody_recovers_upset_without_trigger_words():
    transcript = "AGENT|neutral|low: How can I help?\nCUSTOMER|upset|high: I have called three times."
    result = reconcile_transcript_emotion(transcript, base_prediction())
    assert result.emotional_tone == "upset"
    assert result.emotional_intensity == "high"


def test_tagged_neutral_customer_prevents_weak_problem_word_false_positive():
    transcript = "CUSTOMER|neutral|medium: I have an issue with the device again."
    audio = base_prediction().model_copy(update={"emotional_tone": "frustrated", "emotional_intensity": "medium"})
    result = reconcile_transcript_emotion(transcript, audio)
    assert result.emotional_tone == "neutral"
    assert result.emotional_intensity == "medium"
