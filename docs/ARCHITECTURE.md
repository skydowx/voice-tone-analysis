# Architecture and decisions

## Request and processing flow

```text
authenticated browser
       │ ZIP/folder + labels.csv
       ▼
FastAPI intake ── safe extraction ── manifest/media validation
       │                                │ invalid rows become findings
       ▼                                ▼
SQLite batch/items ◄──────────── bounded background worker pool
                                      │
                              ffprobe + FFmpeg normalize
                                      │
                         deterministic signal diagnostics
                                      │
                    ┌──── Gemini ephemeral redacted turns ──► local emotion rules
                    │                 (never persisted)
                    └──── Gemini anonymous voice profiles ──► role/overlap fields
                                      │
                   signal/static guards + invariant reconciliation + costing
                                      ▼
                         SQLite results → UI / CSV / JSON
```

## Key choices

The default makes two bounded `gemini-3.1-flash-lite` audio calls. The first produces a redacted role-labelled
transcript that is reconciled locally and immediately discarded. The second returns anonymous per-voice
behavior profiles and the non-emotion fields under a strict compact schema. This recovered the visible
satisfied example and improved overlap without ever sending derived transcript text back to the provider.
The provider remains behind an `InferenceProvider` protocol, so alternatives do not affect intake, jobs,
persistence, or UI.

Audio is converted to 16 kHz mono PCM. This gives Gemini one consistent representation and enables
local signal checks. The checks own technically deterministic facts: long low-energy runs, severe signal
impairment, and repeated loud broadband transients characteristic of sharp static. Semantic tone and ordinary
noise/overlap remain model-assisted.

SQLite plus filesystem objects are deliberate for a single-instance assessment deployment: simple,
inspectable, transactional, and persistent on a VM/Compose volume. The repository and file boundary is
isolated so a multi-instance product can replace these with Postgres and object storage.

The in-process worker keeps the submission self-contained. Each item is independently committed, so one
bad clip does not roll back siblings. For sustained multi-instance production load, replace it with a
managed queue and idempotent worker service.

## Assumptions made explicit

- “Long silence” means at least 10 consecutive seconds below -45 dBFS. The model may also flag semantic
  dead air; local evidence can only change `false` to `true`.
- Customer emotion is requested even when both sides are audible. Low certainty should lower confidence.
- An ephemeral transcript is approved for these assessment recordings and stays inside process memory.
- Noise type is short open text and is empty exactly when noise is absent.
- A browser folder selection can flatten paths; nested folder manifests are rejected to keep name matching
  deterministic.
- Visible labels are a smoke set only. Prompt changes must not overfit three examples.

## Known scaling boundary

The implementation intentionally uses one application instance. A public Cloud Run smoke deployment is
functional but ephemeral; the durable target is a VM with the Compose volume, or a later Postgres/object
storage migration. This boundary is surfaced instead of hidden behind an unsafe SQLite multi-instance
configuration.
