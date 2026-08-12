(() => {
  const summary = document.querySelector("[data-batch-id]");
  if (!summary) return;
  const terminal = new Set(["complete", "completed_with_errors", "failed", "validation_failed"]);
  const batchId = summary.dataset.batchId;
  const initial = summary.dataset.status;
  let lastCompleted = -1;
  const poll = async () => {
    try {
      const response = await fetch(`/api/batches/${batchId}`, {headers: {Accept: "application/json"}});
      if (!response.ok) return;
      const payload = await response.json();
      const done = payload.batch.completed + payload.batch.failed;
      if (terminal.has(payload.batch.status) || (lastCompleted >= 0 && done !== lastCompleted) || payload.batch.status !== initial) {
        window.location.reload();
        return;
      }
      lastCompleted = done;
    } catch (_) { /* Retry on the next interval. */ }
  };
  setInterval(poll, 1800);
  poll();
})();
