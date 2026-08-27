from collections import Counter, defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import load_jsonl, metric_summary
probe = {s["sample_id"]: s for s in load_jsonl(ROOT / "data" / "customer_probe.jsonl")}
sessions = load_jsonl(ROOT / "local" / "customer_eval" / "transcripts.jsonl")


def attach(session: dict) -> dict:
    src = probe[session["sample_id"]]
    profile = src["user_profile"]
    return {
        **session,
        "combo_group": src["combo_group"],
        "rating_style": profile["rating_style"],
        "n_tags": len(profile["preference_tags"]),
    }


rows = [attach(item) for item in sessions]


def report(title: str, key) -> None:
    groups = defaultdict(list)
    for row in rows:
        groups[key(row)].append(row)
    print(f"=== {title} ===")
    print(f"{'group':<28} {'n':>4} {'hit':>7} {'mrr':>7} {'mttc':>7}")
    for name in sorted(groups, key=lambda item: str(item)):
        metrics = metric_summary(groups[name])
        print(
            f"{str(name):<28} {metrics['sample_count']:>4} "
            f"{metrics['hit_rate_at_10']:>7.3f} {metrics['mrr']:>7.3f} {metrics['mttc']:>7.3f}"
        )
    print()


report("combo_group", lambda row: row["combo_group"])
report("rating_style", lambda row: row["rating_style"])
report("n_tags", lambda row: row["n_tags"])
print("first_hit_turn", dict(sorted(Counter(row["first_hit_turn"] for row in rows).items())))
print("best_rank top", Counter(row["best_rank"] for row in rows).most_common())
