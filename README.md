# AutoAce voice-tone and background-noise analyzer

A production-shaped evaluation application for batch analysis of customer-service call audio. It
accepts a ZIP or browser-selected folder containing audio plus `labels.csv`, validates the batch,
processes valid files independently with a hybrid Gemini/local pipeline, shows progress and per-file errors,
shows expected-versus-predicted matches and batch metrics when labels are supplied, and exports the required
`name,result_json` CSV. Unlabelled hidden batches do not show an evaluation panel.

## Live assessment

The reviewer deployment is available at <https://autoace.omerkhalil.com>. Sign in as `evaluator`; the
password is shared out of band and is never committed. A concise reviewer walkthrough and the evidence
map for every requested deliverable are in [docs/SUBMISSION.md](docs/SUBMISSION.md).

## Quick start

Prerequisites: Python 3.10+, `ffmpeg`/`ffprobe`, and a Gemini API key.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
# Add GEMINI_API_KEY, optionally add POSTHOG_PROJECT_TOKEN, and change the local evaluator password in .env
make test
make run
```

Open <http://127.0.0.1:8080>. The default local username is `evaluator`; the password is read from
`.env`. To exercise the supplied examples and regenerate the benchmark:

```bash
make live-eval
```

Docker is equally direct: `docker compose up --build`. The named volume preserves evaluation state.

## Input contract

The ZIP or selected folder must have `labels.csv` and audio files at its root. The manifest requires a
`name` column and may contain `result_json`; populated labels are validated against the same strict
schema used for predictions. Supported formats are OGG/Opus, WAV, MP3, AAC, FLAC, M4A, MP4, and WebM.

Every prediction contains exactly:

```json
{
  "emotional_tone": "neutral|satisfied|frustrated|upset|distressed",
  "emotional_intensity": "low|medium|high",
  "background_noise_present": false,
  "background_noise_type": "",
  "background_noise_severity": "none|low|medium|high",
  "audio_quality": "clear|slightly_impaired|severely_impaired",
  "speaker_overlap_present": false,
  "long_silence_present": false,
  "confidence": 0.82
}
```

## What is production-shaped

- Strict Pydantic response contract and cross-field invariants
- Safe streaming uploads, archive traversal/symlink/zip-bomb defenses, and `ffprobe` media validation
- FFmpeg normalization to deterministic 16 kHz mono PCM
- Independent per-file failures, bounded concurrency, durable SQLite job/result records, and restart recovery
- Authenticated evaluator UI, signed `HttpOnly` session cookies, CSRF tokens, login throttling, host checking,
  secure-cookie production guardrails, and optional PBKDF2 password hashes
- Model/prompt version, measured duration/latency/token usage/cost, deterministic signal diagnostics, and
  downloadable CSV/JSON audit artifacts
- Ephemeral redacted speaker-turn transcription for conservative customer-emotion reconciliation; weak
  issue words cannot override the assessment's exact primary-tone definitions, and transcript
  text is never persisted, logged, displayed, or sent in a follow-up provider request
- Anonymous per-voice behavior profiles for overlap and role confidence, plus local silence, signal-quality,
  and broadband-static detectors
- Health/readiness endpoints, non-root container, persistent Compose volume, and deployment script
- Optional privacy-limited PostHog deployment and batch telemetry with no browser capture or call content

The generated evaluation report is in [docs/EVALUATION.md](docs/EVALUATION.md), the full experiment ledger
is in [docs/EXPERIMENTS.md](docs/EXPERIMENTS.md), the experiment narrative is in
[docs/TECHNICAL_MEMO.md](docs/TECHNICAL_MEMO.md), and the final supplied-call output is
[artifacts/provided_predictions.csv](artifacts/provided_predictions.csv), with its redacted reproducibility
record in [artifacts/provided_audit.json](artifacts/provided_audit.json). Architecture, risks, deployment,
and operational decisions are documented under `docs/`. The sample is only three calls, so its metrics are
reported as smoke evidence rather than a generalization claim.

The PostHog event and privacy contract is documented in [docs/ANALYTICS.md](docs/ANALYTICS.md).

## Commands

| Command | Purpose |
|---|---|
| `make test` | Unit and HTTP integration suite with coverage |
| `make run` | Local development server |
| `make live-eval` | Paid Gemini run on labelled clips, then score it |
| `make evaluate` | Re-score existing prediction artifacts without API calls |
| `make docker-up` | Build and launch the persistent local stack |

The materially different OSS tone challenger is isolated from production dependencies. Reproduce it with
`uv` and the CPU-only PyTorch index:

```bash
UV_CACHE_DIR=/tmp/autoace-uv-cache uv venv .venv-oss --python python3
UV_CACHE_DIR=/tmp/autoace-uv-cache uv pip install --python .venv-oss/bin/python \
  --index https://download.pytorch.org/whl/cpu torch==2.11.0 torchaudio==2.11.0
UV_CACHE_DIR=/tmp/autoace-uv-cache uv pip install --python .venv-oss/bin/python \
  -r requirements-oss-eval.txt
HF_HUB_DOWNLOAD_TIMEOUT=300 .venv-oss/bin/python scripts/evaluate_oss_emotion.py
```

No audio, credentials, session data, or live inference artifacts are committed. See
[docs/SECURITY.md](docs/SECURITY.md) before a public deployment.
