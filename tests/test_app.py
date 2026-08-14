from __future__ import annotations

import io
import json
import re
import time
import zipfile
from pathlib import Path

import anyio
import httpx
import pytest
from pydantic import SecretStr

from app.main import create_app

from .conftest import RecordingAnalytics, StubProvider, write_wav


pytestmark = pytest.mark.anyio


def csrf_from(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


async def login(client):
    response = await client.get("/login")
    response = await client.post(
        "/login",
        data={"username": "reviewer", "password": "test-password", "csrf_token": csrf_from(response)},
        follow_redirects=False,
    )
    assert response.status_code == 303


def make_batch_zip(tmp_path, *, expected: dict | None = None) -> bytes:
    audio = write_wav(tmp_path / "call.wav")
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.write(audio, "evaluation/call.wav")
        result_json = json.dumps(expected, separators=(",", ":")) if expected else ""
        manifest = io.StringIO(newline="")
        import csv

        writer = csv.DictWriter(manifest, fieldnames=["name", "result_json"])
        writer.writeheader()
        writer.writerow({"name": "call.wav", "result_json": result_json})
        archive.writestr("evaluation/labels.csv", manifest.getvalue())
    return archive_buffer.getvalue()


async def test_health_and_authentication(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    response = await client.get("/")
    assert response.status_code == 200
    assert response.url.path == "/login"
    assert "posthog-replay.js" not in response.text


async def test_session_replay_is_opt_in_and_maximally_masked(settings):
    settings.posthog_project_token = SecretStr("phc_test_public_project_token")
    settings.posthog_session_replay = True
    app = create_app(settings=settings, provider=StubProvider(), analytics=RecordingAnalytics())
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as replay_client:
            login_page = await replay_client.get("/login")
    replay_script = (Path(__file__).parents[1] / "app/static/posthog-replay.js").read_text()

    assert login_page.status_code == 200
    assert 'src="http://testserver/static/posthog-replay.js"' in login_page.text
    assert 'data-posthog-token="phc_test_public_project_token"' in login_page.text
    assert 'class="card auth-card ph-no-capture"' in login_page.text
    assert "Privacy-masked session replay is enabled." in login_page.text
    assert "autocapture: false" in replay_script
    assert "capture_pageview: false" in replay_script
    assert "enable_recording_console_log: false" in replay_script
    assert "maskAllInputs: true" in replay_script
    assert 'maskTextSelector: "*"' in replay_script
    assert 'request.name.split("?")[0]' in replay_script


async def test_authenticated_batch_flow_and_download(client, tmp_path, analytics):
    await login(client)
    dashboard = await client.get("/")
    response = await client.post(
        "/batches",
        data={"csrf_token": csrf_from(dashboard)},
        files={"files": ("evaluation.zip", make_batch_zip(tmp_path), "application/zip")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    batch_path = response.headers["location"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        payload = (await client.get(f"/api{batch_path}")).json()
        if payload["batch"]["status"] in {"complete", "completed_with_errors"}:
            break
        await anyio.sleep(0.05)
    assert payload["batch"]["status"] == "complete"
    assert payload["items"][0]["prediction"]["emotional_tone"] == "neutral"

    csv_response = await client.get(f"{batch_path}/results.csv")
    assert csv_response.status_code == 200
    assert csv_response.text.startswith("name,result_json")
    assert "call.wav" in csv_response.text
    events = [event for event, _ in analytics.events]
    assert "application started" in events
    assert "batch uploaded" in events
    assert "batch completed" in events
    assert "results downloaded" in events
    uploaded = next(properties for event, properties in analytics.events if event == "batch uploaded")
    assert uploaded["total_items"] == 1
    assert "name" not in uploaded


async def test_upload_ignores_empty_unused_file_picker(client, tmp_path):
    await login(client)
    dashboard = await client.get("/")
    response = await client.post(
        "/batches",
        data={"csrf_token": csrf_from(dashboard)},
        files=[
            ("files", ("evaluation.zip", make_batch_zip(tmp_path), "application/zip")),
            ("files", ("", b"", "application/octet-stream")),
        ],
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/batches/")


async def test_labelled_batch_displays_expected_matches_and_metrics(client, tmp_path):
    await login(client)
    dashboard = await client.get("/")
    expected = {
        "emotional_tone": "upset",
        "emotional_intensity": "low",
        "background_noise_present": False,
        "background_noise_type": "",
        "background_noise_severity": "none",
        "audio_quality": "clear",
        "speaker_overlap_present": False,
        "long_silence_present": False,
        "confidence": 0.82,
    }
    response = await client.post(
        "/batches",
        data={"csrf_token": csrf_from(dashboard)},
        files={"files": ("evaluation.zip", make_batch_zip(tmp_path, expected=expected), "application/zip")},
        follow_redirects=False,
    )
    batch_path = response.headers["location"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        payload = (await client.get(f"/api{batch_path}")).json()
        if payload["batch"]["status"] == "complete":
            break
        await anyio.sleep(0.05)

    assert payload["evaluation"]["sample_count"] == 1
    assert payload["items"][0]["comparison"]["fields"]["emotional_tone"]["match"] is False
    page = await client.get(batch_path)
    assert "Visible-set evaluation" in page.text
    assert "Expected upset" in page.text
    assert "Expected vs predicted" in page.text


async def test_unlabelled_batch_hides_label_comparison(client, tmp_path):
    await login(client)
    dashboard = await client.get("/")
    response = await client.post(
        "/batches",
        data={"csrf_token": csrf_from(dashboard)},
        files={"files": ("evaluation.zip", make_batch_zip(tmp_path), "application/zip")},
        follow_redirects=False,
    )
    batch_path = response.headers["location"]
    page = await client.get(batch_path)
    assert "Visible-set evaluation" not in page.text
