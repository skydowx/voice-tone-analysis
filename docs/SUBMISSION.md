# Assessment submission guide

## Reviewer access

- Application: <https://autoace.omerkhalil.com>
- Username: `evaluator`
- Password: shared out of band; retrieve it with the command below if you operate the GCP project.

```bash
gcloud secrets versions access latest \
  --secret autoace-evaluator-password \
  --project autoace-assessment
```

The GitHub repository is private. Grant the named reviewers read access before sending this submission.

## Five-minute walkthrough

1. Sign in and upload a ZIP or select a folder whose root contains `labels.csv` and its referenced audio.
2. Confirm the preflight summary, then start the batch. Valid files proceed independently; invalid entries
   show actionable errors without aborting valid siblings.
3. Watch item-level progress, prediction fields, latency, cost, model/prompt version, and diagnostics. For a
   labelled manifest, review expected-versus-predicted badges, tone accuracy/macro F1, exact match,
   confidence error, and the tone confusion matrix. These controls stay hidden for unlabelled batches.
4. Download the required `name,result_json` CSV. JSON audit artifacts are also available.
5. Compare the generated evaluation report and reproducible prediction artifact linked below.

## Requirement evidence

| Requested outcome | Evidence |
|---|---|
| Hosted, login-protected dashboard | Live URL above; authentication/session controls in `app/security.py` |
| Runnable repository and setup | `README.md`, `.env.example`, `Makefile`, `Dockerfile`, Compose files |
| Folder/ZIP batch input and manifest validation | `app/services/batch_validation.py`, upload integration tests |
| Progress, label comparison, independent errors, and download | `app/routes/batches.py`, templates, shared evaluator, processor and route tests |
| Exact prediction contract | `app/schemas/prediction.py`; CSV sample in `artifacts/provided_predictions.csv` |
| Technical memo and architecture | `docs/TECHNICAL_MEMO.md`, `docs/ARCHITECTURE.md` |
| Validation metrics and confusion | `docs/EVALUATION.md`, `artifacts/evaluation.json`, `artifacts/provided_audit.json` |
| Cost below $0.003/audio minute | $0.002109/min aggregate; $0.002680/min worst clip in the selected v9 run |
| Measured latency | 129.17 seconds for 3.964 audio minutes (0.54x real time; one 88.59s provider outlier) |
| Failure modes and next steps | `docs/TECHNICAL_MEMO.md`, `docs/EXPERIMENTS.md` |
| Paid API/privacy disclosure | `docs/SECURITY.md` and the memo's external API section |

## Validation caveat

The supplied set contains only three labelled calls. The spec-correct production candidate scores 0.549 on
the documented internal weighted metric, with 33.3% tone accuracy and observed-class macro F1 of 0.333. A
historical v7 run scored 0.609, but depended on an ambiguous salient-emotion instruction and weak lexical
overrides, so it was superseded rather than promoted from n=3. These are transparent smoke results, not a
production estimate. The most valuable next input is a larger, independently labelled,
speaker-grouped validation set; the submission asks for additional examples instead of tuning further to the
three visible calls.

## Data handling

Each call is transmitted twice, inline, to the Gemini Developer API: once for ephemeral redacted turns and
once for anonymous speaker/noise profiles. Audio leaves the hosted VM. Filenames and labels do not. The app
does not use the Files API and does not persist transcript text. Full provider terms, price assumptions, and
the seven-day post-review deletion commitment are in [Security and privacy](SECURITY.md).

## Suggested submission email

> Subject: AutoAce software engineer assessment submission
>
> Hi — the assessment is ready for review.
>
> Live app: https://autoace.omerkhalil.com<br>
> Username: evaluator<br>
> Password: [insert the separately retrieved evaluator password]<br>
> Repository: https://github.com/skydowx/voice-tone-analysis
>
> The repository includes setup instructions, the technical memo, reproducible evaluation artifacts, cost and
> latency measurements, and the external-API/privacy disclosure. The supplied three-call set is useful as a
> smoke test but too small for a trustworthy generalization estimate: the selected spec-correct run scores
> 0.549, a historical run scored 0.609, and tone remains the main risk. A pinned local emotion2vec+ challenger
> was also measured and rejected because it predicted neutral for all three calls and cannot isolate the
> customer. If you can share additional independently labelled examples—ideally covering
> all tone classes, speakers, channels, and noise conditions—I would use them as a held-out evaluation set
> rather than tune against the visible three calls.
>
> Please let me know when review is complete; uploaded assessment data will be deleted no later than seven
> days after that confirmation.
>
> Thanks,
> Omer
