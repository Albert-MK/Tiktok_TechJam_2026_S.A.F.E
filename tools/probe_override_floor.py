"""What is the irreducible MTTC floor for intent_override sessions?

An override session cannot score before the new intent arrives, and the evaluator
picks that turn with rng.choice([3, 4]) seeded from the sample id. Recomputing that
seed tells us the exact floor, so we know whether our 3.7 is slack or bedrock.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    samples = [json.loads(l) for l in (ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") if l.strip()]
    turns = []
    for s in samples:
        if s["scenario_type"] != "intent_override":
            continue
        rng = random.Random(f"{s.get('sample_id','')}\0{s.get('scenario_type','')}")
        turns.append(rng.choice([3, 4]))
    print(f"intent_override sessions: {len(turns)}")
    print(f"override turn distribution: {dict(sorted(Counter(turns).items()))}")
    print(f"irreducible MTTC floor for these sessions: {statistics.fmean(turns):.4f}")

    floor_total = statistics.fmean(turns) * len(turns)
    print(f"floor turn-budget contributed by override: {floor_total:.1f} of 200 sessions")


if __name__ == "__main__":
    main()
