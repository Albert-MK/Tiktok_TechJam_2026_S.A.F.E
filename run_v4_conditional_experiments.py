"""Sequential conditional-profile experiments without environment-variable leakage."""

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
    specs = [
        {
            "name": "profile_generic_only_0.03",
            "flags": {"profile_tag_weight": 0.03, "profile_tags_generic_only": True},
            "method": "Apply profile tags only before a distinctive constraint is known.",
        },
    ]
    for weight in (0.01, 0.02, 0.025, 0.03, 0.035, 0.04, 0.05):
        specs.extend(
            [
                {
                    "name": f"profile_override_only_{weight:g}",
                    "flags": {
                        "profile_tag_weight": weight,
                        "profile_tags_override_only": True,
                    },
                    "method": "Apply weak profile-tag matching only after an intent override.",
                },
                {
                    "name": f"entry_1.1_profile_override_{weight:g}",
                    "flags": {
                        "entry_prefix_weight": 1.1,
                        "profile_tag_weight": weight,
                        "profile_tags_override_only": True,
                    },
                    "method": "Combine entry-prefix evidence with override-only profile matching.",
                },
            ]
        )

    attempts = []
    for spec in specs:
        trial = run_trial(agent, base_config, samples, catalog_pack, spec)
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
    Path("runs/v4_conditional_attempts.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"CHAMPION: {champion['name']} {champion['metrics']}", flush=True)


if __name__ == "__main__":
    main()
