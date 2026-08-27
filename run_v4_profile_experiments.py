"""Evaluate weak, explainable preference-tag personalization."""

from __future__ import annotations

import json
from pathlib import Path

from evaluator.local_evaluator import catalog_index, load_jsonl
from run_v4_experiments import BASELINE_SCORE, run_trial, v12_config
from starter.agent import Agent


def main() -> None:
    catalog_path = "data/catalog.jsonl"
    samples = load_jsonl("data/public_set.jsonl")
    catalog_pack = catalog_index(catalog_path)
    agent = Agent(catalog_path)
    base_config = v12_config(agent.cfg)
    attempts = []

    for weight in (0.01, 0.03, 0.05, 0.1, 0.2, 0.5):
        trial = run_trial(
            agent,
            base_config,
            samples,
            catalog_pack,
            {
                "name": f"profile_tag_weight_{weight:g}",
                "flags": {"profile_tag_weight": weight},
                "method": (
                    "Use aggregate preference tags only as a weak tie-break when their "
                    "tokens occur in candidate metadata."
                ),
            },
        )
        attempts.append(trial)
        print(
            f"{trial['name']}: {trial['metrics']['recommended_technical_score']:.6f} "
            f"({trial['delta_vs_v12']:+.6f})",
            flush=True,
        )

    champion = max(
        attempts,
        key=lambda trial: trial["metrics"]["recommended_technical_score"],
    )
    payload = {
        "dataset": "data/public_set.jsonl",
        "baseline_score": BASELINE_SCORE,
        "champion": champion,
        "attempts": attempts,
    }
    Path("runs/v4_profile_attempts.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"CHAMPION: {champion['name']} {champion['metrics']}", flush=True)


if __name__ == "__main__":
    main()
