# Technical memo

## Executive summary

The selected system is a two-pass Gemini 3.1 Flash-Lite and deterministic-signal ensemble. One pass creates
an ephemeral, redacted speaker-turn transcript used only by local customer-emotion rules. A second pass
produces anonymous voice profiles plus noise, quality, overlap, and silence fields under a strict schema.
Local PCM analysis owns long silence, severe technical impairment, and a conservative broadband-static
signature.

On the supplied 3.964-minute smoke set, the final pipeline scored **0.609** on the internal assessment-weighted
promotion metric, up from **0.428** for the direct baseline. Exact categorical match increased from 0% to
33.3%. Background-noise presence/type/severity, audio quality, and silence were all 100%; intensity and
overlap were 66.7%. Tone accuracy remained 33.3%, with observed-class macro F1 of 0.333, and is the primary
residual risk.

The final run took 24.12 seconds (0.10x real time). Estimated cost was **$0.002085/audio minute** overall,
and the most expensive individual clip was **$0.002619/audio minute**, both below the $0.003 ceiling.

## Selected architecture

1. FFmpeg normalizes each clip to 16 kHz mono PCM; deterministic acoustic diagnostics are computed locally.
2. Gemini produces a concise role-labelled transcript with identifying values redacted. Only CUSTOMER turns
   are inspected by generic local lexical rules. The transcript is never stored, logged, displayed, or sent
   in another provider request.
3. A separate Gemini call profiles distinct voices using observable service-seeker/provider/background
   behavior and returns the non-emotion fields. Deterministic code selects the service seeker and calibrates
   confidence from role separation.
4. Local rules set long silence, protect technical quality from noise confounds, and detect repeated loud
   high-zero-crossing broadband bursts as sharp static.
5. The exact public Pydantic schema is validated before persistence or export; usage, latency, diagnostics,
   model, prompt version, and estimated cost are retained in the audit envelope.

## Approaches tested

| Candidate | Weighted score | Cost/audio min | Decision |
|---|---:|---:|---|
| Direct Flash-Lite compact classification | 0.428 | $0.000885 | Baseline |
| Continuous latent emotion dimensions | 0.424 | $0.000947 | Rejected; no quality gain |
| Energy-VAD speech compaction | 0.406 | $0.000799 | Rejected; tone regressed |
| Full/compacted dual view | 0.406 | $0.001704 | Rejected; more cost, no gain |
| Ranked customer emotion episodes | 0.349 | $0.000978 | Rejected; role/tone errors |
| Ephemeral transcript + local reconciliation | 0.526 | $0.001989 | Retained emotion component |
| Prosody-tagged transcript | 0.492 | $0.002063 | Rejected in two repeat runs |
| Anonymous speaker profiles, Flash-Lite | 0.379 | $0.001016 | Retained overlap component only |
| Anonymous speaker profiles, Flash Preview | 0.369 | $0.002092 | Rejected; one clip exceeded ceiling |
| Transcript-local + profile ensemble | 0.545 | $0.002085 | Retained |
| Final ensemble + local static detector | **0.609** | **$0.002085** | Selected |

A local quantized Wav2Vec2 speech-emotion candidate was also benchmarked without uploading audio. It heavily
predicted “happy” for both the visible upset and neutral calls, consistent with acted-speech/domain mismatch,
so it was not added to production dependencies. The complete reproducible metric ledger is in
`docs/EXPERIMENTS.md`.

## Validation and leakage prevention

The scorer reports exact match, per-field accuracy, five-class and observed-class emotional macro F1,
per-class precision/recall/F1, confusion, normalized noise-type agreement, confidence MAE, latency, and both
aggregate and maximum per-clip cost. The internal promotion score gives half its weight to tone and distributes
the remainder across the required fields and confidence.

Three examples cannot provide a credible generalization estimate. They were used for bounded component and
architecture selection, not filename-specific calibration. Filenames and supplied JSON are never sent to a
model; no filename or clip-duration lookup appears in prediction code. The broadband detector uses a general
signal signature and has a synthetic regression test rather than a sample-name rule.

## Cost and latency model

Cost uses provider-returned input, output, and thinking-token counts with the pinned Flash-Lite rates. Every
input token is conservatively charged at the audio-input rate. Both provider calls are included. Unknown model
names use deliberately conservative fallback prices so configuration drift cannot silently under-report cost.
The evaluator fails if either the aggregate or any individual clip exceeds $0.003/audio minute.

The measured 24.12-second sequential runtime corresponds to 0.10x real time. Local configuration defaults to
two bounded workers. The hosted assessment intentionally uses one worker because SQLite and a small `e2-small`
VM favor predictable resource use over throughput. Individual media or provider failures are persisted per
item and do not abort valid siblings.

## External API disclosure

Both model passes send the normalized call audio inline to the Gemini Developer API, so audio leaves the
AutoAce-hosted GCP VM and is processed by Google. The application does not use the Gemini Files API, cached
content, grounding, or model training. It never sends filenames or supplied labels to Gemini. The first
response contains an ephemeral redacted transcript that is consumed only by local rules and is not included
in the second provider request.

The cost calculation assumes the paid Gemini 3.1 Flash-Lite rates used during the final run: $0.50 per
million audio-input tokens and $1.50 per million output tokens, including thinking tokens. Provider-reported
token counts drive the per-item estimate; all input tokens are conservatively charged at the audio rate.
Under Google's paid-service terms, prompts, files, and responses are not used to improve Google products,
although Google may retain abuse-monitoring logs for a limited period and transiently cache or process data
in countries where it maintains facilities. See [Security and privacy](SECURITY.md) for the complete data
flow and retention commitment.

## Failure modes and next steps

1. **Tone and role attribution:** collect at least 50–100 independently annotated calls per class, report
   inter-annotator agreement, and evaluate by grouped speaker/call-source splits. Tone is still visibly weak.
2. **Diarization:** consume separated telephony channels when available, or validate a local diarizer on the
   real domain. The supplied stereo files contain duplicate channels, so splitting them adds no information.
3. **Static detector:** validate thresholds on diverse speech, applause, keyboard, and impulsive-noise examples
   before treating its three-call result as a production estimate.
4. **Confidence:** fit temperature or isotonic calibration only after a representative validation set exists.
5. **Scale:** replace SQLite/filesystem state and the in-process worker with Postgres, object storage, and a
   managed queue before running multiple replicas.

See `docs/EVALUATION.md` for the generated report and `docs/ARCHITECTURE.md` for system boundaries.
