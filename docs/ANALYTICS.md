# Privacy-limited analytics and session replay

PostHog is optional. Set `POSTHOG_PROJECT_TOKEN` and `POSTHOG_HOST` to enable allowlisted server-side
operational events. Set `POSTHOG_SESSION_REPLAY=true` as well to load the browser recorder. When the token is
absent, the server adapter becomes a no-op and the replay script is omitted. Analytics failures never change
upload, inference, download, health, or readiness behavior.

Server events disable PostHog person profiles and GeoIP enrichment. Audio, transcripts, filenames, labels,
predictions, credentials, raw exceptions, server paths, IP addresses, and user-agent values are never included.
A strict allowlist in `app/services/analytics.py` drops undeclared event properties.

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

## Replay privacy contract

Replay is enabled on the assessment VM and remains off by default elsewhere. The browser SDK is configured
only for replay: autocapture, pageview/pageleave events, dead-click events, exception capture, heatmaps,
performance/network timing, surveys, and console recording are disabled. It does not identify the evaluator,
uses session-scoped browser storage, respects supported Do Not Track signals, and does not share identity
across subdomains.

Before replay data leaves the browser:

- every input value and every text node is masked;
- URL query strings are stripped;
- the login form, CSRF inputs, selected filenames, batch history, evaluation metrics, expected/predicted
  outputs, validation messages, and result tables use `ph-no-capture` and become opaque placeholders;
- call audio and transcripts never enter the page and therefore cannot be recorded.

The masked replay is intended to answer flow questions such as whether upload selection, submission,
navigation, and progress updates behaved as expected. It is deliberately unsuitable for inspecting the
reviewer's credentials, filenames, assessment labels, or model output. A visible footer notice indicates when
replay is active. To disable replay while retaining server events, set `POSTHOG_SESSION_REPLAY=false` and
restart. Remove the project token to disable both.

The reverse proxy's content-security policy permits the local loader and PostHog's script/connect/worker
origins while retaining same-origin defaults for the rest of the application.

Official references: [Python SDK](https://posthog.com/docs/libraries/python),
[JavaScript configuration](https://posthog.com/docs/libraries/js/config),
[session replay installation](https://posthog.com/docs/session-replay/installation), and
[replay privacy controls](https://posthog.com/docs/session-replay/privacy).
