from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.prediction import Prediction
from app.security import verify_login
from app.config import Settings
from pydantic import SecretStr
import base64
import hashlib


def valid_prediction(**overrides):
    values = {
        "emotional_tone": "neutral",
        "emotional_intensity": "low",
        "background_noise_present": False,
        "background_noise_type": "",
        "background_noise_severity": "none",
        "audio_quality": "clear",
        "speaker_overlap_present": False,
        "long_silence_present": False,
        "confidence": 0.8,
    }
    values.update(overrides)
    return Prediction(**values)


def test_prediction_enforces_noise_consistency():
    with pytest.raises(ValidationError):
        valid_prediction(background_noise_present=False, background_noise_severity="medium")


def test_prediction_rejects_extra_fields_and_invalid_confidence():
    with pytest.raises(ValidationError):
        valid_prediction(transcript="must not be returned")
    with pytest.raises(ValidationError):
        valid_prediction(confidence=1.1)


def test_prediction_accepts_expected_contract():
    result = valid_prediction(
        background_noise_present=True,
        background_noise_type="television",
        background_noise_severity="low",
    )
    assert result.model_dump()["background_noise_type"] == "television"


def test_hashed_evaluator_password_is_supported(tmp_path):
    salt = b"0123456789abcdef"
    rounds = 1_000
    digest = hashlib.pbkdf2_hmac("sha256", b"secret", salt, rounds)
    encoded = "pbkdf2_sha256${}${}${}".format(
        rounds,
        base64.urlsafe_b64encode(salt).decode(),
        base64.urlsafe_b64encode(digest).decode(),
    )
    settings = Settings(
        app_data_dir=tmp_path,
        evaluator_username="reviewer",
        evaluator_password_hash=SecretStr(encoded),
    )
    assert verify_login(settings, "reviewer", "secret") is True
    assert verify_login(settings, "reviewer", "wrong") is False
