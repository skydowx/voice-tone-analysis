from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.services.batch_validation import IntakeIssue, ValidatedItem


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class BatchRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total INTEGER NOT NULL DEFAULT 0,
                    completed INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    total_audio_seconds REAL NOT NULL DEFAULT 0,
                    total_cost_usd REAL NOT NULL DEFAULT 0,
                    validation_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expected_json TEXT,
                    prediction_json TEXT,
                    error TEXT,
                    duration_seconds REAL NOT NULL DEFAULT 0,
                    latency_seconds REAL,
                    cost_usd REAL,
                    cost_per_minute_usd REAL,
                    model TEXT,
                    input_tokens INTEGER NOT NULL DEFAULT 0,
                    output_tokens INTEGER NOT NULL DEFAULT 0,
                    thinking_tokens INTEGER NOT NULL DEFAULT 0,
                    features_json TEXT,
                    UNIQUE(batch_id, name)
                );
                CREATE INDEX IF NOT EXISTS idx_items_batch ON items(batch_id);
                """
            )

    def recover_incomplete(self) -> None:
        with self._write_lock, self._connection() as connection:
            connection.execute(
                "UPDATE items SET status='failed', error='Application restarted during processing' WHERE status IN ('queued','preprocessing','analyzing')"
            )
            connection.execute(
                "UPDATE batches SET status='failed', finished_at=? WHERE status IN ('queued','processing')",
                (_now(),),
            )

    def create_batch(
        self,
        name: str,
        items: list[ValidatedItem],
        issues: list[IntakeIssue],
    ) -> str:
        batch_id = uuid.uuid4().hex
        created = _now()
        with self._write_lock, self._connection() as connection:
            connection.execute(
                "INSERT INTO batches(id,name,status,total,created_at,total_audio_seconds,validation_json) VALUES(?,?,?,?,?,?,?)",
                (
                    batch_id,
                    name,
                    "queued" if items else "validation_failed",
                    len(items),
                    created,
                    sum(item.duration_seconds for item in items),
                    json.dumps([issue.__dict__ for issue in issues]),
                ),
            )
            connection.executemany(
                "INSERT INTO items(id,batch_id,name,path,status,expected_json,duration_seconds) VALUES(?,?,?,?,?,?,?)",
                [
                    (
                        uuid.uuid4().hex,
                        batch_id,
                        item.name,
                        str(item.path),
                        "queued",
                        item.expected_json,
                        item.duration_seconds,
                    )
                    for item in items
                ],
            )
        return batch_id

    def start_batch(self, batch_id: str) -> None:
        with self._write_lock, self._connection() as connection:
            connection.execute(
                "UPDATE batches SET status='processing', started_at=? WHERE id=?",
                (_now(), batch_id),
            )

    def update_item_status(self, item_id: str, status: str) -> None:
        with self._write_lock, self._connection() as connection:
            connection.execute("UPDATE items SET status=? WHERE id=?", (status, item_id))

    def complete_item(self, item_id: str, envelope: dict[str, Any]) -> None:
        with self._write_lock, self._connection() as connection:
            connection.execute(
                """UPDATE items SET status='complete', prediction_json=?, duration_seconds=?, latency_seconds=?,
                cost_usd=?, cost_per_minute_usd=?, model=?, input_tokens=?, output_tokens=?, thinking_tokens=?,
                features_json=?, error=NULL WHERE id=?""",
                (
                    json.dumps(envelope["prediction"], separators=(",", ":")),
                    envelope["duration_seconds"],
                    envelope["latency_seconds"],
                    envelope["estimated_cost_usd"],
                    envelope["cost_per_audio_minute_usd"],
                    envelope["model"],
                    envelope["input_tokens"],
                    envelope["output_tokens"],
                    envelope["thinking_tokens"],
                    json.dumps(envelope["features"], separators=(",", ":")),
                    item_id,
                ),
            )
            self._refresh_batch(connection, item_id=item_id)

    def fail_item(self, item_id: str, message: str) -> None:
        with self._write_lock, self._connection() as connection:
            connection.execute(
                "UPDATE items SET status='failed', error=? WHERE id=?",
                (message[:1000], item_id),
            )
            self._refresh_batch(connection, item_id=item_id)

    def _refresh_batch(self, connection: sqlite3.Connection, item_id: str) -> None:
        row = connection.execute("SELECT batch_id FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return
        batch_id = row["batch_id"]
        summary = connection.execute(
            """SELECT COUNT(*) total,
            SUM(CASE WHEN status='complete' THEN 1 ELSE 0 END) completed,
            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) failed,
            COALESCE(SUM(cost_usd),0) cost
            FROM items WHERE batch_id=?""",
            (batch_id,),
        ).fetchone()
        completed = int(summary["completed"] or 0)
        failed = int(summary["failed"] or 0)
        total = int(summary["total"] or 0)
        finished = completed + failed >= total
        status = "complete" if finished and failed == 0 else "completed_with_errors" if finished else "processing"
        connection.execute(
            "UPDATE batches SET completed=?, failed=?, total_cost_usd=?, status=?, finished_at=? WHERE id=?",
            (completed, failed, float(summary["cost"] or 0), status, _now() if finished else None, batch_id),
        )

    def get_batch(self, batch_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            batch = _dict(connection.execute("SELECT * FROM batches WHERE id=?", (batch_id,)).fetchone())
        if batch:
            batch["validation"] = json.loads(batch.pop("validation_json") or "[]")
        return batch

    def list_batches(self, limit: int = 25) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM batches ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_items(self, batch_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM items WHERE batch_id=? ORDER BY name", (batch_id,)
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            for key in ("prediction_json", "expected_json", "features_json"):
                raw = item.pop(key)
                item[key.removesuffix("_json")] = json.loads(raw) if raw else None
            items.append(item)
        return items

    def pending_items(self, batch_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM items WHERE batch_id=? AND status='queued' ORDER BY name", (batch_id,)
            ).fetchall()
        return [dict(row) for row in rows]
