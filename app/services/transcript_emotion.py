from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.prediction import Prediction


TONES = ("neutral", "satisfied", "frustrated", "upset", "distressed")
INTENSITIES = ("low", "medium", "high")
# Intensity changes the evidence weight only slightly: primary tone should not
# collapse into "strongest isolated moment."
INTENSITY_WEIGHT = {"low": 0.9, "medium": 1.0, "high": 1.1}
EXPLICIT_EXPRESSIONS = {
    "satisfied": (
        "thank you",
        "thanks",
        "appreciate",
        "relieved",
        "pleased",
        "glad",
        "that works",
        "resolved",
    ),
    "frustrated": ("frustrated", "annoyed", "impatient", "dissatisfied"),
    "upset": ("angry", "furious", "strongly dissatisfied"),
    "distressed": ("panicking", "panicked", "overwhelmed", "crying", "desperate"),
}


@dataclass(frozen=True)
class CustomerTurn:
    text: str
    tone: str | None = None
    intensity: str | None = None

    @property
    def word_count(self) -> int:
        return max(1, len(re.findall(r"\b[\w']+\b", self.text)))


def _customer_turns(transcript: str) -> list[CustomerTurn]:
    turns: list[CustomerTurn] = []
    for line in transcript.splitlines():
        match = re.match(
            r"\s*(CUSTOMER|CALLER|USER)(?:\s*\|\s*([a-z_]+)\s*\|\s*([a-z_]+))?\s*:\s*(.*)",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        tone = (match.group(2) or "").lower() or None
        intensity = (match.group(3) or "").lower() or None
        turns.append(
            CustomerTurn(
                text=match.group(4),
                tone=tone if tone in TONES else None,
                intensity=intensity if intensity in INTENSITIES else None,
            )
        )
    return turns


def reconcile_transcript_emotion(transcript: str, audio_prediction: Prediction) -> Prediction:
    prediction, _ = analyze_transcript_emotion(transcript, audio_prediction)
    return prediction


def _explicit_count(text: str, expression: str) -> int:
    matches = re.finditer(rf"(?<!\w){re.escape(expression)}(?!\w)", text.lower())
    count = 0
    for match in matches:
        prefix = text.lower()[max(0, match.start() - 16) : match.start()]
        if re.search(r"(?:not|never|hardly|don't|do not)\s+$", prefix):
            continue
        count += 1
    return count


def analyze_transcript_emotion(
    transcript: str, audio_prediction: Prediction
) -> tuple[Prediction, dict[str, float | bool | str]]:
    """Aggregate CUSTOMER evidence without sample-specific or weak issue-word rules.

    Word count is a reproducible proxy for turn duration because the ephemeral
    transcript does not contain timestamps. Untagged text can override the audio
    profile only when it contains an expression taken directly from a class definition.
    """
    turns = _customer_turns(transcript)
    tagged = [turn for turn in turns if turn.tone is not None and turn.intensity is not None]
    diagnostics: dict[str, float | bool | str] = {
        "transcript_customer_turn_count": float(len(turns)),
        "transcript_tagged_turn_count": float(len(tagged)),
    }
    if not tagged:
        # Meaning can disambiguate an otherwise neutral audio profile, but only
        # definition-level self-expression is strong enough to override it.
        # Generic issue descriptions are intentionally absent from this list.
        expression_counts = {
            tone: sum(_explicit_count(turn.text, expression) for turn in turns for expression in expressions)
            for tone, expressions in EXPLICIT_EXPRESSIONS.items()
        }
        diagnostics.update(
            {
                f"transcript_explicit_{tone}": float(count)
                for tone, count in expression_counts.items()
            }
        )
        strongest = max(
            EXPLICIT_EXPRESSIONS,
            key=lambda tone: (expression_counts[tone], TONES.index(tone)),
        )
        if expression_counts[strongest] == 0:
            return audio_prediction, diagnostics
        data = audio_prediction.model_dump()
        data["emotional_tone"] = strongest
        if strongest != "neutral" and data["emotional_intensity"] == "low":
            data["emotional_intensity"] = "medium"
        if strongest != audio_prediction.emotional_tone:
            data["confidence"] = min(float(audio_prediction.confidence), 0.78)
        return Prediction.model_validate(data), diagnostics

    tone_scores = {tone: 0.0 for tone in TONES}
    intensity_scores = {tone: {intensity: 0.0 for intensity in INTENSITIES} for tone in TONES}
    for turn in tagged:
        assert turn.tone is not None and turn.intensity is not None
        duration_evidence = float(turn.word_count)
        tone_scores[turn.tone] += duration_evidence * INTENSITY_WEIGHT[turn.intensity]
        intensity_scores[turn.tone][turn.intensity] += duration_evidence

    primary_tone = max(TONES, key=lambda tone: tone_scores[tone])
    primary_intensity = max(
        INTENSITIES,
        key=lambda intensity: intensity_scores[primary_tone][intensity],
    )
    data = audio_prediction.model_dump()
    data["emotional_tone"] = primary_tone
    data["emotional_intensity"] = primary_intensity
    if (
        primary_tone != audio_prediction.emotional_tone
        or primary_intensity != audio_prediction.emotional_intensity
    ):
        data["confidence"] = min(float(audio_prediction.confidence), 0.78)

    diagnostics.update(
        {
            **{f"transcript_tag_{tone}": round(score, 3) for tone, score in tone_scores.items()},
            "transcript_primary_tone": primary_tone,
            "transcript_primary_intensity": primary_intensity,
        }
    )
    return Prediction.model_validate(data), diagnostics
