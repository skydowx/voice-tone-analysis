#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path


source = Path("artifacts/experiments.json")
target = Path("docs/EXPERIMENTS.md")
items = json.loads(source.read_text(encoding="utf-8")) if source.exists() else []
rows = "\n".join(
    "| {id} | {scope} | {model} | {score} | {tone:.1%} | {f1:.3f} | ${cost:.6f} | {rtf:.3f} | {decision} |".format(
        id=item["id"],
        scope=item.get("scope", "full schema").replace("_", " "),
        model=item["model"],
        score=(
            f"{item['assessment_quality_score']:.3f}"
            if item.get("assessment_quality_score") is not None
            else "—"
        ),
        tone=item["tone_accuracy"],
        f1=item["tone_macro_f1_observed"],
        cost=item["cost_per_audio_minute_usd"],
        rtf=item["real_time_factor"],
        decision=item.get("decision", "historical candidate"),
    )
    for item in items
)
details = "\n\n".join(f"### {item['id']}\n\n{item['description']}" for item in items)
target.write_text(
    f"""# Experiment ledger

The quality score is an internal promotion metric for this three-call smoke set. Half of its weight is
emotional tone (accuracy and observed-class macro F1); the balance covers the other required fields and
confidence. It is useful for direction, not a hidden-set estimate.

| Experiment | Scope | Model | Weighted quality | Tone accuracy | Tone macro F1 | Cost/audio min | Real-time factor | Decision |
|---|---|---|---:|---:|---:|---:|---:|---|
{rows}

{details}
""",
    encoding="utf-8",
)
