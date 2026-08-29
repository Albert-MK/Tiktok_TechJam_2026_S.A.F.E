"""v1.4 之后：多轮延迟交卷 vs 微调 BM25 字段权重。

验收：Hit@10 必须保持 1.0，TechnicalScore 必须严格高于 v1.4。
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


V14_SCORE = 0.911382
DEFAULT_BM25 = [6.0, 4.0, 2.5, 2.5, 1.5, 1.0]


def bm25(title=6.0, categories=4.0, features=2.5, details=2.5, store=1.5, description=1.0) -> list[float]:
    return [title, categories, features, details, store, description]


SINGLE_TRIALS = [
    {
        "name": "delay_until_distinctive_max2",
        "flags": {"delay_until_distinctive": True, "delay_max_empty": 2},
        "direction": "delay",
        "method": "Keep withholding Top-10 until a distinctive constraint exists, cap 2 empty turns.",
    },
    {
        "name": "delay_until_distinctive_max3",
        "flags": {"delay_until_distinctive": True, "delay_max_empty": 3},
        "direction": "delay",
        "method": "Same as distinctive delay, but allow 3 empty turns.",
    },
    {
        "name": "delay_until_2_constraints",
        "flags": {"delay_until_n_constraints": 2, "delay_max_empty": 2},
        "direction": "delay",
        "method": "Withhold while fewer than 2 disclosed constraints, cap 2 empty turns.",
    },
    {
        "name": "delay_until_3_constraints",
        "flags": {"delay_until_n_constraints": 3, "delay_max_empty": 2},
        "direction": "delay",
        "method": "Withhold while fewer than 3 disclosed constraints, cap 2 empty turns.",
    },
    {
        "name": "delay_uncertain_m1_max2",
        "flags": {"delay_uncertain": True, "delay_min_margin": 1.0, "delay_max_empty": 2},
        "direction": "delay",
        "method": "Delay when top-1 vs top-2 rerank margin is under 1.0.",
    },
    {
        "name": "delay_uncertain_m2_max2",
        "flags": {"delay_uncertain": True, "delay_min_margin": 2.0, "delay_max_empty": 2},
        "direction": "delay",
        "method": "Delay when top-1 vs top-2 rerank margin is under 2.0.",
    },
    {
        "name": "delay_uncertain_m4_max2",
        "flags": {"delay_uncertain": True, "delay_min_margin": 4.0, "delay_max_empty": 2},
        "direction": "delay",
        "method": "Delay when top-1 vs top-2 rerank margin is under 4.0.",
    },
    {
        "name": "delay_uncertain_m2_max3",
        "flags": {"delay_uncertain": True, "delay_min_margin": 2.0, "delay_max_empty": 3},
        "direction": "delay",
        "method": "Uncertain-margin delay with a 3-empty-turn cap.",
    },
    {
        "name": "delay_distinctive_or_uncertain_max2",
        "flags": {
            "delay_until_distinctive": True,
            "delay_uncertain": True,
            "delay_min_margin": 2.0,
            "delay_max_empty": 2,
        },
        "direction": "delay",
        "method": "Delay until distinctive or until the top-2 margin is at least 2.0.",
    },
    *[
        {
            "name": name,
            "flags": {"bm25_field_weights": weights},
            "direction": "bm25",
            "method": method,
        }
        for name, weights, method in (
            ("bm25_title_4", bm25(title=4.0), "Lower title BM25 weight."),
            ("bm25_title_8", bm25(title=8.0), "Raise title BM25 weight."),
            ("bm25_title_10", bm25(title=10.0), "Stronger title BM25 weight."),
            ("bm25_cat_2", bm25(categories=2.0), "Lower category BM25 weight."),
            ("bm25_cat_6", bm25(categories=6.0), "Raise category BM25 weight."),
            ("bm25_feat_4", bm25(features=4.0), "Raise features BM25 weight."),
            ("bm25_feat_6", bm25(features=6.0), "Stronger features BM25 weight."),
            ("bm25_feat_8", bm25(features=8.0), "Heaviest features BM25 weight."),
            ("bm25_details_4", bm25(details=4.0), "Raise details BM25 weight."),
            ("bm25_details_6", bm25(details=6.0), "Stronger details BM25 weight."),
            ("bm25_store_0p5", bm25(store=0.5), "Lower store BM25 weight."),
            ("bm25_store_3", bm25(store=3.0), "Raise store BM25 weight."),
            ("bm25_desc_0p5", bm25(description=0.5), "Lower description BM25 weight."),
            ("bm25_desc_2", bm25(description=2.0), "Raise description BM25 weight."),
            ("bm25_feat_details_4", bm25(features=4.0, details=4.0), "Raise both features and details."),
            ("bm25_title8_feat4", bm25(title=8.0, features=4.0), "Raise title and features together."),
            ("bm25_title4_feat6", bm25(title=4.0, features=6.0), "Shift weight from title toward features."),
        )
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
        "delta_vs_v14": round(score - V14_SCORE, 6),
        "eligible_vs_v14": eligible(result, V14_SCORE),
    }


def main() -> None:
    catalog_path = "data/catalog.jsonl"
    samples = load_jsonl("data/public_set.jsonl")
    catalog_pack = catalog_index(catalog_path)
    agent = Agent(catalog_path)
    base_config = dict(agent.cfg)
    base_config.setdefault("bm25_field_weights", DEFAULT_BM25)

    baseline = run_trial(
        agent,
        base_config,
        samples,
        catalog_pack,
        {
            "name": "v1.4_recheck",
            "flags": {},
            "direction": "baseline",
            "method": "Current v1.4 default strategy.",
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
            f"({trial['delta_vs_v14']:+.6f}) "
            f"hit={trial['metrics']['hit_rate_at_10']:.3f} "
            f"mrr={trial['metrics']['mrr']:.6f} "
            f"mttc={trial['metrics']['mttc']:.3f}",
            flush=True,
        )

    winners = [
        trial
        for trial in attempts
        if trial["name"] != "v1.4_recheck" and eligible(trial["metrics"], V14_SCORE)
    ]
    combo_specs = []
    if winners:
        by_direction: dict[str, dict] = {}
        for trial in winners:
            direction = trial["direction"]
            current = by_direction.get(direction)
            if current is None or (
                trial["metrics"]["recommended_technical_score"]
                > current["metrics"]["recommended_technical_score"]
            ):
                by_direction[direction] = trial
        if len(by_direction) >= 2:
            flags: dict = {}
            names = []
            for trial in by_direction.values():
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
            f"({trial['delta_vs_v14']:+.6f})",
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
        "baseline_score": V14_SCORE,
        "acceptance_rule": "Hit@10 must remain 1.0 and TechnicalScore must strictly improve over v1.4.",
        "champion": champion,
        "adopt_new_version": eligible(champion["metrics"], V14_SCORE),
        "attempts": attempts,
    }
    out_path = Path("runs/v6_delay_bm25_attempts.json")
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"CHAMPION: {champion['name']} {champion['metrics']}", flush=True)
    print(f"Wrote {out_path}", flush=True)


if __name__ == "__main__":
    main()
