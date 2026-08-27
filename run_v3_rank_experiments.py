"""Greedy public-set ranking experiments on top of v1.1 final.

Keep a flag only if Hit@10 does not drop and TechnicalScore strictly rises.
Official dataset: data/public_set.jsonl + data/catalog.jsonl.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl

# Measured v1.1 final on public_set (also re-checked as baseline in this script).
V11 = {
    "hit_rate_at_10": 1.0,
    "mrr": 0.702738,
    "mttc": 2.385,
    "efficiency": 0.8615,
    "recommended_technical_score": 0.883121,
}

EXPERIMENTS = [
    {
        "name": "soft_cover_bonus",
        "flags": {"soft_cover_bonus": 5.0},
        "how": "Rerank: add 5.0 * (# distinctive exact matches) without changing primary sort key.",
    },
    {
        "name": "generic_match_dampen",
        "flags": {"generic_exact_score": 0.4},
        "how": "Rerank: lower exact-match score for generic phrases (leather/cotton/…) from 1.2 to 0.4.",
    },
    {
        "name": "profile_when_generic_only",
        "flags": {"profile_when_generic_only": True},
        "how": "Disable rating/popularity boost once any distinctive constraint is present.",
    },
    {
        "name": "leaf_category_boost",
        "flags": {"leaf_category_boost": True},
        "how": "Boost candidates whose category path contains the leaf category token (e.g. Sun Hats).",
    },
    {
        "name": "title_category_boost",
        "flags": {"title_category_boost": True},
        "how": "Extra rerank points when coarse category tokens appear in the product title.",
    },
    {
        "name": "features_field_boost",
        "flags": {"features_field_boost": True},
        "how": "Extra score when a constraint needle appears specifically in the features field.",
    },
    {
        "name": "semi_distinctive_bonus",
        "flags": {"semi_distinctive_bonus": True},
        "how": "Give mid-length non-generic phrases (e.g. polyester lining) a medium exact-match bonus.",
    },
    {
        "name": "relaxed_distinctive",
        "flags": {"relaxed_distinctive": True},
        "how": "Treat semi-long phrases as distinctive for retrieve+rerank (_is_distinctive threshold relaxed).",
    },
    {
        "name": "distinctive_partial_boost",
        "flags": {"distinctive_partial_boost": True},
        "how": "When a distinctive needle is not fully matched, raise per-token partial credit 0.35→0.8.",
    },
    {
        "name": "full_cover_bonus",
        "flags": {"full_cover_bonus": True},
        "how": "Large bonus when every distinctive constraint is exact-matched on the product.",
    },
    {
        "name": "store_match_boost",
        "flags": {"store_match_boost": True},
        "how": "Small boost when query tokens appear in the store/brand field.",
    },
    {
        "name": "popularity_dampen",
        "flags": {"popularity_dampen": True},
        "how": "Slightly penalize very popular items (rating_n>500) when distinctive constraints exist.",
    },
    {
        "name": "stronger_category_penalty",
        "flags": {"category_miss_penalty": 15.0},
        "how": "Increase category-must-match miss penalty from 8 to 15.",
    },
    {
        "name": "bm25_lighter",
        "flags": {"bm25_coef": 0.01},
        "how": "Halve BM25 rank penalty so phrase/category signals dominate more.",
    },
    {
        "name": "bm25_heavier",
        "flags": {"bm25_coef": 0.04},
        "how": "Double BM25 rank penalty to trust lexical retrieval order more.",
    },
    {
        "name": "distinctive_exact_base_28",
        "flags": {"distinctive_exact_base": 28.0},
        "how": "Raise distinctive exact-match base score 20→28.",
    },
    {
        "name": "wide_phrase_retrieve",
        "flags": {"wide_phrase_retrieve": True},
        "how": "Fetch more FTS hits for distinctive phrases (30→60) with a larger early-rank bonus.",
    },
    {
        "name": "retrieve_k_150",
        "flags": {"retrieve_k": 150},
        "how": "Widen BM25 candidate pool from 80 to 150 before phrase rerank.",
    },
    {
        "name": "soft_cover_plus_leaf",
        "flags": {"soft_cover_bonus": 5.0, "leaf_category_boost": True},
        "how": "Combo probe: soft cover + leaf category (only meaningful if either alone helped or for completeness).",
    },
]


def summarize(result: dict) -> dict:
    keys = [
        "hit_rate_at_10",
        "mrr",
        "mttc",
        "efficiency",
        "recommended_technical_score",
        "scenario_metrics",
    ]
    return {key: result[key] for key in keys}


def better(candidate: dict, champion: dict) -> bool:
    if candidate["hit_rate_at_10"] < champion["hit_rate_at_10"]:
        return False
    return candidate["recommended_technical_score"] > champion["recommended_technical_score"] + 1e-9


def eval_flags(flags: dict, samples, catalog_path: str, catalog_pack) -> dict:
    os.environ["AGENT_STRATEGY"] = "final"
    os.environ["AGENT_EXP_FLAGS"] = json.dumps(flags)
    import starter.config as config_mod
    import starter.agent as agent_mod

    importlib.reload(config_mod)
    importlib.reload(agent_mod)
    catalog_ids, categories, products = catalog_pack
    return evaluate(agent_mod.Agent(catalog_path), samples, catalog_ids, categories, products)


def main() -> None:
    catalog_path = "data/catalog.jsonl"
    samples = load_jsonl("data/public_set.jsonl")
    catalog_pack = catalog_index(catalog_path)

    print("=== baseline v1.1 final (empty extra flags) ===", flush=True)
    baseline = summarize(eval_flags({}, samples, catalog_path, catalog_pack))
    print(json.dumps(baseline, indent=2), flush=True)

    champion_flags: dict = {}
    champion = {
        "hit_rate_at_10": baseline["hit_rate_at_10"],
        "mrr": baseline["mrr"],
        "mttc": baseline["mttc"],
        "efficiency": baseline["efficiency"],
        "recommended_technical_score": baseline["recommended_technical_score"],
    }
    log = [
        {
            "name": "v1.1_final_baseline",
            "adopted": True,
            "flags": {},
            "how": "Current starter final preset (distinctive_exact_bonus + category_must_match).",
            "metrics": baseline,
            "reference_v11_doc": V11,
        }
    ]

    for spec in EXPERIMENTS:
        # Greedy: stack on adopted champion flags. Named combos replace entirely if they
        # already include multiple keys and name starts with soft_cover_plus.
        if spec["name"] == "soft_cover_plus_leaf":
            trial_flags = {**champion_flags, **spec["flags"]}
        else:
            trial_flags = {**champion_flags, **spec["flags"]}
        print(f"\n=== {spec['name']} flags={trial_flags} ===", flush=True)
        metrics = summarize(eval_flags(trial_flags, samples, catalog_path, catalog_pack))
        adopted = better(metrics, champion)
        entry = {
            "name": spec["name"],
            "how": spec["how"],
            "flags_tried": trial_flags,
            "metrics": {
                "hit_rate_at_10": metrics["hit_rate_at_10"],
                "mrr": metrics["mrr"],
                "mttc": metrics["mttc"],
                "efficiency": metrics["efficiency"],
                "recommended_technical_score": metrics["recommended_technical_score"],
            },
            "scenario_metrics": metrics["scenario_metrics"],
            "adopted": adopted,
            "versus_champion_score": round(
                metrics["recommended_technical_score"] - champion["recommended_technical_score"],
                6,
            ),
        }
        print(
            json.dumps(
                {
                    "metrics": entry["metrics"],
                    "adopted": adopted,
                    "versus_champion_score": entry["versus_champion_score"],
                },
                indent=2,
            ),
            flush=True,
        )
        if adopted:
            champion_flags = dict(trial_flags)
            champion = {
                "hit_rate_at_10": metrics["hit_rate_at_10"],
                "mrr": metrics["mrr"],
                "mttc": metrics["mttc"],
                "efficiency": metrics["efficiency"],
                "recommended_technical_score": metrics["recommended_technical_score"],
            }
        log.append(entry)

    out_dir = Path("runs")
    out_dir.mkdir(exist_ok=True)
    payload = {
        "dataset": "data/public_set.jsonl",
        "catalog": catalog_path,
        "champion_flags": champion_flags,
        "champion_metrics": champion,
        "attempts": log,
    }
    out_path = out_dir / "v3_rank_attempts.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("\nCHAMPION FLAGS", champion_flags)
    print("CHAMPION", champion)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
