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

### Google Cloud VM provisioning

The checked-in provisioning script creates the recommended topology in `us-east1`: an `e2-small`
Compute Engine VM, 20 GB standard persistent boot disk, reserved external IP, HTTPS through Caddy,
Artifact Registry image, and a dedicated least-privilege VM service account. The application data and
Caddy certificates live in named Docker volumes on the persistent boot disk.

Authenticate `gcloud`, activate a configuration targeting the intended project, and run:

```bash
GCP_PROJECT_ID=autoace-assessment \
AUTOACE_DOMAIN=autoace.omerkhalil.com \
deploy/gcp/provision.sh
```

The script creates a temporary `<static-ip>.sslip.io` HTTPS hostname, so the deployment can be checked before
DNS is changed. It stores the local Gemini key, optional PostHog project token, and generated application
secrets in Secret Manager; their values are never placed in VM metadata or container images. Add an `A`
record for the final hostname after the temporary health check succeeds.

The evaluator password is generated during first provisioning. Retrieve it locally with:

```bash
gcloud secrets versions access latest \
  --secret autoace-evaluator-password \
  --project autoace-assessment
```

The initial deployment uses `us-east1-b` because all `us-central1` zones returned temporary E2 capacity
errors during provisioning. Artifact Registry remains in `us-central1`; this does not affect the public URL
or application behavior. Deploy a new immutable image and restart the existing VM with:

```bash
deploy/gcp/redeploy.sh
```

The current assessment deployment is live at <https://autoace.omerkhalil.com> on an `e2-small` VM in
`us-east1-b`, with Caddy-managed HTTPS and one application worker. The Gemini key, evaluator password, and
session secret, and optional PostHog project token are stored in Secret Manager. The immutable container tag
is exposed as `APP_VERSION` for the `application started` release event. Before sharing credentials, verify
the API key belongs to an active-billing Cloud project so the paid-service data terms described in
[Security](SECURITY.md) apply.

## Cloud Run smoke deployment

`deploy/cloudrun.sh` builds and deploys a single instance with background CPU enabled. Before running it,
create Artifact Registry and these Secret Manager secrets:

- `autoace-gemini-key`
- `autoace-password-hash`
- `autoace-session-secret`
- `autoace-posthog-token` (optional; omit the Cloud Run secret mapping when analytics is disabled)

Then set `GCP_PROJECT_ID` and optionally `GCP_REGION`. This path is included as an alternative but is not used
for the assessment deployment because its ephemeral filesystem does not meet the review/retry requirement.

Cloud Run's local filesystem is ephemeral. This option is suitable for a live review smoke test, not durable
retention. A production Cloud Run migration should move batch rows to Postgres/Cloud SQL and uploads to
object storage before increasing `--max-instances` beyond one.

## Rollback

Images should be tagged with an immutable commit SHA in CI. On a VM, redeploy the previous tag while leaving
the data volume mounted. On Cloud Run, route traffic back to the prior revision. Database schema creation is
additive in this version and requires no destructive rollback.
