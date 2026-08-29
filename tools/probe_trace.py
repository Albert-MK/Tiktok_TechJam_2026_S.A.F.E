"""Turn-by-turn trace of the agent's belief, to find where MTTC is still being lost.

MRR is 1.0 and turn-1 ranking is at the information limit, so every remaining point
comes from sessions that need 3+ turns. This prints what the agent asked, how big the
belief was, and where the true target sat, for exactly those sessions.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import (  # noqa: E402
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    materialize_hidden_fields,
    normalize_recommendations,
)
from starter.agent import Agent  # noqa: E402


def main() -> None:
    verbose = "--verbose" in sys.argv
    catalog = str(ROOT / "data" / "catalog.jsonl")
    catalog_ids, categories, products = catalog_index(catalog)
    samples = [json.loads(l) for l in (ROOT / "data" / "public_set.jsonl").open(encoding="utf-8") if l.strip()]
    agent = Agent(catalog)
    pid_of = {asin: pid for pid, asin in enumerate(agent.index.asins)}

    ask_counts: dict[int, Counter] = defaultdict(Counter)
    slow: list[dict] = []
    hit_turns = Counter()

    for sample in samples:
        session_id = sample["sample_id"]
        agent.reset(session_id, sample["user_profile"])
        target = str(sample["ground_truth"]["parent_asin"])
        card, behavior = materialize_hidden_fields(sample, products)
        eff = {**sample, "intent_card": card, "behavior": behavior}
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        message = initial_message(eff, coarse_category(categories.get(target, [])), disclosed)

        trace = []
        hit_turn = None
        for turn in range(1, MAX_TURNS + 1):
            response = agent.respond(session_id, message, turn, TOP_K)
            ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
            belief = agent._sessions[session_id].belief
            pids, probs, leak = belief.posterior()
            tp = pid_of[target]
            rank = pids.index(tp) + 1 if tp in pids else None
            trace.append({
                "turn": turn,
                "heard": message[:110],
                "ask": response.get("ask_attribute"),
                "n_sent": len(ranked),
                "pool": len(belief.candidates),
                "target_rank": rank,
                "p_top": round(probs[0], 3) if probs else 0.0,
                "leak": round(leak, 3),
            })
            ask_counts[turn][response.get("ask_attribute")] += 1

            if override_applied and target in ranked:
                hit_turn = turn
                break
            if turn == MAX_TURNS:
                break
            override = eff.get("behavior", {}).get("override") or {}
            if not override_applied and turn + 1 == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                message = str(override.get("message", ""))
            else:
                message, boundary_used = customer_reply(eff, response.get("ask_attribute"), disclosed, boundary_used)

        hit_turns[(sample["scenario_type"], hit_turn)] += 1
        floor = 3 if sample["scenario_type"] == "intent_override" else 1
        if hit_turn is None or hit_turn > max(floor, 2):
            slow.append({"id": sample["sample_id"], "scenario": sample["scenario_type"],
                         "hit_turn": hit_turn, "trace": trace, "card": card})

    print("=== ask attribute chosen, by turn ===")
    for turn in sorted(ask_counts)[:5]:
        print(f"  turn {turn}: {ask_counts[turn].most_common()}")

    print("\n=== hit turn distribution ===")
    for scenario in sorted({s for s, _ in hit_turns}):
        row = {t: c for (s, t), c in hit_turns.items() if s == scenario}
        print(f"  {scenario:16s} {dict(sorted(row.items(), key=lambda kv: (kv[0] is None, kv[0])))}")

    print(f"\n=== {len(slow)} slow sessions ===")
    for item in slow[:12] if not verbose else slow:
        print(f"\n-- {item['id']} [{item['scenario']}] hit_turn={item['hit_turn']}")
        print(f"   card hard={item['card']['hard_constraints']}")
        print(f"   card soft={item['card']['soft_preferences']}")
        for row in item["trace"]:
            print(f"   t{row['turn']} ask={str(row['ask']):9s} sent={row['n_sent']} pool={row['pool']:4d} "
                  f"rank={row['target_rank']} p_top={row['p_top']} | {row['heard']}")


if __name__ == "__main__":
    main()
