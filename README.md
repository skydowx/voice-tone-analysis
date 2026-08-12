# AutoAce voice-tone and background-noise analyzer

A production-shaped evaluation application for batch analysis of customer-service call audio. It
accepts a ZIP or browser-selected folder containing audio plus `labels.csv`, validates the batch,
processes valid files independently with Gemini structured output, shows progress and per-file errors,
and exports the required `name,result_json` CSV.

## Quick start

Prerequisites: Python 3.10+, `ffmpeg`/`ffprobe`, and a Gemini API key.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
# Add GEMINI_API_KEY and change the local evaluator password in .env
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
- Health/readiness endpoints, non-root container, persistent Compose volume, and deployment script

The generated evaluation report is in [docs/EVALUATION.md](docs/EVALUATION.md), the experiment narrative
is in [docs/TECHNICAL_MEMO.md](docs/TECHNICAL_MEMO.md), and the final supplied-call output is
[artifacts/provided_predictions.csv](artifacts/provided_predictions.csv). Architecture, risks, deployment,
and operational decisions are documented under `docs/`.

## Commands

| Command | Purpose |
|---|---|
| `make test` | Unit and HTTP integration suite with coverage |
| `make run` | Local development server |
| `make live-eval` | Paid Gemini run on labelled clips, then score it |
| `make evaluate` | Re-score existing prediction artifacts without API calls |
| `make docker-up` | Build and launch the persistent local stack |

No audio, credentials, session data, or live inference artifacts are committed. See
[docs/SECURITY.md](docs/SECURITY.md) before a public deployment.
