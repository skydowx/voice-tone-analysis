from __future__ import annotations

import io
import re
import time
import zipfile

import anyio
import pytest

from .conftest import write_wav


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


def make_batch_zip(tmp_path) -> bytes:
    audio = write_wav(tmp_path / "call.wav")
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.write(audio, "evaluation/call.wav")
        archive.writestr("evaluation/labels.csv", "name,result_json\ncall.wav,\n")
    return archive_buffer.getvalue()


async def test_health_and_authentication(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
    response = await client.get("/")
    assert response.status_code == 200
    assert response.url.path == "/login"


async def test_authenticated_batch_flow_and_download(client, tmp_path):
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
