"""Adversarial robustness harness.

The agent inverts the public customer simulator. That is legitimate user modelling,
but it must not be the *only* thing holding the score up: the private 800 sessions may

  (a) ship organizer-authored intent cards that are NOT derivable from product metadata, or
  (b) paraphrase the natural language wording, or
  (c) both at once.

The competition spec promises that paraphrasing "cannot decide correctness", so the
constraint content survives; only the surface form and the card source may change.
This harness reproduces each of those worlds and reports how far the score falls.
Everything below is a *test*, not part of the shipped agent.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import (  # noqa: E402
    MAX_TURNS,
    TOP_K,
    ALLOWED_ATTRIBUTES,
    catalog_index,
    classify_constraint,
    coarse_category,
    intent_card,
    normalize_recommendations,
    _clean_constraint,
    _flatten_values,
)
from starter.agent import Agent  # noqa: E402
from starter.catalog_index import CatalogIndex  # noqa: E402


# --- alternative intent-card sources ---------------------------------------


def card_from_description(product: dict) -> dict:
    """An intent card the agent's inverse model cannot reproduce.

    Draws on description and title n-grams instead of features/details, so every
    exact-match route inside the agent fails and only the fallbacks remain.
    """
    parts = [*_flatten_values(product.get("description"))]
    title = str(product.get("title") or "")
    words = title.split()
    if len(words) >= 4:
        parts.append(" ".join(words[:4]))
        parts.append(" ".join(words[-4:]))
    if product.get("store"):
        parts.append(f"brand: {product['store']}")
    cleaned = list(dict.fromkeys(_clean_constraint(p, 180) for p in parts if _clean_constraint(p, 180)))
    if not cleaned:
        cleaned = [_clean_constraint(title, 180) or "product"]
    return {
        "target_category": _clean_constraint(title, 180),
        "hard_constraints": cleaned[:2],
        "soft_preferences": cleaned[2:4] or cleaned[:1],
    }


CARD_SOURCES = {
    "official": lambda p: intent_card(p),
    "description": card_from_description,
}


# --- alternative surface wording -------------------------------------------


def paraphrase(text: str, rng: random.Random) -> str:
    """Rewrite the simulator's fixed templates while preserving constraint content."""
    subs = [
        (r"^I'm looking for (.*), but I'm still exploring\.$",
         lambda m: rng.choice([
             f"Hi there — I'm shopping for {m.group(1)}, just browsing for now.",
             f"So I need {m.group(1)}. Nothing decided yet though.",
         ])),
        (r"^I'm looking for (.*?)\. A key requirement is: (.*)\.$",
         lambda m: rng.choice([
             f"I want {m.group(1)}. The one thing I really need: {m.group(2)}",
             f"Shopping for {m.group(1)} — must have {m.group(2)}, that's non-negotiable.",
         ])),
        (r"^For that, what matters is: (.*)\.$",
         lambda m: rng.choice([
             f"What matters to me: {m.group(1)}",
             f"Well, {m.group(1)} — that's the important part.",
         ])),
        (r"^I don't have an additional preference for (.*)\.$",
         lambda m: rng.choice([
             f"Nope, nothing more on {m.group(1)}.",
             f"No further thoughts about {m.group(1)}, sorry.",
         ])),
        (r"^I don't have a preference for (.*); please use your judgment\.$",
         lambda m: f"Honestly no strong feelings on {m.group(1)} — you pick."),
        (r"^Actually, ignore my earlier preference\. What I need is: (.*)\.$",
         lambda m: rng.choice([
             f"Hold on, forget what I said before. What I actually need is {m.group(1)}",
             f"Scratch that earlier bit — the real requirement is {m.group(1)}",
         ])),
    ]
    for pattern, repl in subs:
        match = re.match(pattern, text)
        if match:
            return repl(match)
    return text


# --- evaluation loop --------------------------------------------------------


def initial_message(sample: dict, category: str, disclosed: set[str]) -> str:
    scenario = sample["scenario_type"]
    if scenario == "buying" and sample["intent_card"].get("hard_constraints"):
        constraint = str(sample["intent_card"]["hard_constraints"][0])
        disclosed.add(constraint)
        return f"I'm looking for {category}. A key requirement is: {constraint}."
    if scenario == "intent_override":
        return f"I'm looking for {category}. {sample['behavior']['override']['old_value']}"
    return f"I'm looking for {category}, but I'm still exploring."


def customer_reply(sample: dict, attribute, disclosed: set[str], boundary_used: bool):
    attribute = attribute if isinstance(attribute, str) else None
    if sample["scenario_type"] == "boundary" and not boundary_used and attribute:
        return f"I don't have a preference for {attribute}; please use your judgment.", True
    if not attribute:
        return "Those options are not quite right yet. Ask me about one specific attribute.", boundary_used
    if attribute not in ALLOWED_ATTRIBUTES:
        attribute = "other"
    constraints = [
        *[str(v) for v in sample["intent_card"].get("hard_constraints", [])],
        *[str(v) for v in sample["intent_card"].get("soft_preferences", [])],
    ]
    matches = [v for v in constraints
               if v not in disclosed and (attribute == "other" or classify_constraint(v) == attribute)][:2]
    if not matches:
        return f"I don't have an additional preference for {attribute}.", boundary_used
    disclosed.update(matches)
    return "For that, what matters is: " + "; ".join(matches) + ".", boundary_used


def run(agent, samples, catalog_ids, categories, products, card_source: str, wording: str) -> dict:
    make_card = CARD_SOURCES[card_source]
    sessions = []
    for sample in samples:
        rng = random.Random(sample["sample_id"])
        target = str(sample["ground_truth"]["parent_asin"])
        card = make_card(products[target])
        behavior = {"scenario_type": sample["scenario_type"]}
        if sample["scenario_type"] == "intent_override":
            seed = random.Random(f"{sample['sample_id']}\0{sample['scenario_type']}")
            hard, soft = card["hard_constraints"], card["soft_preferences"]
            new_value = hard[0] if hard else "the target requirements"
            behavior["override"] = {
                "turn": seed.choice([3, 4]),
                "old_value": soft[-1] if soft else "I prefer a different style.",
                "new_value": new_value,
                "message": f"Actually, ignore my earlier preference. What I need is: {new_value}.",
            }
        eff = {**sample, "intent_card": card, "behavior": behavior}

        agent.reset(sample["sample_id"], sample["user_profile"])
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        message = initial_message(eff, coarse_category(categories.get(target, [])), disclosed)

        hit_turn, best_rank = None, None
        for turn in range(1, MAX_TURNS + 1):
            spoken = paraphrase(message, rng) if wording == "paraphrase" else message
            try:
                response = agent.respond(sample["sample_id"], spoken, turn, TOP_K)
            except Exception as exc:  # noqa: BLE001
                print(f"  !! agent raised on {sample['sample_id']} turn {turn}: {exc!r}")
                response = {"message": "", "ask_attribute": None, "recommendations": []}
            ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
            if override_applied and target in ranked:
                best_rank, hit_turn = ranked.index(target) + 1, turn
                break
            if turn == MAX_TURNS:
                break
            override = behavior.get("override") or {}
            if not override_applied and turn + 1 == int(override.get("turn", 3)):
                override_applied = True
                disclosed.add(str(override.get("new_value", "")))
                message = str(override.get("message", ""))
            else:
                message, boundary_used = customer_reply(eff, response.get("ask_attribute"), disclosed, boundary_used)
        sessions.append({"hit": hit_turn is not None, "turn": hit_turn,
                         "rr": 0.0 if best_rank is None else 1.0 / best_rank})

    hit = statistics.fmean(float(s["hit"]) for s in sessions)
    mrr = statistics.fmean(s["rr"] for s in sessions)
    mttc = statistics.fmean(s["turn"] if s["turn"] else MAX_TURNS + 1 for s in sessions)
    eff = max(0.0, min(1.0, (11.0 - mttc) / 10.0))
    return {"hit": hit, "mrr": mrr, "mttc": mttc, "score": 0.5 * hit + 0.3 * mrr + 0.2 * eff}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", default=str(ROOT / "data" / "catalog.jsonl"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "public_set.jsonl"))
    args = parser.parse_args()

    catalog_ids, categories, products = catalog_index(args.catalog)
    samples = [json.loads(l) for l in Path(args.dataset).open(encoding="utf-8") if l.strip()]
    index = CatalogIndex(args.catalog)
    agent = Agent(index=index)

    print(f"{'card source':14s} {'wording':12s} {'score':>8s} {'hit@10':>8s} {'mrr':>8s} {'mttc':>7s}")
    for card_source in ("official", "description"):
        for wording in ("verbatim", "paraphrase"):
            result = run(agent, samples, catalog_ids, categories, products, card_source, wording)
            print(f"{card_source:14s} {wording:12s} {result['score']:8.4f} {result['hit']:8.3f} "
                  f"{result['mrr']:8.4f} {result['mttc']:7.3f}", flush=True)


if __name__ == "__main__":
    main()
