from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from app.config import Settings
from app.repositories.batches import BatchRepository
from app.services.classifier import AudioClassifier


logger = logging.getLogger(__name__)


class BatchProcessor:
    def __init__(self, repository: BatchRepository, classifier: AudioClassifier, settings: Settings):
        self.repository = repository
        self.classifier = classifier
        self.settings = settings
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def submit(self, batch_id: str) -> None:
        with self._lock:
            running = self._threads.get(batch_id)
            if running and running.is_alive():
                return
            thread = threading.Thread(
                target=self._run_batch,
                args=(batch_id,),
                name=f"batch-{batch_id[:8]}",
                daemon=True,
            )
            self._threads[batch_id] = thread
            thread.start()

    def _run_batch(self, batch_id: str) -> None:
        try:
            self.repository.start_batch(batch_id)
            items = self.repository.pending_items(batch_id)
            with ThreadPoolExecutor(
                max_workers=self.settings.processing_concurrency,
                thread_name_prefix="audio-item",
            ) as executor:
                futures = {executor.submit(self._run_item, item): item for item in items}
                for future in as_completed(futures):
                    item = futures[future]
                    try:
                        future.result()
                    except Exception:
                        logger.exception("Unhandled item failure", extra={"item_id": item["id"]})
        finally:
            with self._lock:
                self._threads.pop(batch_id, None)

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        deadline = time.monotonic() + timeout_seconds
        with self._lock:
            threads = list(self._threads.values())
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            thread.join(remaining)

    def _run_item(self, item: dict[str, object]) -> None:
        item_id = str(item["id"])
        try:
            self.repository.update_item_status(item_id, "preprocessing")
            self.repository.update_item_status(item_id, "analyzing")
            envelope = self.classifier.analyze(Path(str(item["path"])))
            self.repository.complete_item(item_id, envelope.model_dump(mode="json"))
        except Exception as exc:
            logger.warning("Item failed: %s", exc, extra={"item_id": item_id})
            self.repository.fail_item(item_id, str(exc))
