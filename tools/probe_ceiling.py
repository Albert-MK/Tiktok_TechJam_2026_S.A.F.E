"""Measure the information ceiling of the deterministic simulator.

Once every disclosable constraint is known, how many catalog products remain
indistinguishable, and can a popularity prior pick the true target out of the tie?
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import coarse_category, intent_card  # noqa: E402


def main() -> None:
    products: dict[str, dict] = {}
    full_key: dict[str, tuple] = {}
    with (ROOT / "data" / "catalog.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            product = json.loads(line)
            asin = str(product["parent_asin"])
            products[asin] = product
            card = intent_card(product)
            cat = coarse_category([str(v) for v in product.get("categories") or []])
            full_key[asin] = (
                cat,
                tuple(str(v) for v in card["hard_constraints"]),
                tuple(str(v) for v in card["soft_preferences"]),
            )

    groups: dict[tuple, list[str]] = defaultdict(list)
    for asin, key in full_key.items():
        groups[key].append(asin)

    sizes = Counter(len(v) for v in groups.values())
    total = len(full_key)
    uniq = sum(n for n, c in sizes.items() if n == 1 for _ in range(c))
    uniq = sum(len(v) for v in groups.values() if len(v) == 1)
    le10 = sum(len(v) for v in groups.values() if len(v) <= 10)
    print(f"FULL-INFO ceiling: unique={uniq/total:.2%}  group<=10={le10/total:.2%}")
    print("group size histogram (size: #groups):", sorted(sizes.items())[:12])
    print("largest groups:", sorted((len(v) for v in groups.values()), reverse=True)[:10])

    # Validate on the 200 public targets: how big is their tie group, and does a
    # popularity prior rank the true target first inside it?
    samples = [json.loads(l) for l in (ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") if l.strip()]
    tie_sizes = []
    rr_pop, rr_arbitrary = [], []
    for sample in samples:
        target = str(sample["ground_truth"]["parent_asin"])
        group = groups[full_key[target]]
        tie_sizes.append(len(group))

        def pop(a: str) -> tuple:
            p = products[a]
            return (float(p.get("rating_number") or 0), float(p.get("average_rating") or 0))

        ranked = sorted(group, key=pop, reverse=True)
        rr_pop.append(1.0 / (ranked.index(target) + 1))
        rr_arbitrary.append(1.0 / (sorted(group).index(target) + 1))

    print(f"\npublic-set tie group size: mean={statistics.fmean(tie_sizes):.2f} "
          f"median={statistics.median(tie_sizes)} max={max(tie_sizes)} "
          f"unique={sum(1 for s in tie_sizes if s == 1)/len(tie_sizes):.2%}")
    print(f"MRR inside tie group, popularity order : {statistics.fmean(rr_pop):.4f}")
    print(f"MRR inside tie group, arbitrary order  : {statistics.fmean(rr_arbitrary):.4f}")
    print(f"target in tie-group top10 (popularity) : "
          f"{sum(1 for s, r in zip(tie_sizes, rr_pop) if r >= 1/10)/len(tie_sizes):.2%}")

    # Is rating_number of targets systematically higher than catalog average?
    tgt_rn = [float(products[str(s['ground_truth']['parent_asin'])].get('rating_number') or 0) for s in samples]
    all_rn = [float(p.get("rating_number") or 0) for p in products.values()]
    print(f"\nrating_number median: targets={statistics.median(tgt_rn):.0f} catalog={statistics.median(all_rn):.0f}")


if __name__ == "__main__":
    main()
