from __future__ import annotations

import zipfile

import pytest

from app.services.batch_validation import BatchValidationError, extract_zip_safely, validate_batch_root

from .conftest import write_wav


def test_validate_batch_reports_missing_and_unmatched_files(tmp_path, settings):
    root = tmp_path / "batch"
    root.mkdir()
    write_wav(root / "call.wav")
    write_wav(root / "extra.wav")
    (root / "labels.csv").write_text("name,result_json\ncall.wav,\nmissing.wav,\n", encoding="utf-8")

    result = validate_batch_root(root, settings)
    assert [item.name for item in result.items] == ["call.wav"]
    assert any(issue.code == "missing_file" for issue in result.errors)
    assert any(issue.code == "unmatched_file" for issue in result.warnings)


def test_zip_slip_is_rejected(tmp_path, settings):
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../escape.wav", b"bad")
    with pytest.raises(BatchValidationError, match="Unsafe archive path"):
        extract_zip_safely(archive_path, tmp_path / "output", settings)


def test_manifest_rejects_duplicate_names(tmp_path, settings):
    root = tmp_path / "batch"
    root.mkdir()
    write_wav(root / "call.wav")
    (root / "labels.csv").write_text("name,result_json\ncall.wav,\ncall.wav,\n", encoding="utf-8")
    result = validate_batch_root(root, settings)
    assert any(issue.code == "duplicate_name" for issue in result.errors)
