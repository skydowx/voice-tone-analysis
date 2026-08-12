# Operations runbook

## Health

- `GET /healthz` verifies the process is serving.
- `GET /readyz` verifies SQLite is accessible.
- A batch in `completed_with_errors` is a successful partial run; inspect each item error.
- On restart, in-flight items and batches are marked failed rather than left permanently “processing.”
- On the GCP VM, inspect first-boot progress with `gcloud compute instances get-serial-port-output autoace-app
  --zone us-east1-b --project autoace-assessment`.

## Common failures

| Symptom | Likely cause | Action |
|---|---|---|
| Validation finding | Missing/mismatched manifest row or invalid media | Fix that file; valid siblings still run |
| Gemini inference failed | Key, quota, provider timeout, or schema rejection | Check provider status/quota; retry a new batch |
| Cost/min above ceiling | Model, prompt, or output-token change | Revert to the pinned Flash-Lite pipeline; rerun benchmark and check both aggregate and maximum per-clip cost |
| `ffprobe` missing | Host dependency absent | Install FFmpeg or use the container |
| Cookie login loop | Secure cookie over plain HTTP | Use HTTPS in production or development mode locally |

## Backups and deletion

For Compose/VM deployment, back up the named data volume only if the reviewer requests retained results.
No later than seven days after written confirmation that review is complete, export any specifically
requested artifact and then remove the assessment data on the VM:

```bash
gcloud compute ssh autoace-app \
  --zone us-east1-b \
  --tunnel-through-iap \
  --project autoace-assessment \
  --command 'sudo docker rm --force autoace-app && sudo docker volume rm autoace-data'
```

This is destructive: it removes all uploaded calls, job records, and generated artifacts. The container can
be recreated by rerunning the startup script, but deleted assessment data cannot be recovered unless it was
separately backed up. Delete any requested backup on the same schedule. Never copy `.env`, raw call audio, or
`artifacts/live/` into source control.

## Release checks

1. `make test`
2. `make live-eval` only when a paid regression run is intended
3. Confirm `docs/EVALUATION.md` cost remains below $0.003/audio minute
4. Build the container and check `/healthz` plus a real ZIP upload
5. Verify HTTPS, host allowlist, secure cookie, secret-manager values, and reviewer credentials
