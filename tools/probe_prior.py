"""Quantify the Bayesian prior P(target = p) and per-turn achievable rank.

Hypothesis: targets are sampled from real Amazon review records, so
P(p) is proportional to rating_number(p). Combined with the deterministic
inverse-simulator filter, this should place the target at rank 1 very early.
"""
from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import coarse_category, intent_card  # noqa: E402


def load():
    products, cards, cats = {}, {}, {}
    with (ROOT / "data" / "catalog.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            p = json.loads(line)
            a = str(p["parent_asin"])
            products[a] = p
            cards[a] = intent_card(p)
            cats[a] = coarse_category([str(v) for v in p.get("categories") or []])
    samples = [json.loads(l) for l in (ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") if l.strip()]
    return products, cards, cats, samples


def rank_stats(name, ranks):
    n = len(ranks)
    mrr = statistics.fmean(1.0 / r if r else 0.0 for r in ranks)
    hit = sum(1 for r in ranks if r and r <= 10) / n
    top1 = sum(1 for r in ranks if r == 1) / n
    print(f"{name:44s} top1={top1:6.2%} hit@10={hit:6.2%} MRR={mrr:.4f}")


def main() -> None:
    products, cards, cats, samples = load()

    by_cat = defaultdict(list)
    for a, c in cats.items():
        by_cat[c].append(a)

    def prior(a: str, alpha: float) -> float:
        rn = float(products[a].get("rating_number") or 0)
        ar = float(products[a].get("average_rating") or 0)
        return (rn + 1.0) ** alpha * (1.0 + 0.05 * ar)

    # Sweep the popularity exponent to see how well prior ~ rating_number^alpha fits.
    print("=== turn-1 browsing: coarse category only, ranked by popularity prior ===")
    for alpha in (0.0, 0.25, 0.5, 0.75, 1.0, 1.5):
        ranks = []
        for s in samples:
            t = str(s["ground_truth"]["parent_asin"])
            pool = sorted(by_cat[cats[t]], key=lambda a: prior(a, alpha), reverse=True)
            ranks.append(pool.index(t) + 1)
        rank_stats(f"  alpha={alpha}", ranks)

    alpha = 1.0
    print("\n=== progressive constraint disclosure, popularity-ordered ===")

    def filtered_rank(target: str, needles: list[str]) -> int:
        pool = []
        for a in by_cat[cats[target]]:
            card = cards[a]
            allc = [str(v) for v in card["hard_constraints"]] + [str(v) for v in card["soft_preferences"]]
            if all(n in allc for n in needles):
                pool.append(a)
        pool.sort(key=lambda a: prior(a, alpha), reverse=True)
        return pool.index(target) + 1

    for k in range(0, 5):
        ranks = []
        for s in samples:
            t = str(s["ground_truth"]["parent_asin"])
            card = cards[t]
            allc = [str(v) for v in card["hard_constraints"]] + [str(v) for v in card["soft_preferences"]]
            ranks.append(filtered_rank(t, allc[:k]))
        rank_stats(f"  category + first {k} constraints", ranks)

    # What fraction of the public targets sit in the catalog popularity head?
    tgt_rn = sorted(float(products[str(s["ground_truth"]["parent_asin"])].get("rating_number") or 0) for s in samples)
    print(f"\ntarget rating_number percentiles: p10={tgt_rn[19]:.0f} p50={tgt_rn[99]:.0f} p90={tgt_rn[179]:.0f} min={tgt_rn[0]:.0f}")
    all_rn = sorted((float(p.get("rating_number") or 0) for p in products.values()), reverse=True)
    print(f"catalog rating_number: top-1000th={all_rn[999]:.0f} top-5000th={all_rn[4999]:.0f}")
    n_above = sum(1 for v in all_rn if v >= tgt_rn[0])
    print(f"catalog products with rating_number >= min target ({tgt_rn[0]:.0f}): {n_above}")


if __name__ == "__main__":
    main()
