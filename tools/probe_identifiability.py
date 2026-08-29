"""Measure how identifiable the hidden target is from simulator-observable keys.

Answers: if we invert the evaluator's deterministic intent-card derivation,
how large is the set of catalog products consistent with turn-1 / turn-2 observations?
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import (  # noqa: E402
    classify_constraint,
    coarse_category,
    intent_card,
)


def main() -> None:
    catalog = ROOT / "data" / "catalog.jsonl"
    cards: dict[str, dict] = {}
    cats: dict[str, str] = {}
    with catalog.open(encoding="utf-8") as handle:
        for line in handle:
            product = json.loads(line)
            asin = str(product["parent_asin"])
            cards[asin] = intent_card(product)
            cats[asin] = coarse_category([str(v) for v in product.get("categories") or []])

    print(f"catalog size: {len(cards)}")

    by_cat: dict[str, list[str]] = defaultdict(list)
    for asin, cat in cats.items():
        by_cat[cat].append(asin)
    sizes = sorted((len(v) for v in by_cat.values()), reverse=True)
    print(f"distinct coarse categories: {len(by_cat)}")
    print(f"coarse-category bucket sizes: max={sizes[0]} median={sizes[len(sizes)//2]}")

    # Turn-1 key for buying sessions: (coarse_cat, hard_constraints[0])
    buy_key: dict[tuple[str, str], int] = Counter()
    # Turn-1 key for override sessions: (coarse_cat, soft_preferences[-1])
    ovr_key: dict[tuple[str, str], int] = Counter()
    # Turn-2 key for browsing after learning hard_constraints[:2]
    brow2_key: dict[tuple, int] = Counter()
    # Turn-2 key for browsing if we instead ask a typed attribute revealing 2 "feature"s
    brow_feat_key: dict[tuple, int] = Counter()

    for asin, card in cards.items():
        cat = cats[asin]
        hard = [str(v) for v in card["hard_constraints"]]
        soft = [str(v) for v in card["soft_preferences"]]
        buy_key[(cat, hard[0] if hard else "")] += 1
        ovr_key[(cat, soft[-1] if soft else "")] += 1
        brow2_key[(cat, tuple(hard[:2]))] += 1
        feats = [c for c in [*hard, *soft] if classify_constraint(c) == "feature"][:2]
        brow_feat_key[(cat, tuple(feats))] += 1

    def report(name: str, counter: Counter) -> None:
        total = sum(counter.values())
        uniq = sum(v for v in counter.values() if v == 1)
        le10 = sum(v for v in counter.values() if v <= 10)
        worst = max(counter.values())
        print(
            f"{name:34s} unique={uniq/total:6.2%}  bucket<=10={le10/total:6.2%}  worst_bucket={worst}"
        )

    report("turn1 buying (cat, hard0)", buy_key)
    report("turn1 override (cat, soft_last)", ovr_key)
    report("turn2 browsing (cat, hard0..1)", brow2_key)
    report("turn2 browsing ask=feature", brow_feat_key)

    # How often does hard_constraints[0] end up being a bare material word?
    mat = sum(1 for c in cards.values() if len(str(c["hard_constraints"][0])) <= 12)
    print(f"short (<=12 char) hard0, likely bare material: {mat/len(cards):.2%}")

    # Distribution of constraint types across the 4 disclosable slots
    slot_types = Counter()
    for card in cards.values():
        allc = [*card["hard_constraints"], *card["soft_preferences"]]
        for c in allc:
            slot_types[classify_constraint(str(c))] += 1
    print("constraint type distribution:", slot_types.most_common())


if __name__ == "__main__":
    main()
