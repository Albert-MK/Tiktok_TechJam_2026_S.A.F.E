"""v1.3 之后的三个方向实验：动态提问、弱约束延迟交卷、轻量商品相似度。

验收：Hit@10 必须保持 1.0，TechnicalScore 必须严格高于 v1.3。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ.pop("AGENT_EXP_FLAGS", None)
os.environ["AGENT_STRATEGY"] = "final"

from evaluator.local_evaluator import catalog_index, evaluate, load_jsonl
from starter.agent import Agent


V13_SCORE = 0.897858
SINGLE_TRIALS = [
    {
        "name": "skip_covered_attrs",
        "flags": {"skip_covered_attrs": True},
        "direction": "dynamic_ask",
        "method": "Skip typed questions whose attribute type is already in disclosed constraints.",
    },
    {
        "name": "dynamic_typed_ask",
        "flags": {"dynamic_typed_ask": True},
        "direction": "dynamic_ask",
        "method": "After other, ask the typed attribute that best splits the current candidate branch.",
    },
    {
        "name": "skip_covered__dynamic_typed",
        "flags": {"skip_covered_attrs": True, "dynamic_typed_ask": True},
        "direction": "dynamic_ask",
        "method": "Skip covered types, then pick the remaining typed ask by candidate split.",
    },
    {
        "name": "ask_mode_feature_first",
        "flags": {"ask_mode": "feature_first"},
        "direction": "dynamic_ask",
        "method": "Static reorder: ask feature/style before material after the first other question.",
    },
    {
        "name": "feature_first__skip_covered",
        "flags": {"ask_mode": "feature_first", "skip_covered_attrs": True},
        "direction": "dynamic_ask",
        "method": "Feature-first order plus skip already-covered typed attributes.",
    },
    {
        "name": "delay_weak_recs",
        "flags": {"delay_weak_recs": True},
        "direction": "delay_rank",
        "method": "Withhold Top-10 on browsing/boundary turn 1 when no distinctive constraint exists.",
    },
    {
        "name": "delay_generic_first",
        "flags": {"delay_generic_first": True},
        "direction": "delay_rank",
        "method": "Withhold Top-10 on any scenario's first turn when no distinctive constraint exists.",
    },
    *[
        {
            "name": f"shown_dissimilarity_{value:g}",
            "flags": {"shown_dissimilarity_weight": value},
            "direction": "similarity",
            "method": "Penalize candidates whose feature tokens overlap already-shown misses.",
        }
        for value in (0.5, 1.0, 2.0, 4.0, 8.0)
    ],
    *[
        {
            "name": f"neighbor_overlap_{value:g}",
            "flags": {"neighbor_overlap_weight": value},
            "direction": "similarity",
            "method": "Boost candidates similar to distinctive-constraint anchors via entry Jaccard.",
        }
        for value in (0.5, 1.0, 2.0, 4.0)
    ],
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
        "delta_vs_v13": round(score - V13_SCORE, 6),
        "eligible_vs_v13": eligible(result, V13_SCORE),
    }


def main() -> None:
    catalog_path = "data/catalog.jsonl"
    samples = load_jsonl("data/public_set.jsonl")
    catalog_pack = catalog_index(catalog_path)
    agent = Agent(catalog_path)
    base_config = dict(agent.cfg)

    baseline = run_trial(
        agent,
        base_config,
        samples,
        catalog_pack,
        {
            "name": "v1.3_recheck",
            "flags": {},
            "direction": "baseline",
            "method": "Current v1.3 default strategy.",
        },
    )
    attempts = [baseline]
    print(
        f"{baseline['name']}: {baseline['metrics']['recommended_technical_score']:.6f} "
        f"hit={baseline['metrics']['hit_rate_at_10']:.3f} "
        f"mrr={baseline['metrics']['mrr']:.6f} "
        f"mttc={baseline['metrics']['mttc']:.3f}",
        flush=True,
    )

    for spec in SINGLE_TRIALS:
        trial = run_trial(agent, base_config, samples, catalog_pack, spec)
        attempts.append(trial)
        print(
            f"{trial['name']}: {trial['metrics']['recommended_technical_score']:.6f} "
            f"({trial['delta_vs_v13']:+.6f}) "
            f"hit={trial['metrics']['hit_rate_at_10']:.3f} "
            f"mrr={trial['metrics']['mrr']:.6f} "
            f"mttc={trial['metrics']['mttc']:.3f}",
            flush=True,
        )

    winners = [
        trial
        for trial in attempts
        if trial["name"] != "v1.3_recheck" and eligible(trial["metrics"], V13_SCORE)
    ]
    combo_specs = []
    if len(winners) >= 2:
        by_direction: dict[str, dict] = {}
        for trial in winners:
            direction = trial["direction"]
            current = by_direction.get(direction)
            if current is None or (
                trial["metrics"]["recommended_technical_score"]
                > current["metrics"]["recommended_technical_score"]
            ):
                by_direction[direction] = trial
        directions = list(by_direction.values())
        if len(directions) >= 2:
            flags: dict = {}
            names = []
            for trial in directions:
                flags.update(trial["flags"])
                names.append(trial["name"])
            combo_specs.append(
                {
                    "name": "combo__" + "__".join(names),
                    "flags": flags,
                    "direction": "combo",
                    "method": "Combine the best eligible variant from each direction.",
                }
            )

    for spec in combo_specs:
        trial = run_trial(agent, base_config, samples, catalog_pack, spec)
        attempts.append(trial)
        print(
            f"{trial['name']}: {trial['metrics']['recommended_technical_score']:.6f} "
            f"({trial['delta_vs_v13']:+.6f})",
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
        "catalog": catalog_path,
        "baseline_score": V13_SCORE,
        "acceptance_rule": "Hit@10 must remain 1.0 and TechnicalScore must strictly improve over v1.3.",
        "champion": champion,
        "adopt_new_version": eligible(champion["metrics"], V13_SCORE),
        "attempts": attempts,
    }
    out_path = Path("runs/v5_direction_attempts.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"CHAMPION: {champion['name']} {champion['metrics']}", flush=True)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
