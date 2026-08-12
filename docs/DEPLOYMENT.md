# Deployment

## Durable assessment deployment (recommended)

Use a small Linux VM with Docker Compose and a persistent disk. Put Caddy, nginx, or the cloud HTTPS load
balancer in front of `127.0.0.1:8080`. Copy `.env.example` to `.env.production`, set production secrets,
the public host allowlist, and then run:

```bash
docker compose -f compose.production.yaml up --build -d
curl --fail http://127.0.0.1:8080/healthz
```

This is the recommended evaluation topology because SQLite and uploaded audio persist on the named volume.
Keep one application replica.

## Cloud Run smoke deployment

`deploy/cloudrun.sh` builds and deploys a single instance with background CPU enabled. Before running it,
create Artifact Registry and these Secret Manager secrets:

- `autoace-gemini-key`
- `autoace-password-hash`
- `autoace-session-secret`

Then set `GCP_PROJECT_ID` and optionally `GCP_REGION`. The script has deliberately not been run because no
GCP project is configured yet.

Cloud Run's local filesystem is ephemeral. This option is suitable for a live review smoke test, not durable
retention. A production Cloud Run migration should move batch rows to Postgres/Cloud SQL and uploads to
object storage before increasing `--max-instances` beyond one.

## Rollback

Images should be tagged with an immutable commit SHA in CI. On a VM, redeploy the previous tag while leaving
the data volume mounted. On Cloud Run, route traffic back to the prior revision. Database schema creation is
additive in this version and requires no destructive rollback.
