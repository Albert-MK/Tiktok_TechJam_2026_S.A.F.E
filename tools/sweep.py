"""Parameter sweep that builds the 50k catalog index once and reuses it.

Usage:
    python tools/sweep.py                  # calibration sweep on the public set
    python tools/sweep.py --dataset data/customer_probe.jsonl
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import catalog_index, evaluate  # noqa: E402
from starter import belief as belief_mod  # noqa: E402
from starter.agent import Agent  # noqa: E402
from starter.catalog_index import CatalogIndex  # noqa: E402
from starter.config import PRESETS  # noqa: E402

BELIEF_KEYS = {
    "W_CONSTRAINT", "W_REPLY", "W_SILENT", "W_CATEGORY", "W_CATEGORY_FLAT",
    "W_NONE", "ORDER_DISCOUNT", "CONTAINMENT_SIM", "COVERAGE_CAP",
    "LEXICAL_RESCUE_PENALTY", "BROWSING_PRIOR_MATCH",
}


def run(index, samples, catalog_ids, categories, products, overrides: dict) -> dict:
    defaults = {key: getattr(belief_mod, key) for key in BELIEF_KEYS}
    cfg = dict(PRESETS["bayes"])
    for key, value in overrides.items():
        if key in BELIEF_KEYS:
            setattr(belief_mod, key, value)
        else:
            cfg[key] = value
    try:
        agent = Agent(index=index, config=cfg)
        return evaluate(agent, samples, catalog_ids, categories, products)
    finally:
        for key, value in defaults.items():
            setattr(belief_mod, key, value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default=str(ROOT / "data" / "catalog.jsonl"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "public_set.jsonl"))
    args = parser.parse_args()

    print("building index ...", flush=True)
    started = time.time()
    index = CatalogIndex(args.catalog)
    catalog_ids, categories, products = catalog_index(args.catalog)
    samples = [json.loads(l) for l in Path(args.dataset).open(encoding="utf-8") if l.strip()]
    print(f"  ready in {time.time()-started:.1f}s  ({len(index)} products, {len(samples)} sessions)\n")

    variants: list[tuple[str, dict]] = [
        ("baseline", {}),
        ("temp=0.5", {"temperature": 0.5}),
        ("temp=2", {"temperature": 2.0}),
        ("temp=4", {"temperature": 4.0}),
        ("temp=8", {"temperature": 8.0}),
        ("leak=5", {"leak_gap": 5.0}),
        ("leak=14", {"leak_gap": 14.0}),
        ("pool=1200", {"pool_size": 1200}),
        ("order=0.85", {"ORDER_DISCOUNT": 0.85}),
        ("no-elimination", {"eliminate": False}),
        ("batch top-10", {"sequential": False}),
    ]

    print(f"{'variant':18s} {'score':>8s} {'hit':>6s} {'mrr':>7s} {'mttc':>6s}   per-scenario mttc")
    for name, overrides in variants:
        started = time.time()
        result = run(index, copy.deepcopy(samples), catalog_ids, categories, products, overrides)
        per = {k: round(v["mttc"], 3) for k, v in result["scenario_metrics"].items()}
        print(f"{name:18s} {result['recommended_technical_score']:8.4f} "
              f"{result['hit_rate_at_10']:6.3f} {result['mrr']:7.4f} {result['mttc']:6.3f}   {per}"
              f"  [{time.time()-started:.0f}s]", flush=True)


if __name__ == "__main__":
    main()
