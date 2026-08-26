"""Run the official scoring loop and save full dialogue transcripts.

Does not modify evaluator/local_evaluator.py. Scoring logic mirrors the
official public-set evaluator so metrics stay comparable.

Each run overwrites the previous files in --output-dir (default: runs/latest).

Examples:
  python evaluate_with_transcripts.py
  python evaluate_with_transcripts.py --limit 8
  python evaluate_with_transcripts.py --sample-id public_0001
"""

from __future__ import annotations

import argparse
import json
import shutil
import uuid
from collections import defaultdict
from pathlib import Path

from starter.agent import Agent
from evaluator.local_evaluator import (
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    metric_summary,
    normalize_recommendations,
)


def evaluate_with_transcripts(
    agent: Agent,
    samples: list[dict],
    catalog_ids: set[str],
    categories: dict[str, list[str]],
    products: dict[str, dict],
) -> dict:
    sessions: list[dict] = []
    transcripts: list[dict] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0

    for sample in samples:
        session_id = f"public_{uuid.uuid4().hex}"
        agent.reset(session_id, sample["user_profile"])
        target = str(sample["ground_truth"]["parent_asin"])
        product = products.get(target, {})
        effective_intent_card, effective_behavior = materialize_hidden_fields(sample, products)
        effective_sample = {
            **sample,
            "intent_card": effective_intent_card,
            "behavior": effective_behavior,
        }
        disclosed: set[str] = set()
        boundary_used = False
        override_applied = sample["scenario_type"] != "intent_override"
        user_message = initial_message(
            effective_sample,
            coarse_category(categories.get(target, [])),
            disclosed,
        )
        hit_turn: int | None = None
        best_rank: int | None = None
        turns: list[dict] = []

        for turn in range(1, MAX_TURNS + 1):
            turn_record: dict = {
                "turn": turn,
                "user_message": user_message,
                "override_applied_before_respond": override_applied,
            }
            error: str | None = None
            try:
                response = agent.respond(session_id, user_message, turn, TOP_K)
            except Exception as exc:  # noqa: BLE001 - mirror official evaluator
                response = {"message": "", "ask_attribute": None, "recommendations": []}
                error = f"{type(exc).__name__}: {exc}"

            if not isinstance(response, dict) or not isinstance(response.get("message"), str):
                response = {"message": "", "ask_attribute": None, "recommendations": []}
                error = error or "invalid_response_shape"

            usage = response.get("usage")
            prompt_tokens = 0
            completion_tokens = 0
            if isinstance(usage, dict):
                if isinstance(usage.get("prompt_tokens"), int) and usage["prompt_tokens"] >= 0:
                    prompt_tokens = usage["prompt_tokens"]
                    total_prompt_tokens += prompt_tokens
                if isinstance(usage.get("completion_tokens"), int) and usage["completion_tokens"] >= 0:
                    completion_tokens = usage["completion_tokens"]
                    total_completion_tokens += completion_tokens

            ranked = normalize_recommendations(response.get("recommendations"), catalog_ids)
            target_rank = ranked.index(target) + 1 if target in ranked else None
            scored_hit = bool(override_applied and target_rank is not None)

            turn_record.update(
                {
                    "agent_message": response.get("message"),
                    "ask_attribute": response.get("ask_attribute"),
                    "recommendations": ranked,
                    "target_in_recommendations": target in ranked,
                    "target_rank": target_rank,
                    "scored_hit": scored_hit,
                    "usage": {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                    },
                    "error": error,
                }
            )
            turns.append(turn_record)

            if scored_hit:
                best_rank = target_rank
                hit_turn = turn
                break
            if turn == MAX_TURNS:
                break

            override = effective_sample.get("behavior", {}).get("override") or {}
            if not override_applied and turn + 1 == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                user_message = str(
                    override.get("message", "Actually, please ignore my earlier preference.")
                )
                turns[-1]["next_user_trigger"] = "intent_override"
            else:
                user_message, boundary_used = customer_reply(
                    effective_sample,
                    response.get("ask_attribute"),
                    disclosed,
                    boundary_used,
                )
                turns[-1]["next_user_trigger"] = "customer_reply"

        session_summary = {
            "sample_id": sample["sample_id"],
            "scenario_type": sample["scenario_type"],
            "hit": hit_turn is not None,
            "first_hit_turn": hit_turn,
            "best_rank": best_rank,
            "reciprocal_rank": 0.0 if best_rank is None else 1.0 / best_rank,
        }
        sessions.append(session_summary)
        transcripts.append(
            {
                **session_summary,
                "session_id": session_id,
                "target_parent_asin": target,
                "target_title": str(product.get("title") or "")[:200],
                "user_profile": sample.get("user_profile"),
                "intent_card": effective_intent_card,
                "behavior": effective_behavior,
                "turns": turns,
            }
        )

    overall = metric_summary(sessions)
    efficiency = max(0.0, min(1.0, (11.0 - float(overall["mttc"])) / 10.0))
    technical_score = (
        0.50 * overall["hit_rate_at_10"] + 0.30 * overall["mrr"] + 0.20 * efficiency
    )
    grouped: dict[str, list[dict]] = defaultdict(list)
    for session in sessions:
        grouped[session["scenario_type"]].append(session)

    return {
        **overall,
        "efficiency": round(efficiency, 6),
        "recommended_technical_score": round(technical_score, 6),
        "reported_token_usage": {
            "prompt_tokens": total_prompt_tokens,
            "completion_tokens": total_completion_tokens,
            "total_tokens": total_prompt_tokens + total_completion_tokens,
        },
        "scenario_metrics": {name: metric_summary(grouped[name]) for name in sorted(grouped)},
        "sessions": sessions,
        "transcripts": transcripts,
    }


def render_readable_transcript(transcript: dict) -> str:
    lines = [
        f"sample_id: {transcript['sample_id']}",
        f"scenario_type: {transcript['scenario_type']}",
        f"target: {transcript['target_parent_asin']}",
        f"title: {transcript.get('target_title', '')}",
        f"hit: {transcript['hit']} | first_hit_turn: {transcript['first_hit_turn']} | "
        f"best_rank: {transcript['best_rank']}",
        "-" * 72,
    ]
    for turn in transcript["turns"]:
        lines.append(f"[Turn {turn['turn']}] USER: {turn['user_message']}")
        lines.append(f"[Turn {turn['turn']}] AGENT: {turn['agent_message']}")
        lines.append(f"[Turn {turn['turn']}] ask_attribute: {turn['ask_attribute']}")
        lines.append(f"[Turn {turn['turn']}] recommendations: {turn['recommendations']}")
        lines.append(
            f"[Turn {turn['turn']}] target_rank: {turn['target_rank']} | "
            f"scored_hit: {turn['scored_hit']}"
        )
        if turn.get("error"):
            lines.append(f"[Turn {turn['turn']}] error: {turn['error']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _clear_previous_run(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name in ("metrics.json", "results.json", "transcripts.jsonl", "README.md"):
        path = output_dir / name
        if path.is_file():
            path.unlink()
    txt_dir = output_dir / "transcripts_txt"
    if txt_dir.exists():
        shutil.rmtree(txt_dir)


def save_run(result: dict, output_dir: Path) -> None:
    _clear_previous_run(output_dir)
    transcripts = result["transcripts"]

    metrics = {key: value for key, value in result.items() if key != "transcripts"}
    (output_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (output_dir / "results.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    with (output_dir / "transcripts.jsonl").open("w", encoding="utf-8") as handle:
        for item in transcripts:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    readable_dir = output_dir / "transcripts_txt"
    readable_dir.mkdir(parents=True, exist_ok=True)
    for item in transcripts:
        path = readable_dir / f"{item['sample_id']}_{item['scenario_type']}.txt"
        path.write_text(render_readable_transcript(item), encoding="utf-8")

    index_lines = [
        "# Dialogue transcript index",
        "",
        f"- sessions: {len(transcripts)}",
        f"- hit_rate_at_10: {result['hit_rate_at_10']}",
        f"- mrr: {result['mrr']}",
        f"- mttc: {result['mttc']}",
        f"- technical_score: {result['recommended_technical_score']}",
        "",
        "| sample_id | scenario | hit | turn | rank | file |",
        "|-----------|----------|-----|------|------|------|",
    ]
    for item in transcripts:
        index_lines.append(
            f"| {item['sample_id']} | {item['scenario_type']} | {item['hit']} | "
            f"{item['first_hit_turn']} | {item['best_rank']} | "
            f"transcripts_txt/{item['sample_id']}_{item['scenario_type']}.txt |"
        )
    (output_dir / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate the starter Agent and save full dialogue transcripts."
    )
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument(
        "--output-dir",
        default="runs/latest",
        help="Directory for this run. Previous files in this directory are overwritten.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Only evaluate first N samples.")
    parser.add_argument(
        "--sample-id",
        action="append",
        default=[],
        help="Only evaluate these sample_id values (repeatable).",
    )
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="Only evaluate these scenario_type values (repeatable).",
    )
    return parser.parse_args()


def filter_samples(samples: list[dict], args: argparse.Namespace) -> list[dict]:
    selected = samples
    if args.sample_id:
        wanted = set(args.sample_id)
        selected = [sample for sample in selected if sample.get("sample_id") in wanted]
    if args.scenario:
        wanted_scenarios = {item.lower() for item in args.scenario}
        selected = [
            sample
            for sample in selected
            if str(sample.get("scenario_type", "")).lower() in wanted_scenarios
        ]
    if args.limit and args.limit > 0:
        selected = selected[: args.limit]
    return selected


def main() -> None:
    args = parse_args()
    samples = filter_samples(load_jsonl(args.dataset), args)
    if not samples:
        raise SystemExit("No samples selected. Check --sample-id / --scenario / --limit.")

    output_dir = Path(args.output_dir)

    catalog_ids, categories, products = catalog_index(args.catalog)
    result = evaluate_with_transcripts(
        Agent(args.catalog),
        samples,
        catalog_ids,
        categories,
        products,
    )
    save_run(result, output_dir)

    summary = {key: value for key, value in result.items() if key not in {"sessions", "transcripts"}}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nSaved metrics + transcripts to: {output_dir.resolve()}")
    print(f"  - {output_dir / 'metrics.json'}")
    print(f"  - {output_dir / 'transcripts.jsonl'}")
    print(f"  - {output_dir / 'transcripts_txt'}")
    print(f"  - {output_dir / 'README.md'}")


if __name__ == "__main__":
    main()
