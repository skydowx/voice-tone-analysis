# Technical memo

## Executive summary

The selected system is a two-pass Gemini 3.1 Flash-Lite and deterministic-signal ensemble. One pass creates
an ephemeral, redacted speaker-turn transcript used for conservative customer-emotion reconciliation. A
second pass produces anonymous voice profiles plus noise, quality, overlap, and silence fields under a strict
schema. Local PCM analysis owns long silence, severe technical impairment, and a conservative broadband-static
signature.

The prompt now uses the assessment's definition of “primary emotional tone expressed by the customer”
verbatim. Earlier code incorrectly preferred a “clearest salient” emotion and allowed weak issue words such as
“problem,” “still,” and “again” to influence tone. Those shortcuts were removed. Only explicit expressions
taken directly from a class definition can reconcile an untagged CUSTOMER turn; generic problem descriptions
cannot.

The spec-correct v9 run scored **0.549** on the internal assessment-weighted smoke metric, with 33.3% tone
accuracy and 0.333 observed-class macro F1. It took 129.17 seconds (0.54x real time), including one 88.59-second
provider outlier. Estimated cost was **$0.002109/audio minute** overall and **$0.002680/audio minute** for the
most expensive clip, both below the $0.003 ceiling. The historical v7 artifact scored 0.609, but it was not
retained as production behavior because its tone contract and weak lexical overrides were not faithful to the
rubric. With n=3, that difference is not evidence for keeping the less defensible rules.

## Selected architecture

1. FFmpeg normalizes each clip to 16 kHz mono PCM; deterministic acoustic diagnostics are computed locally.
2. Gemini produces a concise role-labelled transcript with identifying values redacted. Only CUSTOMER turns
   are inspected. Generic issue words never alter tone; only explicit definition-level expressions can
   reconcile the audio profile. The transcript is never stored, logged, displayed, or sent in another request.
3. A separate Gemini call profiles distinct voices using observable service-seeker/provider/background
   behavior and returns environmental fields. Deterministic code selects the service seeker and calibrates
   confidence from role separation.
4. Local rules set long silence, protect technical quality from noise confounds, and detect repeated loud
   high-zero-crossing broadband bursts as sharp static.
5. The exact public Pydantic schema is validated before persistence or export; usage, latency, diagnostics,
   model, prompt version, and estimated cost are retained in the audit envelope.

Gemini remains selected because its official documentation describes
[`gemini-3.1-flash-lite`](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite) as a low-latency,
cost-oriented model supporting audio input and structured output, while the API's
[audio guide](https://ai.google.dev/gemini-api/docs/audio) explicitly covers transcription, diarization,
emotion detection, and non-speech sound understanding. More importantly, it is the only tested approach here
that covers the complete schema and customer role in one operational pipeline under the cost ceiling. This is
a pragmatic selection, not a claim that its current tone accuracy is sufficient.

## Approaches tested

| Candidate | Weighted score | Cost/audio min | Decision |
|---|---:|---:|---|
| Direct Flash-Lite compact classification | 0.428 | $0.000885 | Baseline |
| Continuous latent emotion dimensions | 0.424 | $0.000947 | Rejected; no quality gain |
| Energy-VAD speech compaction | 0.406 | $0.000799 | Rejected; tone regressed |
| Full/compacted dual view | 0.406 | $0.001704 | Rejected; more cost, no gain |
| Ranked customer emotion episodes | 0.349 | $0.000978 | Rejected; role/tone errors |
| Ephemeral transcript + local reconciliation | 0.526 | $0.001989 | Retained component |
| Prosody-tagged transcript | 0.492 | $0.002063 | Rejected in two repeat runs |
| Anonymous speaker profiles, Flash-Lite | 0.379 | $0.001016 | Retained component |
| Anonymous speaker profiles, Flash Preview | 0.369 | $0.002092 | Rejected; one clip exceeded ceiling |
| Transcript-local + profile ensemble | 0.545 | $0.002085 | Retained |
| Historical v7 + local static detector | **0.609** | **$0.002085** | Visible-set best; superseded |
| Dedicated spec-defined emotion pass (v8) | 0.349 | $0.001919 | Rejected; tone fell to 0% |
| Spec-defined conservative reconciliation (v9) | 0.549 | $0.002109 | Selected for rubric fidelity |

A materially different local challenger used the pinned
[`emotion2vec_plus_base`](https://huggingface.co/emotion2vec/emotion2vec_plus_base) checkpoint at revision
`b318240bfe67db81a8c572ecb37ce9c3759b81c9`. Its nine native SER labels were mapped to the five assessment
tones before the run; non-overlapping 30-second chunks were duration-weighted. It predicted neutral for all
three calls: 33.3% tone accuracy and 0.167 observed-class macro F1, versus 33.3% and 0.333 for v9. CPU inference
took 41.72 seconds (0.18x real time) after model load. It was rejected because whole-call SER cannot isolate
the customer, it missed upset and satisfied, it implements no other required fields, and the checkpoint's
custom license needs production review. An initial unchunked attempt on the 172-second call caused heavy CPU
memory/swap pressure and was aborted; fixed 30-second chunks made the comparison operationally bounded.

The OSS script, pinned dependencies, raw probabilities, predetermined label mapping, model revision, and
runtime versions are committed in `scripts/evaluate_oss_emotion.py`, `requirements-oss-eval.txt`, and
`artifacts/oss_emotion2vec_evaluation.json`. The complete experiment history is in `docs/EXPERIMENTS.md`.

## Validation and leakage prevention

The shared evaluator reports exact match, per-field accuracy, five-class and observed-class emotional macro
F1, per-class precision/recall/F1, confusion, normalized noise-type agreement, confidence MAE, latency, and
aggregate and maximum per-clip cost. The dashboard uses this same implementation, so online label comparisons
cannot drift from the offline report. The smoke score gives half its weight to tone and distributes the rest
across required fields and confidence.

Three examples cannot provide a credible generalization estimate. They were used for bounded component and
architecture decisions, not filename-specific calibration. Filenames and supplied JSON are never sent to a
model; no filename or clip-duration lookup appears in prediction code. The OSS mapping and v8 experiment were
declared before results were read. The broadband detector uses a general signal signature and a synthetic
regression test rather than a sample-name rule.

## Cost and latency model

Cost uses provider-returned input, output, and thinking-token counts with pinned Flash-Lite rates. Every input
token is conservatively charged at the audio-input rate, and both calls are included. Unknown model names use
conservative fallback prices. Evaluation fails if either aggregate or any per-clip cost exceeds $0.003/audio
minute.

The selected v9 run's 129.17-second sequential runtime corresponds to 0.54x real time; its median clip latency
was 23.25 seconds. Local configuration defaults to two bounded workers. The hosted assessment uses one worker
because SQLite and a small `e2-small` VM favor predictable resource use. Individual media or provider failures
are persisted per item and do not abort valid siblings.

## External API disclosure

Both model passes send normalized call audio inline to the Gemini Developer API, so audio leaves the
AutoAce-hosted GCP VM and is processed by Google. The application does not use the Gemini Files API, cached
content, grounding, or training. It never sends filenames or supplied labels. The first response contains an
ephemeral redacted transcript consumed only by local rules and never included in the second request.

The cost model assumes $0.50 per million audio-input tokens and $1.50 per million output tokens, including
thinking tokens. Under Google's paid-service terms, prompts, files, and responses are not used to improve
Google products, although limited abuse-monitoring retention and international processing may apply. See
[Security and privacy](SECURITY.md) for the complete data flow and retention commitment.

## Failure modes and next steps

1. **Tone and role attribution:** collect at least 50–100 independently annotated calls per class, report
   inter-annotator agreement, and evaluate by grouped speaker/call-source splits. Tone remains visibly weak.
2. **Diarization:** consume separated telephony channels when available, or validate a local diarizer on the
   real domain. The supplied stereo files contain duplicate channels, so splitting them adds no information.
3. **Static detector:** validate thresholds on diverse speech, applause, keyboard, and impulsive-noise examples.
4. **Confidence:** fit temperature or isotonic calibration only after a representative validation set exists.
5. **Scale:** replace SQLite/filesystem state and the in-process worker with Postgres, object storage, and a
   managed queue before running multiple replicas.

See `docs/EVALUATION.md` for the historical best visible-set report and `docs/EXPERIMENTS.md` for v8, v9, and
OSS comparisons.
