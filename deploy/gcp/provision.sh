#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_ID="${GCP_PROJECT_ID:-autoace-assessment}"
readonly REGION="${GCP_REGION:-us-east1}"
readonly ZONE="${GCP_ZONE:-us-east1-b}"
readonly ARTIFACT_REGION="${GCP_ARTIFACT_REGION:-us-central1}"
readonly DOMAIN="${AUTOACE_DOMAIN:-autoace.omerkhalil.com}"
readonly REPOSITORY="autoace"
readonly INSTANCE="autoace-app"
readonly ADDRESS="autoace-web-ip-east"
readonly SERVICE_ACCOUNT_NAME="autoace-vm"
readonly SERVICE_ACCOUNT="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
readonly IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d-%H%M%S)}"
readonly IMAGE_URI="${ARTIFACT_REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/audio-assessment:${IMAGE_TAG}"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ ! -f "${REPO_ROOT}/.env" ]]; then
  echo "Missing ${REPO_ROOT}/.env" >&2
  exit 1
fi

if [[ "$(gcloud config get-value project 2>/dev/null)" != "${PROJECT_ID}" ]]; then
  echo "Activate the ${PROJECT_ID} gcloud configuration before provisioning." >&2
  exit 1
fi

echo "Enabling required Google Cloud APIs..."
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  compute.googleapis.com \
  iam.googleapis.com \
  secretmanager.googleapis.com \
  --project "${PROJECT_ID}"

if ! gcloud artifacts repositories describe "${REPOSITORY}" \
  --location "${ARTIFACT_REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud artifacts repositories create "${REPOSITORY}" \
    --repository-format docker \
    --location "${ARTIFACT_REGION}" \
    --description "AutoAce assessment container images" \
    --project "${PROJECT_ID}"
fi

if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT}" \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SERVICE_ACCOUNT_NAME}" \
    --display-name "AutoAce assessment VM" \
    --project "${PROJECT_ID}"
fi

for role in roles/artifactregistry.reader roles/logging.logWriter roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member "serviceAccount:${SERVICE_ACCOUNT}" \
    --role "${role}" \
    --condition None \
    --quiet >/dev/null
done

ensure_secret() {
  local name="$1"
  if ! gcloud secrets describe "${name}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud secrets create "${name}" \
      --replication-policy automatic \
      --project "${PROJECT_ID}"
  fi
}

secret_has_version() {
  [[ -n "$(gcloud secrets versions list \
    "$1" \
    --filter 'state=ENABLED' \
    --format 'value(name)' \
    --limit 1 \
    --project "${PROJECT_ID}")" ]]
}

ensure_secret autoace-gemini-key
ensure_secret autoace-evaluator-password
ensure_secret autoace-session-secret
ensure_secret autoace-posthog-token

if ! secret_has_version autoace-gemini-key; then
  GEMINI_API_KEY="$(sed -n 's/^GEMINI_API_KEY=//p' "${REPO_ROOT}/.env" | tail -n 1)"
  GEMINI_API_KEY="${GEMINI_API_KEY%\"}"
  GEMINI_API_KEY="${GEMINI_API_KEY#\"}"
  if [[ -z "${GEMINI_API_KEY}" ]]; then
    echo "GEMINI_API_KEY is empty in .env" >&2
    exit 1
  fi
  printf '%s' "${GEMINI_API_KEY}" | gcloud secrets versions add autoace-gemini-key \
    --data-file=- --project "${PROJECT_ID}" >/dev/null
  unset GEMINI_API_KEY
fi

if ! secret_has_version autoace-evaluator-password; then
  openssl rand -base64 24 | tr -d '\n' | gcloud secrets versions add autoace-evaluator-password \
    --data-file=- --project "${PROJECT_ID}" >/dev/null
fi

if ! secret_has_version autoace-session-secret; then
  openssl rand -hex 32 | gcloud secrets versions add autoace-session-secret \
    --data-file=- --project "${PROJECT_ID}" >/dev/null
fi

if ! secret_has_version autoace-posthog-token; then
  POSTHOG_PROJECT_TOKEN="$(sed -n 's/^POSTHOG_PROJECT_TOKEN=//p' "${REPO_ROOT}/.env" | tail -n 1)"
  POSTHOG_PROJECT_TOKEN="${POSTHOG_PROJECT_TOKEN%\"}"
  POSTHOG_PROJECT_TOKEN="${POSTHOG_PROJECT_TOKEN#\"}"
  if [[ -n "${POSTHOG_PROJECT_TOKEN}" ]]; then
    printf '%s' "${POSTHOG_PROJECT_TOKEN}" | gcloud secrets versions add autoace-posthog-token \
      --data-file=- --project "${PROJECT_ID}" >/dev/null
  fi
  unset POSTHOG_PROJECT_TOKEN
fi

echo "Building ${IMAGE_URI}..."
gcloud builds submit "${REPO_ROOT}" \
  --tag "${IMAGE_URI}" \
  --project "${PROJECT_ID}"

if ! gcloud compute addresses describe "${ADDRESS}" \
  --region "${REGION}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute addresses create "${ADDRESS}" \
    --region "${REGION}" \
    --network-tier PREMIUM \
    --project "${PROJECT_ID}"
fi
PUBLIC_IP="$(gcloud compute addresses describe "${ADDRESS}" \
  --region "${REGION}" --format 'value(address)' --project "${PROJECT_ID}")"
PUBLIC_HOST="${PUBLIC_IP}.sslip.io"

if ! gcloud compute firewall-rules describe autoace-allow-web \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute firewall-rules create autoace-allow-web \
    --allow tcp:80,tcp:443,udp:443 \
    --direction INGRESS \
    --source-ranges 0.0.0.0/0 \
    --target-tags autoace-web \
    --description "Public HTTPS for AutoAce assessment" \
    --project "${PROJECT_ID}"
fi

if ! gcloud compute firewall-rules describe autoace-allow-iap-ssh \
  --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute firewall-rules create autoace-allow-iap-ssh \
    --allow tcp:22 \
    --direction INGRESS \
    --source-ranges 35.235.240.0/20 \
    --target-tags autoace-web \
    --description "SSH through Identity-Aware Proxy only" \
    --project "${PROJECT_ID}"
fi

if gcloud compute instances describe "${INSTANCE}" \
  --zone "${ZONE}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Instance ${INSTANCE} already exists; refusing to replace it automatically." >&2
  echo "Use deploy/gcp/redeploy.sh for an existing instance." >&2
  exit 1
fi

gcloud compute instances create "${INSTANCE}" \
  --project "${PROJECT_ID}" \
  --zone "${ZONE}" \
  --machine-type e2-small \
  --image-family debian-12 \
  --image-project debian-cloud \
  --boot-disk-size 20GB \
  --boot-disk-type pd-standard \
  --address "${PUBLIC_IP}" \
  --network-tier PREMIUM \
  --service-account "${SERVICE_ACCOUNT}" \
  --scopes cloud-platform \
  --tags autoace-web \
  --metadata "enable-oslogin=TRUE,image-uri=${IMAGE_URI},public-host=${PUBLIC_HOST},domain=${DOMAIN}" \
  --metadata-from-file "startup-script=${SCRIPT_DIR}/startup.sh" \
  --shielded-secure-boot \
  --shielded-vtpm \
  --shielded-integrity-monitoring

cat <<EOF

Provisioning started.

Temporary HTTPS URL: https://${PUBLIC_HOST}
Requested domain:    https://${DOMAIN}
Static IP:           ${PUBLIC_IP}

After the temporary URL is healthy, create this DNS record:
  ${DOMAIN%%.*}  A  ${PUBLIC_IP}

Retrieve the generated evaluator password when needed:
  gcloud secrets versions access latest --secret autoace-evaluator-password --project ${PROJECT_ID}

View startup progress:
  gcloud compute instances get-serial-port-output ${INSTANCE} --zone ${ZONE} --project ${PROJECT_ID}
EOF
