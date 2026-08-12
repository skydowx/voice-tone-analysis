from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.main import create_app
from app.schemas.prediction import Prediction
from app.services.inference.base import InferenceOutcome, Usage


@pytest.fixture
def anyio_backend():
    return "asyncio"


class StubProvider:
    def analyze(self, audio_path, features, model=None):
        return InferenceOutcome(
            prediction=Prediction(
                emotional_tone="neutral",
                emotional_intensity="low",
                background_noise_present=False,
                background_noise_type="",
                background_noise_severity="none",
                audio_quality="clear",
                speaker_overlap_present=False,
                long_silence_present=False,
                confidence=0.91,
            ),
            model=model or "gemini-3.5-flash-lite",
            latency_seconds=0.01,
            usage=Usage(input_tokens=100, output_tokens=40, thinking_tokens=0, total_tokens=140),
        )


def write_wav(path: Path, seconds: float = 1.0, *, silence_after: float | None = None) -> Path:
    rate = 16_000
    frames = []
    for index in range(int(rate * seconds)):
        second = index / rate
        silent = silence_after is not None and second >= silence_after
        sample = 0 if silent else int(8_000 * math.sin(2 * math.pi * 220 * second))
        frames.append(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(b"".join(frames))
    return path


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        app_data_dir=tmp_path / "data",
        database_path=tmp_path / "data" / "test.sqlite3",
        evaluator_username="reviewer",
        evaluator_password=SecretStr("test-password"),
        session_secret=SecretStr("test-session-secret-with-enough-entropy"),
        trusted_hosts=["testserver"],
        cookie_secure=False,
        long_silence_seconds=2.0,
    )


@pytest.fixture
async def client(settings: Settings):
    app = create_app(settings=settings, provider=StubProvider())
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=True,
        ) as test_client:
            yield test_client
