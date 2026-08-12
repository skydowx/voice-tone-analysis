#!/usr/bin/env bash
set -euo pipefail

: "${GCP_PROJECT_ID:?Set GCP_PROJECT_ID}"
: "${GCP_REGION:=us-central1}"
: "${SERVICE_NAME:=autoace-audio-assessment}"

IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/autoace/${SERVICE_NAME}:latest"

gcloud builds submit --project "${GCP_PROJECT_ID}" --tag "${IMAGE}" .
gcloud run deploy "${SERVICE_NAME}" \
  --project "${GCP_PROJECT_ID}" \
  --region "${GCP_REGION}" \
  --image "${IMAGE}" \
  --port 8080 \
  --allow-unauthenticated \
  --max-instances 1 \
  --min-instances 0 \
  --concurrency 20 \
  --cpu 2 \
  --memory 2Gi \
  --timeout 900 \
  --no-cpu-throttling \
  --set-env-vars "APP_ENV=production,APP_DATA_DIR=/tmp/autoace,COOKIE_SECURE=true,TRUSTED_HOSTS=*" \
  --set-secrets "GEMINI_API_KEY=autoace-gemini-key:latest,EVALUATOR_PASSWORD_HASH=autoace-password-hash:latest,SESSION_SECRET=autoace-session-secret:latest"
