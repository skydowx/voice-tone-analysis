from __future__ import annotations

import csv
import io
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.status import HTTP_303_SEE_OTHER

from app.dependencies import processor_from, repository_from, settings_from
from app.security import ensure_csrf_token, require_login, verify_csrf
from app.services.batch_validation import (
    BatchValidationError,
    IntakeIssue,
    extract_zip_safely,
    sanitize_filename,
    validate_batch_root,
)
from app.services.evaluation import compare_predictions, summarize_pairs


router = APIRouter()


def _batch_context(request: Request, batch_id: str) -> dict:
    repository = repository_from(request)
    batch = repository.get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    items = repository.list_items(batch_id)
    labelled_pairs = []
    for item in items:
        if item["expected"] and item["prediction"]:
            item["comparison"] = compare_predictions(item["expected"], item["prediction"])
            labelled_pairs.append((item["expected"], item["prediction"]))
        else:
            item["comparison"] = None
    duration_minutes = max(float(batch["total_audio_seconds"]) / 60.0, 0.0)
    batch["cost_per_minute"] = (
        float(batch["total_cost_usd"]) / duration_minutes if duration_minutes else 0.0
    )
    return {
        "batch": batch,
        "items": items,
        "evaluation": summarize_pairs(labelled_pairs),
        "csrf_token": ensure_csrf_token(request),
    }


@router.get("/")
async def dashboard(request: Request):
    require_login(request)
    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "batches": repository_from(request).list_batches(),
            "csrf_token": ensure_csrf_token(request),
            "settings": settings_from(request),
        },
    )


@router.post("/batches")
async def create_batch(
    request: Request,
    files: Annotated[list[UploadFile | str], File()],
    csrf_token: Annotated[str, Form()],
):
    require_login(request)
    verify_csrf(request, csrf_token)
    settings = settings_from(request)
    # Browsers submit an empty multipart part for the unused ZIP/folder picker.
    # Ignore those placeholders while still rejecting a genuinely empty form.
    selected_files = [
        upload
        for upload in files
        if isinstance(upload, StarletteUploadFile) and (upload.filename or "").strip()
    ]
    if not selected_files:
        raise HTTPException(400, "Choose a ZIP archive or batch folder")

    staging = settings.uploads_dir / f"staging-{uuid.uuid4().hex}"
    direct_root = staging / "direct"
    direct_root.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    total_bytes = 0
    seen: set[str] = set()
    try:
        for upload in selected_files:
            name = sanitize_filename(upload.filename or "")
            if name in seen:
                raise BatchValidationError(f"Duplicate uploaded filename: {name}")
            seen.add(name)
            destination = direct_root / name
            file_bytes = 0
            file_limit = settings.max_batch_bytes if destination.suffix.lower() == ".zip" else settings.max_file_bytes
            with destination.open("wb") as output:
                while chunk := await upload.read(1024 * 1024):
                    file_bytes += len(chunk)
                    total_bytes += len(chunk)
                    if file_bytes > file_limit or total_bytes > settings.max_batch_bytes:
                        raise BatchValidationError("Upload exceeds the configured size limit")
                    output.write(chunk)
            saved.append(destination)

        if len(saved) == 1 and saved[0].suffix.lower() == ".zip":
            root = extract_zip_safely(saved[0], staging / "extracted", settings)
        else:
            root = direct_root
        intake = validate_batch_root(root, settings)
        issues = [*intake.errors, *intake.warnings]
        batch_name = f"Evaluation {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        batch_id = repository_from(request).create_batch(batch_name, intake.items, issues)
        if intake.can_process:
            processor_from(request).submit(batch_id)
        else:
            # Nothing references staging when validation produces no processable items.
            shutil.rmtree(staging, ignore_errors=True)
        return RedirectResponse(f"/batches/{batch_id}", status_code=HTTP_303_SEE_OTHER)
    except BatchValidationError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return request.app.state.templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "batches": repository_from(request).list_batches(),
                "csrf_token": ensure_csrf_token(request),
                "settings": settings,
                "upload_error": str(exc),
            },
            status_code=400,
        )
    finally:
        for upload in files:
            if isinstance(upload, StarletteUploadFile):
                await upload.close()


@router.get("/batches/{batch_id}")
async def batch_detail(request: Request, batch_id: str):
    require_login(request)
    return request.app.state.templates.TemplateResponse(
        request,
        "batch.html",
        _batch_context(request, batch_id),
    )


@router.get("/api/batches/{batch_id}")
async def batch_status(request: Request, batch_id: str):
    require_login(request)
    context = _batch_context(request, batch_id)
    batch = context["batch"]
    items = context["items"]
    for item in items:
        item.pop("path", None)
    return JSONResponse({"batch": batch, "items": items, "evaluation": context["evaluation"]})


@router.get("/batches/{batch_id}/results.csv")
async def download_csv(request: Request, batch_id: str):
    require_login(request)
    repository = repository_from(request)
    if not repository.get_batch(batch_id):
        raise HTTPException(404, "Batch not found")
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=["name", "result_json"])
    writer.writeheader()
    for item in repository.list_items(batch_id):
        writer.writerow(
            {
                "name": item["name"],
                "result_json": json.dumps(item["prediction"], separators=(",", ":"))
                if item["prediction"]
                else "",
            }
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{batch_id}-results.csv"'},
    )


@router.get("/batches/{batch_id}/results.json")
async def download_json(request: Request, batch_id: str):
    require_login(request)
    batch = repository_from(request).get_batch(batch_id)
    if not batch:
        raise HTTPException(404, "Batch not found")
    rows = []
    for item in repository_from(request).list_items(batch_id):
        row = {"name": item["name"], "result": item["prediction"]}
        if item["error"]:
            row["error"] = item["error"]
        rows.append(row)
    return Response(
        json.dumps(rows, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{batch_id}-results.json"'},
    )
