"""Run strategy ablations against the official public-set scorer."""

from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl


STRATEGIES = [
    "ask_other_first",
    "hybrid_typed",
    "hybrid_other_keep",
    "hybrid_other_profile",
    "hybrid_other_keep_wide",
]


def run_strategy(name: str, samples: list[dict], catalog_path: str, catalog_pack: tuple) -> dict:
    os.environ["AGENT_STRATEGY"] = name
    import starter.config as config_mod
    import starter.agent as agent_mod

    importlib.reload(config_mod)
    importlib.reload(agent_mod)
    catalog_ids, categories, products = catalog_pack
    result = evaluate(agent_mod.Agent(catalog_path), samples, catalog_ids, categories, products)
    summary = {key: value for key, value in result.items() if key != "sessions"}
    summary["strategy"] = name
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", default="runs/ablation_results.json")
    parser.add_argument("--strategies", default=",".join(STRATEGIES))
    args = parser.parse_args()

    samples = load_jsonl(args.dataset)
    if args.limit:
        samples = samples[: args.limit]
    catalog_pack = catalog_index(args.catalog)
    names = [item.strip() for item in args.strategies.split(",") if item.strip()]
    results = []
    for name in names:
        print(f"\n=== strategy={name} samples={len(samples)} ===", flush=True)
        summary = run_strategy(name, samples, args.catalog, catalog_pack)
        print(json.dumps(summary, indent=2), flush=True)
        results.append(summary)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {output}")


if __name__ == "__main__":
    main()
