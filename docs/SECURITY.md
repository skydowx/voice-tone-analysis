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

Normalized WAV is created in a temporary directory and deleted immediately after each inference call.
Ephemeral transcript text becomes unreachable when that item completes; audit records contain only aggregate
turn counts and emotion-evidence scores.
Original uploaded clips remain under the configured data directory to support audit/retry. They are not
committed to source control. For an evaluation deployment, delete the persistent volume after review or
apply an agreed short retention window. Provider request logs and retention are governed by the selected
Gemini paid-service terms.

## Before exposing publicly

1. Use HTTPS behind a managed load balancer/reverse proxy.
2. Set `APP_ENV=production`, `COOKIE_SECURE=true`, an explicit host allowlist, a random session secret,
   and a PBKDF2 password hash through a secret manager.
3. Restrict inbound access by identity-aware proxy or reviewer IP where possible.
4. Confirm the company approves sending recordings to Gemini and choose an appropriate region/account.
5. Set and test deletion/retention policy; do not retain call audio by default indefinitely.
6. Run dependency and container vulnerability scans in CI.

## Threats intentionally deferred

SSO/RBAC, malware scanning, customer-managed encryption keys, managed audit-log export, and multi-tenant
isolation are beyond a single-reviewer assessment. The boundaries are documented so they are not mistaken
for completed enterprise controls.
