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
                         Gemini strict structured output
                                      │
                        invariant reconciliation + costing
                                      ▼
                         SQLite results → UI / CSV / JSON
```

## Key choices

`gemini-3.1-flash-lite` is the default because it was the only tested candidate with non-zero visible-set
emotional macro F1, the assessment's dominant metric. It is a stable GA model, ran faster, and stayed far
below the $0.003/audio-minute requirement. `gemini-3-flash-preview` remains configurable as the stronger
noise/intensity benchmark and is the first candidate to revisit with a larger grouped validation set.
The provider is behind an `InferenceProvider` protocol, so an alternative model does not affect intake,
jobs, persistence, or UI.

Audio is converted to 16 kHz mono PCM. This gives Gemini one consistent representation and enables
local signal checks. The checks own only technically deterministic facts (long low-energy runs and
severe signal impairment); the model owns semantic tone, noise source, and conversational overlap.

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
- Noise type is short open text and is empty exactly when noise is absent.
- A browser folder selection can flatten paths; nested folder manifests are rejected to keep name matching
  deterministic.
- Visible labels are a smoke set only. Prompt changes must not overfit three examples.

## Known scaling boundary

The implementation intentionally uses one application instance. A public Cloud Run smoke deployment is
functional but ephemeral; the durable target is a VM with the Compose volume, or a later Postgres/object
storage migration. This boundary is surfaced instead of hidden behind an unsafe SQLite multi-instance
configuration.
