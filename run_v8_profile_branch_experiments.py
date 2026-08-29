"""Compare v1.5 vs profile-guided branch-aware ask logic (v8)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.pop("AGENT_EXP_FLAGS", None)
os.environ["AGENT_STRATEGY"] = "final"

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from starter.agent import Agent


V15_SCORE = 0.914778

TRIALS = [
    {
        "name": "v1.5_recheck",
        "flags": {},
        "method": "Current v1.5: other_first fixed typed order + delay rules.",
    },
    {
        "name": "profile_branch",
        "flags": {"ask_mode": "profile_branch"},
        "method": "After other, pick typed attr by profile prior × branch split × low-yield penalty.",
    },
    {
        "name": "profile_branch_skip_covered",
        "flags": {"ask_mode": "profile_branch", "skip_covered_attrs": True},
        "method": "profile_branch plus skip typed attrs already implied by constraints.",
    },
    {
        "name": "profile_branch_stop15",
        "flags": {"ask_mode": "profile_branch", "narrow_stop_candidates": 15},
        "method": "Stop asking once distinctive-filtered branch has <=15 items.",
    },
    {
        "name": "profile_branch_all_constraints",
        "flags": {"ask_mode": "profile_branch", "profile_branch_all_constraints": True},
        "method": "Filter active branch with all constraints (not distinctive-only).",
    },
    {
        "name": "profile_branch_no_low_yield",
        "flags": {"ask_mode": "profile_branch", "profile_branch_no_low_yield_penalty": True},
        "method": "profile_branch without brand/budget/category penalty.",
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


def run_trial(agent: Agent, base_config: dict, samples: list[dict], catalog_pack, spec: dict) -> dict:
    agent.cfg = {**base_config, **spec["flags"]}
    started = time.perf_counter()
    result = compact(evaluate(agent, samples, *catalog_pack))
    elapsed = time.perf_counter() - started
    score = result["recommended_technical_score"]
    return {
        **spec,
        "metrics": result,
        "elapsed_seconds": round(elapsed, 3),
        "delta_vs_v15": round(score - V15_SCORE, 6),
        "eligible_vs_v15": (
            result["hit_rate_at_10"] >= 1.0
            and score > V15_SCORE + 1e-9
        ),
    }


def main() -> None:
    catalog_path = "data/catalog.jsonl"
    samples = load_jsonl("data/public_set.jsonl")
    catalog_pack = catalog_index(catalog_path)
    agent = Agent(catalog_path)
    base_config = dict(agent.cfg)

    attempts = []
    for spec in TRIALS:
        trial = run_trial(agent, base_config, samples, catalog_pack, spec)
        attempts.append(trial)
        print(
            f"{trial['name']}: {trial['metrics']['recommended_technical_score']:.6f} "
            f"({trial['delta_vs_v15']:+.6f}) "
            f"hit={trial['metrics']['hit_rate_at_10']:.3f} "
            f"mrr={trial['metrics']['mrr']:.6f} "
            f"mttc={trial['metrics']['mttc']:.3f}",
            flush=True,
        )

    champion = max(
        attempts,
        key=lambda trial: (
            trial["metrics"]["hit_rate_at_10"] >= 1.0,
            trial["metrics"]["recommended_technical_score"],
        ),
    )
    payload = {
        "dataset": "data/public_set.jsonl",
        "baseline_score": V15_SCORE,
        "champion": champion,
        "attempts": attempts,
    }
    out_path = Path("runs/v8_profile_branch_attempts.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"CHAMPION: {champion['name']} {champion['metrics']}", flush=True)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
