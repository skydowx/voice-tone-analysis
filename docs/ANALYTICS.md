# Privacy-limited operational analytics

PostHog is optional and server-side only. Set `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` to enable it; when
the token is absent, the same adapter becomes a no-op. Capture and shutdown failures are logged but never
change upload, inference, download, health, or readiness behavior.

The integration intentionally does not install the browser SDK. Autocapture and session replay are disabled,
and PostHog person profiles and GeoIP enrichment are disabled for every event. Audio, transcripts, filenames,
labels, predictions, credentials, raw exceptions, server paths, IP addresses, and user-agent values are never
included. A strict allowlist in `app/services/analytics.py` drops undeclared event properties.

| Event | Allowed application properties |
|---|---|
| `application started` | none; the adapter adds environment and release |
| `batch uploaded` | random batch ID, item count, processable flag, validation error/warning counts |
| `batch completed` | random batch ID, status and counts, aggregate duration/cost/processing time |
| `batch item failed` | random batch ID and normalized error category |
| `results downloaded` | random batch ID, format, status and completion/failure counts |

The VM reads `autoace-posthog-token` from Secret Manager and passes the immutable image tag as `APP_VERSION`.
This makes `application started` a release marker without granting the application read access to PostHog.
The `phc_` project token is ingestion-only; never provide a `phx_` personal API key to the application.

Official references: [Python SDK](https://posthog.com/docs/libraries/python) and
[privacy controls](https://posthog.com/docs/privacy).
