from __future__ import annotations

import re
from dataclasses import dataclass

from app.schemas.prediction import Prediction


SATISFIED = {
    "thank": 1.0,
    "thanks": 1.0,
    "appreciate": 1.2,
    "perfect": 1.4,
    "great": 1.0,
    "excellent": 1.4,
    "wonderful": 1.4,
    "glad": 1.0,
    "happy": 1.0,
    "relieved": 1.3,
    "that works": 1.2,
    "resolved": 1.0,
}
FRUSTRATED = {
    "frustrat": 1.6,
    "annoy": 1.3,
    "disappoint": 1.3,
    "not working": 1.2,
    "doesn't work": 1.2,
    "still": 0.5,
    "already": 0.4,
    "waiting": 0.7,
    "problem": 0.5,
    "issue": 0.4,
    "why": 0.4,
    "again": 0.5,
}
UPSET = {
    "angry": 1.8,
    "furious": 2.0,
    "unacceptable": 1.6,
    "ridiculous": 1.5,
    "terrible": 1.4,
    "horrible": 1.5,
    "worst": 1.5,
    "supervisor": 0.8,
    "manager": 0.7,
    "complaint": 1.0,
    "cancel": 0.8,
    "what the hell": 1.8,
}
DISTRESSED = {
    "scared": 1.6,
    "afraid": 1.6,
    "panic": 1.8,
    "emergency": 1.4,
    "desperate": 1.6,
    "please help": 1.2,
    "crying": 1.8,
    "can't breathe": 2.0,
}

TONES = {"neutral", "satisfied", "frustrated", "upset", "distressed"}
INTENSITY_WEIGHT = {"low": 0.6, "medium": 1.0, "high": 1.4}


@dataclass(frozen=True)
class CustomerTurn:
    text: str
    tone: str | None = None
    intensity: str | None = None


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
                intensity=intensity if intensity in INTENSITY_WEIGHT else None,
            )
        )
    return turns


def _score(text: str, lexicon: dict[str, float]) -> float:
    lowered = text.lower()
    return sum(weight * lowered.count(term) for term, weight in lexicon.items())


def reconcile_transcript_emotion(transcript: str, audio_prediction: Prediction) -> Prediction:
    """Use ephemeral customer wording to correct audio-only role/tone ambiguity."""
    prediction, _ = analyze_transcript_emotion(transcript, audio_prediction)
    return prediction


def analyze_transcript_emotion(
    transcript: str, audio_prediction: Prediction
) -> tuple[Prediction, dict[str, float | bool | str]]:
    """Reconcile emotion and return aggregate, transcript-free diagnostic evidence."""
    turns = _customer_turns(transcript)
    customer = "\n".join(turn.text for turn in turns)
    if not customer.strip():
        return audio_prediction, {
            "transcript_customer_turn_count": 0.0,
            "transcript_tagged_turn_count": 0.0,
        }

    satisfied = _score(customer, SATISFIED)
    frustrated = _score(customer, FRUSTRATED)
    upset = _score(customer, UPSET)
    distressed = _score(customer, DISTRESSED)
    negative = frustrated + upset + distressed

    tag_scores = {tone: 0.0 for tone in TONES}
    tag_max_intensity = {tone: "low" for tone in TONES}
    intensity_rank = {"low": 0, "medium": 1, "high": 2}
    for turn in turns:
        if turn.tone is None or turn.intensity is None:
            continue
        tag_scores[turn.tone] += INTENSITY_WEIGHT[turn.intensity]
        if intensity_rank[turn.intensity] > intensity_rank[tag_max_intensity[turn.tone]]:
            tag_max_intensity[turn.tone] = turn.intensity
    tagged_tone = max(tag_scores, key=tag_scores.get) if max(tag_scores.values()) > 0 else None

    tone = audio_prediction.emotional_tone
    if distressed >= 1.6:
        tone = "distressed"
    elif upset >= 1.5 or (upset >= 0.7 and frustrated >= 0.8):
        tone = "upset"
    elif satisfied >= 1.0 and satisfied > negative:
        tone = "satisfied"
    elif tagged_tone is not None:
        # Turn annotations use prosody as well as wording, and a neutral tag prevents
        # ordinary descriptions of a problem from being mistaken for frustration.
        tone = tagged_tone
    elif frustrated >= 1.1:
        tone = "frustrated"

    intensity = audio_prediction.emotional_intensity
    exclamations = customer.count("!")
    tagged_intensity = tag_max_intensity[tone] if tagged_tone == tone else None
    if tagged_intensity is not None:
        intensity = tagged_intensity
    if tone in {"upset", "distressed"} and (max(upset, distressed) >= 1.8 or exclamations >= 2):
        intensity = "high"
    elif tone != "neutral" and intensity == "low":
        intensity = "medium"

    data = audio_prediction.model_dump()
    data["emotional_tone"] = tone
    data["emotional_intensity"] = intensity
    if tone != audio_prediction.emotional_tone:
        data["confidence"] = min(float(audio_prediction.confidence), 0.78)
    diagnostics: dict[str, float | bool | str] = {
        "transcript_customer_turn_count": float(len(turns)),
        "transcript_tagged_turn_count": float(
            sum(turn.tone is not None and turn.intensity is not None for turn in turns)
        ),
        "transcript_lexical_satisfied": round(satisfied, 3),
        "transcript_lexical_frustrated": round(frustrated, 3),
        "transcript_lexical_upset": round(upset, 3),
        "transcript_lexical_distressed": round(distressed, 3),
        **{f"transcript_tag_{name}": round(value, 3) for name, value in tag_scores.items()},
    }
    return Prediction.model_validate(data), diagnostics
