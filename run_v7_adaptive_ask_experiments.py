"""Compare v1.5 fixed-order asking vs adaptive candidate-narrowing ask logic."""

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
        "name": "adaptive_narrow",
        "flags": {"ask_mode": "adaptive_narrow"},
        "method": "After other, ask the typed attribute with highest entropy on active candidates.",
    },
    {
        "name": "adaptive_narrow_stop15",
        "flags": {"ask_mode": "adaptive_narrow", "narrow_stop_candidates": 15},
        "method": "Adaptive narrow ask; stop questioning once active branch has <=15 items.",
    },
    {
        "name": "adaptive_narrow_stop20",
        "flags": {"ask_mode": "adaptive_narrow", "narrow_stop_candidates": 20},
        "method": "Adaptive narrow ask; stop questioning once active branch has <=20 items.",
    },
    {
        "name": "adaptive_narrow_no_filter",
        "flags": {"ask_mode": "adaptive_narrow", "narrow_filter_active": False},
        "method": "Entropy on raw rerank pool without constraint hard-filter.",
    },
    {
        "name": "dynamic_typed_v1.5",
        "flags": {"dynamic_typed_ask": True},
        "method": "v1.5 plus legacy dynamic typed split (v5 experiment).",
    },
    {
        "name": "adaptive_narrow_no_delay",
        "flags": {
            "ask_mode": "adaptive_narrow",
            "delay_generic_first": False,
            "delay_until_n_constraints": 0,
            "delay_max_empty": 0,
        },
        "method": "Adaptive ask only, without v1.4/v1.5 delay rules.",
    },
    {
        "name": "adaptive_narrow_stop15_no_delay",
        "flags": {
            "ask_mode": "adaptive_narrow",
            "narrow_stop_candidates": 15,
            "delay_generic_first": False,
            "delay_until_n_constraints": 0,
            "delay_max_empty": 0,
        },
        "method": "Adaptive ask + early stop, no delay rules.",
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
    out_path = Path("runs/v7_adaptive_ask_attempts.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"CHAMPION: {champion['name']} {champion['metrics']}", flush=True)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
