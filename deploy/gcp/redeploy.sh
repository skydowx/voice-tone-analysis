#!/usr/bin/env bash
set -Eeuo pipefail

readonly PROJECT_ID="${GCP_PROJECT_ID:-autoace-assessment}"
readonly ZONE="${GCP_ZONE:-us-east1-b}"
readonly ARTIFACT_REGION="${GCP_ARTIFACT_REGION:-us-central1}"
readonly REPOSITORY="autoace"
readonly INSTANCE="autoace-app"
readonly IMAGE_TAG="${IMAGE_TAG:-$(date -u +%Y%m%d-%H%M%S)}"
readonly IMAGE_URI="${ARTIFACT_REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/audio-assessment:${IMAGE_TAG}"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

if [[ "$(gcloud config get-value project 2>/dev/null)" != "${PROJECT_ID}" ]]; then
  echo "Activate the ${PROJECT_ID} gcloud configuration before redeploying." >&2
  exit 1
fi

gcloud compute instances describe "${INSTANCE}" \
  --zone "${ZONE}" --project "${PROJECT_ID}" >/dev/null

gcloud builds submit "${REPO_ROOT}" \
  --tag "${IMAGE_URI}" \
  --project "${PROJECT_ID}"

gcloud compute instances add-metadata "${INSTANCE}" \
  --zone "${ZONE}" \
  --metadata "image-uri=${IMAGE_URI}" \
  --metadata-from-file "startup-script=${SCRIPT_DIR}/startup.sh" \
  --project "${PROJECT_ID}"

gcloud compute ssh "${INSTANCE}" \
  --zone "${ZONE}" \
  --tunnel-through-iap \
  --command "sudo google_metadata_script_runner startup" \
  --project "${PROJECT_ID}"

echo "Deployed ${IMAGE_URI}"

