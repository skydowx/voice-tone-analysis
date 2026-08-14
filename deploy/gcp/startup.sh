#!/usr/bin/env bash
set -Eeuo pipefail

exec > >(tee -a /var/log/autoace-startup.log | logger -t autoace-startup -s 2>/dev/console) 2>&1

readonly METADATA_ROOT="http://metadata.google.internal/computeMetadata/v1"
readonly METADATA_HEADER="Metadata-Flavor: Google"

metadata() {
  curl --fail --silent --show-error \
    --header "${METADATA_HEADER}" \
    "${METADATA_ROOT}/$1"
}

PROJECT_ID="$(metadata project/project-id)"
IMAGE_URI="$(metadata instance/attributes/image-uri)"
PUBLIC_HOST="$(metadata instance/attributes/public-host)"
DOMAIN="$(metadata instance/attributes/domain)"
REGISTRY_HOST="${IMAGE_URI%%/*}"

export DEBIAN_FRONTEND=noninteractive

if [[ ! -f /swapfile ]]; then
  fallocate --length 2G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

apt-get update
apt-get install --yes --no-install-recommends ca-certificates curl docker.io jq
systemctl enable --now docker

access_token() {
  metadata instance/service-accounts/default/token | jq --raw-output '.access_token'
}

secret() {
  local name="$1"
  local token
  token="$(access_token)"
  curl --fail --silent --show-error \
    --header "Authorization: Bearer ${token}" \
    "https://secretmanager.googleapis.com/v1/projects/${PROJECT_ID}/secrets/${name}/versions/latest:access" \
    | jq --raw-output '.payload.data' \
    | base64 --decode
}

mkdir --parents /etc/autoace
chmod 700 /etc/autoace
umask 077

GEMINI_API_KEY="$(secret autoace-gemini-key)"
EVALUATOR_PASSWORD="$(secret autoace-evaluator-password)"
SESSION_SECRET="$(secret autoace-session-secret)"
POSTHOG_PROJECT_TOKEN="$(secret autoace-posthog-token 2>/dev/null || true)"

cat > /etc/autoace/app.env <<EOF
APP_ENV=production
APP_VERSION=${IMAGE_URI##*:}
APP_DATA_DIR=/data
POSTHOG_PROJECT_TOKEN=${POSTHOG_PROJECT_TOKEN}
POSTHOG_HOST=https://us.i.posthog.com
GEMINI_API_KEY=${GEMINI_API_KEY}
GEMINI_MODEL=gemini-3.1-flash-lite
GEMINI_MAX_OUTPUT_TOKENS=384
GEMINI_THINKING_LEVEL=minimal
GEMINI_EMOTION_STRATEGY=transcript_local_profiles
GEMINI_AUDIO_VIEW=full
PROCESSING_CONCURRENCY=1
EVALUATOR_USERNAME=evaluator
EVALUATOR_PASSWORD=${EVALUATOR_PASSWORD}
SESSION_SECRET=${SESSION_SECRET}
COOKIE_SECURE=true
TRUSTED_HOSTS=${DOMAIN},${PUBLIC_HOST},localhost,127.0.0.1
EOF

cat > /etc/autoace/Caddyfile <<EOF
${PUBLIC_HOST}, ${DOMAIN} {
    encode zstd gzip
    header {
        -Server
        Referrer-Policy "no-referrer"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
    }
    reverse_proxy autoace-app:8080
}
EOF

access_token | docker login \
  --username oauth2accesstoken \
  --password-stdin \
  "https://${REGISTRY_HOST}"

docker pull "${IMAGE_URI}"
docker logout "${REGISTRY_HOST}" >/dev/null
docker pull caddy:2-alpine
docker network inspect autoace >/dev/null 2>&1 || docker network create autoace
docker volume inspect autoace-data >/dev/null 2>&1 || docker volume create autoace-data
docker volume inspect autoace-caddy-data >/dev/null 2>&1 || docker volume create autoace-caddy-data
docker volume inspect autoace-caddy-config >/dev/null 2>&1 || docker volume create autoace-caddy-config

docker rm --force autoace-app >/dev/null 2>&1 || true
docker run --detach \
  --name autoace-app \
  --network autoace \
  --env-file /etc/autoace/app.env \
  --volume autoace-data:/data \
  --restart unless-stopped \
  "${IMAGE_URI}"

docker rm --force autoace-caddy >/dev/null 2>&1 || true
docker run --detach \
  --name autoace-caddy \
  --network autoace \
  --publish 80:80 \
  --publish 443:443 \
  --publish 443:443/udp \
  --volume /etc/autoace/Caddyfile:/etc/caddy/Caddyfile:ro \
  --volume autoace-caddy-data:/data \
  --volume autoace-caddy-config:/config \
  --restart unless-stopped \
  caddy:2-alpine

unset GEMINI_API_KEY EVALUATOR_PASSWORD SESSION_SECRET POSTHOG_PROJECT_TOKEN
docker image prune --force
