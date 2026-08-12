# Experiment ledger

The quality score is an internal promotion metric for this three-call smoke set. Half of its weight is
emotional tone (accuracy and observed-class macro F1); the balance covers the other required fields and
confidence. It is useful for direction, not a hidden-set estimate.

| Experiment | Model | Weighted quality | Tone accuracy | Tone macro F1 | Cost/audio min | Real-time factor | Decision |
|---|---|---:|---:|---:|---:|---:|---|
| baseline_direct | gemini-3.1-flash-lite | 0.428 | 33.3% | 0.222 | $0.000885 | 0.073 | not selected |
| latent_v1 | gemini-3.1-flash-lite | 0.424 | 33.3% | 0.167 | $0.000947 | 0.071 | not selected |
| speech_compact_v1 | gemini-3.1-flash-lite | 0.406 | 0.0% | 0.000 | $0.000799 | 0.060 | not selected |
| dual_view_v1 | gemini-3.1-flash-lite | 0.406 | 0.0% | 0.000 | $0.001704 | 0.106 | not selected |
| episodes_v1 | gemini-3.1-flash-lite | 0.349 | 0.0% | 0.000 | $0.000978 | 0.053 | not selected |
| transcript_local_v1 | gemini-3.1-flash-lite | 0.526 | 33.3% | 0.333 | $0.001989 | 0.120 | not selected |
| transcript_local_tagged_v1 | gemini-3.1-flash-lite | 0.492 | 33.3% | 0.333 | $0.002063 | 0.124 | not selected |
| transcript_local_tagged_v2 | gemini-3.1-flash-lite | 0.492 | 33.3% | 0.333 | $0.002063 | 0.095 | not selected |
| speaker_profiles_v1 | gemini-3.1-flash-lite | 0.379 | 0.0% | 0.000 | $0.001016 | 0.056 | not selected |
| speaker_profiles_flash_v1 | gemini-3-flash-preview | 0.369 | 0.0% | 0.000 | $0.002092 | 0.058 | not selected |
| transcript_local_profiles_v1 | gemini-3.1-flash-lite | 0.545 | 33.3% | 0.333 | $0.002085 | 0.097 | not selected |
| final_v7 | gemini-3.1-flash-lite+gemini-3.1-flash-lite | 0.609 | 33.3% | 0.333 | $0.002085 | 0.101 | current best |

### baseline_direct

Direct whole-call compact classification with Gemini 3.1 Flash-Lite plus deterministic silence/quality reconciliation.

### latent_v1

Single-pass latent customer emotion evidence (valence/arousal/satisfaction/frustration/anger/distress/role certainty) mapped deterministically to assessment enums.

### speech_compact_v1

Energy-VAD speech-focused audio view with 300 ms context, 500 ms gap bridging, and full-audio deterministic quality/silence guards.

### dual_view_v1

Cost-gated two-view ensemble: full audio supplies customer tone; speech-focused audio supplies intensity/noise/overlap; deterministic full-audio signal guards own silence and quality.

### episodes_v1

Single-pass internal diarization with ranked customer-only emotional episodes; deterministic salience aggregation; no transcript or call words returned.

### transcript_local_v1

Gemini returns an ephemeral redacted role-labelled transcript; a local-only generic service-call lexicon reconciles CUSTOMER emotion; transcript is never persisted, logged, or sent back.

### transcript_local_tagged_v1

Ephemeral role-labelled transcript with local-only lexical and per-turn prosody reconciliation; transcript is never persisted or sent back to the provider

### transcript_local_tagged_v2

Repeat tagged-transcript run with privacy-safe aggregate evidence diagnostics to assess variance

### speaker_profiles_v1

Single-pass distinct-voice profiles with deterministic service-seeker selection; no transcript generated

### speaker_profiles_flash_v1

Speaker-profile decomposition on Gemini 3 Flash Preview; rejected if any clip exceeds cost ceiling

### transcript_local_profiles_v1

Two-pass Lite ensemble: ephemeral role-labelled transcript for local-only emotion reconciliation plus anonymous speaker profiles for non-emotion fields

### final_v7

Promoted two-pass Flash-Lite ensemble with ephemeral local-only transcript reconciliation, anonymous speaker profiles, calibrated single-profile confidence, and deterministic broadband-static detection
