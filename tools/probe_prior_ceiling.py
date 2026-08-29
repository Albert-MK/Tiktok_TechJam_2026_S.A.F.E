"""Is turn-1 accuracy at the information-theoretic limit?

If targets really are sampled from review records, then within a coarse category
P(p) = rating_number(p) / sum(rating_number). The best any prior can do at turn 1
is to guess the argmax, which succeeds with probability rn_max / sum(rn).

If that predicted rate matches what the agent actually achieves, no better prior
exists and turn-1 effort should stop.
"""
from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import coarse_category  # noqa: E402


def main() -> None:
    rn: dict[str, float] = {}
    cats: dict[str, str] = {}
    with (ROOT / "data" / "catalog.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            p = json.loads(line)
            a = str(p["parent_asin"])
            try:
                rn[a] = float(p.get("rating_number") or 0.0)
            except (TypeError, ValueError):
                rn[a] = 0.0
            cats[a] = coarse_category([str(v) for v in p.get("categories") or []])

    by_cat = defaultdict(list)
    for a, c in cats.items():
        by_cat[c].append(a)

    samples = [json.loads(l) for l in (ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") if l.strip()]

    predicted, observed_rank1, bucket = [], 0, []
    for s in samples:
        t = str(s["ground_truth"]["parent_asin"])
        pool = by_cat[cats[t]]
        total = sum(rn[a] for a in pool)
        best = max(rn[a] for a in pool)
        predicted.append(best / total if total > 0 else 1.0 / len(pool))
        winner = max(pool, key=lambda a: rn[a])
        observed_rank1 += int(winner == t)
        bucket.append(len(pool))

    print(f"sessions: {len(samples)}")
    print(f"predicted turn-1 top1 under P ∝ rating_number : {statistics.fmean(predicted):.2%}")
    print(f"observed  turn-1 top1 (argmax rating_number)  : {observed_rank1/len(samples):.2%}")
    print(f"category bucket size: mean={statistics.fmean(bucket):.1f} median={statistics.median(bucket):.0f}")

    # Same check for the "cat + 2 constraints" state that turn 2 reaches.
    from starter.user_model import intent_card

    cards = {}
    with (ROOT / "data" / "catalog.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            p = json.loads(line)
            hard, soft = intent_card(p)
            cards[str(p["parent_asin"])] = tuple(hard) + tuple(soft)

    pred2, obs2 = [], 0
    for s in samples:
        t = str(s["ground_truth"]["parent_asin"])
        needles = cards[t][:2]
        pool = [a for a in by_cat[cats[t]] if all(n in cards[a] for n in needles)]
        total = sum(rn[a] for a in pool)
        best = max(rn[a] for a in pool)
        pred2.append(best / total if total > 0 else 1.0 / len(pool))
        obs2 += int(max(pool, key=lambda a: rn[a]) == t)
    print(f"\nturn-2 state (cat + 2 constraints):")
    print(f"predicted top1 : {statistics.fmean(pred2):.2%}")
    print(f"observed  top1 : {obs2/len(samples):.2%}")


if __name__ == "__main__":
    main()
