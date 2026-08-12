from __future__ import annotations

import csv
import io
import json
import shutil
import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from app.config import Settings
from app.schemas.prediction import Prediction
from app.services.audio import AudioProcessingError, probe_audio


SUPPORTED_AUDIO_EXTENSIONS = {
    ".aac",
    ".flac",
    ".m4a",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}


@dataclass(frozen=True)
class IntakeIssue:
    name: str
    code: str
    message: str


@dataclass(frozen=True)
class ValidatedItem:
    name: str
    path: Path
    expected_json: str | None
    duration_seconds: float


@dataclass
class IntakeResult:
    items: list[ValidatedItem] = field(default_factory=list)
    errors: list[IntakeIssue] = field(default_factory=list)
    warnings: list[IntakeIssue] = field(default_factory=list)

    @property
    def can_process(self) -> bool:
        return bool(self.items)


class BatchValidationError(RuntimeError):
    pass


def sanitize_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise BatchValidationError(f"Unsafe filename: {filename}")
    return path.name


def save_stream(stream: io.BufferedIOBase, destination: Path, max_bytes: int) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    with destination.open("wb") as output:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                output.close()
                destination.unlink(missing_ok=True)
                raise BatchValidationError(f"File exceeds {max_bytes} bytes")
            output.write(chunk)
    return total


def _safe_zip_members(archive: zipfile.ZipFile, settings: Settings) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if len(members) > settings.max_batch_files + 10:
        raise BatchValidationError("Archive contains too many entries")
    total_uncompressed = 0
    for member in members:
        path = PurePosixPath(member.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise BatchValidationError(f"Unsafe archive path: {member.filename}")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise BatchValidationError(f"Archive symlinks are not allowed: {member.filename}")
        total_uncompressed += member.file_size
        if member.file_size > settings.max_file_bytes:
            raise BatchValidationError(f"Archive member is too large: {member.filename}")
        if member.compress_size and member.file_size / member.compress_size > settings.max_archive_ratio:
            raise BatchValidationError(f"Suspicious compression ratio: {member.filename}")
    if total_uncompressed > settings.max_batch_bytes:
        raise BatchValidationError("Archive expands beyond the batch size limit")
    return members


def extract_zip_safely(archive_path: Path, destination: Path, settings: Settings) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = _safe_zip_members(archive, settings)
            for member in members:
                member_path = PurePosixPath(member.filename.replace("\\", "/"))
                if not member_path.parts or member.is_dir():
                    continue
                target = destination.joinpath(*member_path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except (zipfile.BadZipFile, OSError) as exc:
        raise BatchValidationError(f"Malformed ZIP archive: {exc}") from exc

    children = [child for child in destination.iterdir() if not child.name.startswith(".")]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return destination


def _parse_manifest(path: Path) -> tuple[list[dict[str, str]], list[IntakeIssue]]:
    errors: list[IntakeIssue] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or "name" not in reader.fieldnames:
                return [], [IntakeIssue("labels.csv", "missing_name_column", "CSV must contain a name column")]
            rows = list(reader)
    except (UnicodeDecodeError, csv.Error, OSError) as exc:
        return [], [IntakeIssue("labels.csv", "invalid_manifest", str(exc))]

    seen: set[str] = set()
    valid_rows: list[dict[str, str]] = []
    for number, row in enumerate(rows, start=2):
        raw_name = (row.get("name") or "").strip()
        if not raw_name:
            errors.append(IntakeIssue(f"row {number}", "empty_name", "Manifest name cannot be empty"))
            continue
        try:
            name = sanitize_filename(raw_name)
        except BatchValidationError as exc:
            errors.append(IntakeIssue(raw_name, "unsafe_name", str(exc)))
            continue
        if name != raw_name:
            errors.append(IntakeIssue(raw_name, "root_only", "Manifest filenames must be at the batch root"))
            continue
        if name in seen:
            errors.append(IntakeIssue(name, "duplicate_name", "Manifest names must be unique"))
            continue
        seen.add(name)
        result_json = (row.get("result_json") or "").strip()
        if result_json:
            try:
                Prediction.model_validate(json.loads(result_json))
            except Exception as exc:
                errors.append(IntakeIssue(name, "invalid_result_json", f"Expected JSON does not match schema: {exc}"))
                continue
        valid_rows.append({"name": name, "result_json": result_json})
    return valid_rows, errors


def validate_batch_root(root: Path, settings: Settings) -> IntakeResult:
    result = IntakeResult()
    manifest = root / "labels.csv"
    if not manifest.is_file():
        result.errors.append(IntakeIssue("labels.csv", "missing_manifest", "Batch must contain labels.csv at its root"))
        return result

    rows, manifest_errors = _parse_manifest(manifest)
    result.errors.extend(manifest_errors)
    root_files = {path.name: path for path in root.iterdir() if path.is_file() and not path.name.startswith(".")}
    audio_files = {
        name: path for name, path in root_files.items() if path.suffix.lower() in SUPPORTED_AUDIO_EXTENSIONS
    }
    if len(audio_files) > settings.max_batch_files:
        result.errors.append(IntakeIssue("batch", "too_many_files", "Batch exceeds the file-count limit"))
        return result

    manifest_names = {row["name"] for row in rows}
    for name in sorted(audio_files.keys() - manifest_names):
        result.warnings.append(IntakeIssue(name, "unmatched_file", "Audio file has no manifest row and will be skipped"))

    for row in rows:
        name = row["name"]
        path = root_files.get(name)
        if path is None:
            result.errors.append(IntakeIssue(name, "missing_file", "Manifest row has no matching file"))
            continue
        if path.suffix.lower() not in SUPPORTED_AUDIO_EXTENSIONS:
            result.errors.append(IntakeIssue(name, "unsupported_extension", f"Unsupported audio extension: {path.suffix}"))
            continue
        if path.stat().st_size > settings.max_file_bytes:
            result.errors.append(IntakeIssue(name, "file_too_large", "File exceeds the configured size limit"))
            continue
        try:
            probe = probe_audio(path)
        except AudioProcessingError as exc:
            result.errors.append(IntakeIssue(name, "invalid_audio", str(exc)))
            continue
        result.items.append(
            ValidatedItem(
                name=name,
                path=path,
                expected_json=row["result_json"] or None,
                duration_seconds=probe.duration_seconds,
            )
        )
    return result
