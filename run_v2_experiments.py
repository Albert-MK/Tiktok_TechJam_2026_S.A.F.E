"""Greedy public-set experiments on top of v1. Keep a flag only if it beats the champion."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl

V1 = {
    "hit_rate_at_10": 1.0,
    "mrr": 0.695036,
    "mttc": 2.35,
    "efficiency": 0.865,
    "recommended_technical_score": 0.881511,
}

EXPERIMENTS = [
    {
        "name": "distinctive_exact_bonus",
        "flags": {"distinctive_exact_bonus": True},
        "how": "Rerank: long/distinctive constraint substrings get a large exact-match bonus; generic tokens like leather/imported get only a small bonus so popular generic items stop crowding out the target.",
    },
    {
        "name": "punct_normalize",
        "flags": {"punct_normalize": True},
        "how": "Match constraints after stripping punctuation (100% leather ~= 100 leather) on both catalog text and needles.",
    },
    {
        "name": "distinctive_query_focus",
        "flags": {"distinctive_query_focus": True},
        "how": "When at least one long constraint exists, BM25/AND queries drop generic short constraints and search with category + distinctive phrases only.",
    },
    {
        "name": "title_distinctive_boost",
        "flags": {"title_distinctive_boost": True},
        "how": "Extra rerank bonus if a distinctive constraint string appears in the product title.",
    },
    {
        "name": "category_must_match",
        "flags": {"category_must_match": True},
        "how": "Penalize candidates missing any coarse-category token so Mid-Calf Boots stay in boots, not random leather goods.",
    },
    {
        "name": "cover_sort",
        "flags": {"cover_sort": True},
        "how": "Primary sort key = how many distinctive constraints are exact-matched, then the existing score.",
    },
    {
        "name": "override_clear_old",
        "flags": {"override_clear_old": True},
        "how": "On intent override, erase previous constraint slots (keep category via looking-for already stored) and write the new constraint only.",
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
    champion_flags: dict = {}
    champion = dict(V1)
    log = [
        {
            "name": "v1",
            "adopted": True,
            "flags": {},
            "how": "Frozen snapshot of the pre-experiment agent (ask/other retry, exclude shown, hybrid retrieve, phrase rerank).",
            "metrics": V1,
        }
    ]

    print("sanity: v1 flags empty", flush=True)
    sanity = summarize(eval_flags({}, samples, catalog_path, catalog_pack))
    log[0]["sanity_replay"] = sanity
    print(json.dumps(sanity, indent=2), flush=True)

    for spec in EXPERIMENTS:
        trial_flags = {**champion_flags, **spec["flags"]}
        print(f"\n=== {spec['name']} flags={trial_flags} ===", flush=True)
        metrics = summarize(eval_flags(trial_flags, samples, catalog_path, catalog_pack))
        adopted = better(metrics, champion)
        entry = {
            "name": spec["name"],
            "how": spec["how"],
            "flags_tried": trial_flags,
            "metrics": metrics,
            "adopted": adopted,
            "versus_champion_score": round(
                metrics["recommended_technical_score"] - champion["recommended_technical_score"],
                6,
            ),
        }
        print(json.dumps({k: entry[k] for k in ("metrics", "adopted", "versus_champion_score")}, indent=2), flush=True)
        if adopted:
            champion_flags = trial_flags
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
        "v1": V1,
        "champion_flags": champion_flags,
        "champion_metrics": champion,
        "attempts": log,
    }
    (out_dir / "v2_attempts.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("\nCHAMPION FLAGS", champion_flags)
    print("CHAMPION", champion)
    print("Wrote runs/v2_attempts.json")


if __name__ == "__main__":
    main()
