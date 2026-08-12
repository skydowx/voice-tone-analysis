# Operations runbook

## Health

- `GET /healthz` verifies the process is serving.
- `GET /readyz` verifies SQLite is accessible.
- A batch in `completed_with_errors` is a successful partial run; inspect each item error.
- On restart, in-flight items and batches are marked failed rather than left permanently “processing.”

## Common failures

| Symptom | Likely cause | Action |
|---|---|---|
| Validation finding | Missing/mismatched manifest row or invalid media | Fix that file; valid siblings still run |
| Gemini inference failed | Key, quota, provider timeout, or schema rejection | Check provider status/quota; retry a new batch |
| Cost/min above ceiling | Model or output-token change | Revert to Flash-Lite/bounded output; rerun benchmark |
| `ffprobe` missing | Host dependency absent | Install FFmpeg or use the container |
| Cookie login loop | Secure cookie over plain HTTP | Use HTTPS in production or development mode locally |

## Backups and deletion

For Compose/VM deployment, back up the named data volume if results must be retained. To meet a deletion
request, remove the relevant upload directory and batch database records, or destroy the evaluation volume
after exporting the final result. Never copy `.env`, raw call audio, or `artifacts/live/` into source control.

## Release checks

1. `make test`
2. `make live-eval` only when a paid regression run is intended
3. Confirm `docs/EVALUATION.md` cost remains below $0.003/audio minute
4. Build the container and check `/healthz` plus a real ZIP upload
5. Verify HTTPS, host allowlist, secure cookie, secret-manager values, and reviewer credentials
