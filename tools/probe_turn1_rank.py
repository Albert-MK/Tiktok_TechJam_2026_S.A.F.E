"""Diagnose turn-1 ranking quality: is the top candidate the true target?

MRR is already 1.0, so the only remaining score lever is how often the belief's
rank-1 candidate is correct at each turn. This isolates turn 1 without paying for
a full 200-session evaluation, and compares weight variants side by side.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import coarse_category, initial_message, materialize_hidden_fields  # noqa: E402


def main() -> None:
    from starter import belief as belief_mod
    from starter.belief import Belief
    from starter.catalog_index import CatalogIndex

    index = CatalogIndex(str(ROOT / "data" / "catalog.jsonl"))
    pid_of = {asin: pid for pid, asin in enumerate(index.asins)}

    catalog_cats, products = {}, {}
    with (ROOT / "data" / "catalog.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            p = json.loads(line)
            a = str(p["parent_asin"])
            products[a] = p
            catalog_cats[a] = [str(v) for v in p.get("categories") or []]

    samples = [json.loads(l) for l in (ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") if l.strip()]

    variants = {
        "current      (cat=26 graded, order=0.85)": dict(W_CATEGORY=26.0, W_CATEGORY_FLAT=0.0, ORDER_DISCOUNT=0.85),
        "flat cat 20  (order=0.85)":                dict(W_CATEGORY=14.0, W_CATEGORY_FLAT=20.0, ORDER_DISCOUNT=0.85),
        "flat cat 20  (order=0.45)":                dict(W_CATEGORY=14.0, W_CATEGORY_FLAT=20.0, ORDER_DISCOUNT=0.45),
        "flat cat 20  (order=0.20)":                dict(W_CATEGORY=14.0, W_CATEGORY_FLAT=20.0, ORDER_DISCOUNT=0.20),
    }

    for name, weights in variants.items():
        for key, value in weights.items():
            setattr(belief_mod, key, value)
        ranks_by_scenario: dict[str, list[int]] = {}
        for sample in samples:
            target = str(sample["ground_truth"]["parent_asin"])
            card, behavior = materialize_hidden_fields(sample, products)
            eff = {**sample, "intent_card": card, "behavior": behavior}
            message = initial_message(eff, coarse_category(catalog_cats.get(target, [])), set())

            state = Belief(index)
            state.observe_opening(message)
            pids, _probs, _leak = state.posterior()
            try:
                rank = pids.index(pid_of[target]) + 1
            except ValueError:
                rank = 10_000
            ranks_by_scenario.setdefault(sample["scenario_type"], []).append(rank)

        allr = [r for rs in ranks_by_scenario.values() for r in rs]
        top1 = sum(1 for r in allr if r == 1) / len(allr)
        missing = sum(1 for r in allr if r == 10_000)
        print(f"{name:42s} top1={top1:6.2%} inPool={1-missing/len(allr):6.2%} "
              f"medRank={statistics.median(allr):.0f}")
        for scenario in sorted(ranks_by_scenario):
            rs = ranks_by_scenario[scenario]
            print(f"      {scenario:16s} top1={sum(1 for r in rs if r == 1)/len(rs):6.2%}  n={len(rs)}")


if __name__ == "__main__":
    main()
