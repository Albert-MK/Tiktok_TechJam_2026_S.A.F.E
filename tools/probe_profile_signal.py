"""Does user_profile carry any information about which product is the target?

The agent currently ignores it. If profile fields correlate with target attributes,
folding them into the prior would cut turn-1 MTTC. If not, ignoring them is correct
and we should say so explicitly in the report.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    products = {}
    with (ROOT / "data" / "catalog.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            p = json.loads(line)
            products[str(p["parent_asin"])] = p

    samples = [json.loads(l) for l in (ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") if l.strip()]

    # 1) Does average_prior_rating track the target's average_rating?
    pairs = []
    for s in samples:
        t = products[str(s["ground_truth"]["parent_asin"])]
        prof = s["user_profile"]
        try:
            pairs.append((float(prof.get("average_prior_rating")), float(t.get("average_rating") or 0)))
        except (TypeError, ValueError):
            pass
    if len(pairs) > 2:
        xs = [a for a, _ in pairs]
        ys = [b for _, b in pairs]
        try:
            r = statistics.correlation(xs, ys)
        except statistics.StatisticsError:
            r = float("nan")
        print(f"corr(average_prior_rating, target.average_rating) = {r:+.4f}  (n={len(pairs)})")
        print(f"  profile ratings seen: {sorted(Counter(xs).items())}")

    # 2) Do preference_tags predict the target's coarse category?
    tag_cat = defaultdict(Counter)
    tag_totals = Counter()
    for s in samples:
        t = products[str(s["ground_truth"]["parent_asin"])]
        cats = [str(v) for v in t.get("categories") or []]
        leaf = cats[-1] if cats else "?"
        for tag in s["user_profile"].get("preference_tags") or []:
            tag_cat[tag][leaf] += 1
            tag_totals[tag] += 1
    base = Counter()
    for s in samples:
        t = products[str(s["ground_truth"]["parent_asin"])]
        cats = [str(v) for v in t.get("categories") or []]
        base[cats[-1] if cats else "?"] += 1
    print(f"\npreference_tags: {sorted(tag_totals.items(), key=lambda kv: -kv[1])}")
    print(f"distinct target leaf categories: {len(base)}; most common: {base.most_common(5)}")

    # Mutual-information style check: is the tag->category distribution different from base?
    n = len(samples)
    for tag, counter in sorted(tag_cat.items(), key=lambda kv: -tag_totals[kv[0]])[:6]:
        total = sum(counter.values())
        top = counter.most_common(3)
        expected = [(c, base[c] * total / n) for c, _ in top]
        print(f"  {tag:14s} n={total:4d} top={[(c, k) for c, k in top]} expected≈{[(c, round(e,1)) for c, e in expected]}")

    # 3) purchase_frequency / rating_style vs target popularity
    for field in ("purchase_frequency", "rating_style"):
        groups = defaultdict(list)
        for s in samples:
            t = products[str(s["ground_truth"]["parent_asin"])]
            groups[str(s["user_profile"].get(field))].append(float(t.get("rating_number") or 0))
        print(f"\n{field} -> median target rating_number:")
        for key, values in sorted(groups.items()):
            print(f"  {key:28s} n={len(values):4d} median={statistics.median(values):9.0f}")


if __name__ == "__main__":
    main()
