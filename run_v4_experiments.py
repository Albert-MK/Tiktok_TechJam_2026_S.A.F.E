"""Fast v1.3 ranking experiments on the official public development set.

The catalog index is built once, then each configuration is evaluated on the
same deterministic 200-session set. A trial is eligible only when Hit@10 stays
at 1.0 and TechnicalScore strictly improves over v1.2.
"""

from __future__ import annotations

import json
import os
import time
from itertools import combinations
from pathlib import Path

# Prevent a previous shell experiment from leaking into this run.
os.environ.pop("AGENT_EXP_FLAGS", None)
os.environ["AGENT_STRATEGY"] = "final"

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from starter.agent import Agent


BASELINE_SCORE = 0.897106
SINGLE_TRIALS = [
    *[
        {
            "name": f"bm25_coef_{value:g}",
            "flags": {"bm25_coef": value},
            "method": "Tune the lexical-route rank prior.",
        }
        for value in (0.03, 0.05, 0.06, 0.08, 0.12)
    ],
    *[
        {
            "name": f"idf_coverage_{value:g}",
            "flags": {"idf_coverage_weight": value},
            "method": "Reward coverage of rare query terms using FTS5 document frequency.",
        }
        for value in (0.02, 0.05, 0.1, 0.2, 0.4)
    ],
    *[
        {
            "name": f"route_rrf_w{weight:g}_k{k:g}",
            "flags": {"route_rrf_weight": weight, "route_rrf_k": k},
            "method": "Fuse exact phrase, category-constrained, and broad retrieval ranks with RRF.",
        }
        for weight, k in ((1.0, 10.0), (3.0, 10.0), (5.0, 10.0), (10.0, 10.0), (20.0, 10.0), (10.0, 30.0))
    ],
    {
        "name": "override_reset_asked",
        "flags": {"override_reset_asked": True},
        "method": "Restart clarification questions when replacement intent arrives.",
    },
    {
        "name": "eager_second_other",
        "flags": {"eager_second_other": True},
        "method": "Ask the high-yield catch-all question twice before typed attributes.",
    },
]


def compact(result: dict) -> dict:
    return {
        key: result[key]
        for key in (
            "hit_rate_at_10",
            "mrr",
            "mttc",
            "efficiency",
            "recommended_technical_score",
            "scenario_metrics",
        )
    }


def eligible(result: dict, reference_score: float) -> bool:
    return (
        result["hit_rate_at_10"] >= 1.0
        and result["recommended_technical_score"] > reference_score + 1e-9
    )


def v12_config(config: dict) -> dict:
    """Remove v1.3 defaults so historical ablations remain reproducible."""
    result = dict(config)
    result.update(
        {
            "entry_prefix_weight": 0.0,
            "profile_tag_weight": 0.0,
            "profile_tags_override_only": False,
        }
    )
    return result


def run_trial(agent: Agent, base_config: dict, samples: list[dict], catalog_pack, spec: dict) -> dict:
    agent.cfg = {**base_config, **spec["flags"]}
    started = time.perf_counter()
    result = compact(evaluate(agent, samples, *catalog_pack))
    elapsed = time.perf_counter() - started
    return {
        **spec,
        "metrics": result,
        "elapsed_seconds": round(elapsed, 3),
        "delta_vs_v12": round(result["recommended_technical_score"] - BASELINE_SCORE, 6),
        "eligible_vs_v12": eligible(result, BASELINE_SCORE),
    }


def main() -> None:
    catalog_path = "data/catalog.jsonl"
    samples = load_jsonl("data/public_set.jsonl")
    catalog_pack = catalog_index(catalog_path)
    agent = Agent(catalog_path)
    base_config = v12_config(agent.cfg)

    baseline = run_trial(
        agent,
        base_config,
        samples,
        catalog_pack,
        {"name": "v1.2_recheck", "flags": {}, "method": "Current default strategy."},
    )
    attempts = [baseline]

    singles = []
    for spec in SINGLE_TRIALS:
        trial = run_trial(agent, base_config, samples, catalog_pack, spec)
        attempts.append(trial)
        singles.append(trial)
        print(
            f"{trial['name']}: {trial['metrics']['recommended_technical_score']:.6f} "
            f"({trial['delta_vs_v12']:+.6f})",
            flush=True,
        )

    best_by_family: dict[str, dict] = {}
    for trial in singles:
        family = next(iter(trial["flags"]))
        current = best_by_family.get(family)
        if current is None or (
            trial["metrics"]["recommended_technical_score"]
            > current["metrics"]["recommended_technical_score"]
        ):
            best_by_family[family] = trial

    family_winners = [
        trial for trial in best_by_family.values()
        if trial["metrics"]["hit_rate_at_10"] >= 1.0
    ]
    combo_specs = []
    for size in (2, 3):
        for group in combinations(family_winners, size):
            flags: dict = {}
            for trial in group:
                flags.update(trial["flags"])
            combo_specs.append(
                {
                    "name": "combo__" + "__".join(trial["name"] for trial in group),
                    "flags": flags,
                    "method": "Interaction test combining the strongest non-miss variants.",
                }
            )

    for spec in combo_specs:
        trial = run_trial(agent, base_config, samples, catalog_pack, spec)
        attempts.append(trial)
        print(
            f"{trial['name']}: {trial['metrics']['recommended_technical_score']:.6f} "
            f"({trial['delta_vs_v12']:+.6f})",
            flush=True,
        )

    champion = max(
        (trial for trial in attempts if trial["metrics"]["hit_rate_at_10"] >= 1.0),
        key=lambda trial: trial["metrics"]["recommended_technical_score"],
    )
    payload = {
        "dataset": "data/public_set.jsonl",
        "catalog": catalog_path,
        "baseline_score": BASELINE_SCORE,
        "acceptance_rule": "Hit@10 must remain 1.0 and TechnicalScore must strictly improve.",
        "champion": champion,
        "adopt_new_version": eligible(champion["metrics"], BASELINE_SCORE),
        "attempts": attempts,
    }
    out_path = Path("runs/v4_optimization_attempts.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"CHAMPION: {champion['name']} {champion['metrics']}", flush=True)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
