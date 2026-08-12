# Technical memo

## Executive summary

The final system is a hybrid: Gemini 3.1 Flash-Lite classifies customer emotion and semantic sound
events, while deterministic PCM analysis owns long-silence decisions and guards technical-quality
confounds. The selected implementation processed the 3.964-minute supplied set in 17.37 seconds and cost
an estimated $0.003508 total, or **$0.000885 per audio minute**. Every clip remained below the $0.003/minute
ceiling individually. The web application adds strict validation, partial-failure handling, auditable
results, authentication, and a reproducible container/deployment path.

The visible set is only three calls, so it is not reported as held-out accuracy. Its most important result
is cautionary: five-class emotional-tone macro F1 is 0.133 (0.222 across classes observed in the three
labels), with only the neutral example correct.
That makes emotional calibration the primary residual risk. The submission does not disguise this by
copying supplied labels or adding filename-specific rules.

## Approaches tested

| Candidate | Result on supplied set | Cost / audio min | Decision |
|---|---|---:|---|
| Deterministic PCM baseline | Reliable silence/signal checks; cannot infer semantic emotion/noise source | Local compute only | Retained as guardrail |
| Gemini 3.5 Flash-Lite | Collapsed mostly to neutral/low and missed meaningful noise/overlap | $0.000744 | Rejected on quality |
| Gemini 3 Flash Preview + object JSON | Better noise, overlap, and intensity; verbose output overhead | $0.001923 | Improved |
| Gemini 3.5 Flash + compact tuple | No visible quality gain; two short calls exceeded the ceiling | $0.002797 aggregate | Rejected on per-call cost |
| Gemini 3 Flash Preview + compact tuple + deterministic guards | Stronger noise/intensity fields but zero visible tone macro F1 | $0.001755 | Retained benchmark |
| Gemini 3.1 Flash-Lite + compact tuple + deterministic guards | Only candidate with non-zero visible tone macro F1; GA and fastest | **$0.000885** | Selected |

The provider wire format is a fixed typed nine-value JSON tuple. It maps immediately into the exact named
Pydantic object and is validated there. This saves roughly 75–80 output tokens per clip without changing
the public CSV/JSON schema.

## Validation method and leakage prevention

The reproducible scorer reports per-field accuracy, five-class emotional macro F1, per-class precision/
recall/F1, a tone confusion matrix, normalized noise-type agreement, confidence MAE, cost, and latency.
No cross-validation estimate is credible with one example for each visible tone and likely shared production
conditions. The three labels were used only for bounded prompt/model calibration. Filenames and expected
JSON are never sent to the model, and no filename-specific post-processing exists.

Automated tests cover schema invariants, archive traversal, duplicate/missing/unmatched files, FFmpeg media
normalization, deterministic silence, technical-quality reconciliation, pricing, hashed authentication,
CSRF/login flow, background processing, status polling, and result download. Current non-provider application
coverage is 86%.

## Cost model

Cost is calculated from Gemini's returned prompt, candidate, and thinking-token counts using paid standard
rates: $0.50/M audio-input tokens (conservatively applied to every input token) and $1.50/M output/thinking
tokens for Gemini 3.1 Flash-Lite. The measured final run used no thinking tokens. Applying the audio rate
to text prompt tokens deliberately overestimates cost.

The system records cost per item and batch. Unknown configured models use conservative fallback rates so a
model-name change cannot silently under-report spend. Compact output is essential for short clips, where a
fixed JSON object otherwise dominates cost per minute.

## Latency and production practicality

Final sequential latency was 17.37 seconds total, 5.79 seconds mean per clip, p50 4.09 seconds, p95 10.35
seconds, and 0.073× real time. The dashboard uses two bounded workers by default, so normal batch wall time
is lower while API concurrency remains controlled. One malformed/provider-failed item is recorded and does
not stop siblings.

## Failure modes and next steps

1. **Emotional calibration:** acquire at least 50–100 independently annotated calls per class, measure
   inter-annotator agreement, and tune class thresholds on grouped call/speaker splits. This is the highest
   priority because the three-call smoke set shows systematic adjacent-class and source-attribution errors.
2. **Speaker attribution:** add a diarization/VAD stage or consume separated call channels when available;
   do not infer customer identity from mixed audio alone.
3. **Noise and overlap:** benchmark an AudioSet event detector and a dedicated overlap detector, then ensemble
   only when grouped validation shows a gain within latency/cost limits.
4. **Confidence:** replace the conservative cap with temperature/isotonic calibration once an adequate
   validation set exists.
5. **Scale:** migrate SQLite/filesystem state to Postgres/object storage and the in-process worker to a managed
   queue before enabling multiple application replicas.
6. **Model selection:** re-evaluate the 3.1 Lite/3 Flash tradeoff on the first credible grouped validation
   set; the latter was materially better on noise-related fields despite its weaker three-call tone score.

See `docs/EVALUATION.md` for the generated metrics and `docs/ARCHITECTURE.md` for system boundaries.
