# Security and privacy

## Controls implemented

- All evaluator pages and download endpoints require a signed session.
- State-changing forms require a session-bound CSRF token.
- Production startup rejects default credentials and insecure cookies.
- Passwords may be supplied as PBKDF2-SHA256 hashes; use `scripts/hash_password.py`.
- Login attempts are throttled per client address.
- Uploads are streamed with file/batch size limits. ZIP traversal, symlinks, excessive expansion ratios,
  excessive entry counts, unsupported extensions, malformed audio, duplicate names, and invalid label
  JSON are rejected or isolated.
- Structured provider responses are strict-schema validated and explicitly forbid PII or spoken words.
- The emotion pass returns a redacted speaker-turn transcript to process memory. It is used only by local
  deterministic rules and is never stored, logged, displayed, or included in another provider request.
- The UI never exposes server-side paths or the Gemini API key.

## Data flow and retention

Each original upload is stored on the VM's persistent Docker volume for review, retry, and artifact download.
Normalized WAV is created in a temporary directory and deleted immediately after each inference call.
Ephemeral transcript text becomes unreachable when that item completes; audit records contain only aggregate
turn counts and emotion-evidence scores. No call audio, transcript, or live job database is committed to the
repository.

For this assessment deployment, uploads are retained only through the review period and the persistent
application volume will be deleted no later than **seven days after written confirmation that review is
complete**. This is a manual operational commitment because the reviewer controls when the assessment ends;
the application does not silently delete evidence during review. The deletion procedure is documented in
[Operations](OPERATIONS.md).

## Gemini disclosure

- Two independent requests send the complete normalized audio inline to the Gemini Developer API. Audio
  therefore leaves the AutoAce-hosted GCP VM and is processed by Google. Filenames and supplied labels are
  excluded from both requests.
- The application uses direct inline requests, not the Gemini Files API, cached content, grounding, or tuning.
- The first response's redacted transcript exists only in application memory and is not sent in the second
  request. Structured predictions and aggregate diagnostics are persisted locally.
- The deployment is designed for the paid Gemini service. Google's current terms state that paid-service
  prompts, files, and responses are not used to improve its products. Google may retain prompts and responses
  for a limited period for abuse prevention or legal compliance and may transiently cache or process them in
  countries where it maintains facilities. Google does not publish a fixed duration for this abuse-monitoring
  window. Zero-data-retention approval is not claimed.
- The documented price assumption for Gemini 3.1 Flash-Lite is $0.50 per million audio-input tokens and
  $1.50 per million output tokens, including thinking tokens. A paid-service designation requires the API
  key's owning Cloud project to have active billing.

Current provider references: [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Gemini API terms](https://ai.google.dev/gemini-api/terms), and
[zero data retention](https://ai.google.dev/gemini-api/docs/zdr).

## Before exposing publicly

1. Use HTTPS behind a managed load balancer/reverse proxy.
2. Set `APP_ENV=production`, `COOKIE_SECURE=true`, an explicit host allowlist, a random session secret,
   and a PBKDF2 password hash through a secret manager.
3. Restrict inbound access by identity-aware proxy or reviewer IP where possible.
4. Confirm the company approves sending recordings to Gemini and that the configured key belongs to an
   active-billing project. Approval for the supplied assessment recordings was received.
5. Schedule the documented post-review volume deletion; do not retain call audio indefinitely.
6. Run dependency and container vulnerability scans in CI.

## Threats intentionally deferred

SSO/RBAC, malware scanning, customer-managed encryption keys, managed audit-log export, and multi-tenant
isolation are beyond a single-reviewer assessment. The boundaries are documented so they are not mistaken
for completed enterprise controls.
