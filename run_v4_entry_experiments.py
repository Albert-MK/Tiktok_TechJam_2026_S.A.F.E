"""Follow-up experiments for source-entry-aware constraint ranking."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evaluator.local_evaluator import catalog_index, load_jsonl
from run_v4_experiments import BASELINE_SCORE, run_trial, v12_config
from starter.agent import Agent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--weights",
        type=float,
        nargs="+",
        default=[0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 20.0],
    )
    parser.add_argument("--output", default="runs/v4_entry_attempts.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog_path = "data/catalog.jsonl"
    samples = load_jsonl("data/public_set.jsonl")
    catalog_pack = catalog_index(catalog_path)
    agent = Agent(catalog_path)
    base_config = v12_config(agent.cfg)
    attempts = []

    for weight in args.weights:
        trial = run_trial(
            agent,
            base_config,
            samples,
            catalog_pack,
            {
                "name": f"entry_prefix_weight_{weight:g}",
                "flags": {"entry_prefix_weight": weight},
                "method": (
                    "Reward constraints matching the prefix of an original features/details "
                    "entry, with a mild prior for earlier entries."
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
    out_path = Path(args.output)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"CHAMPION: {champion['name']} {champion['metrics']}", flush=True)


if __name__ == "__main__":
    main()
