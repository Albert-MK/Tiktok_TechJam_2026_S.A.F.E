"""Generate extra official-format customer profiles by combining allowed fields.

Field vocabulary matches public_set.jsonl:

    purchase_frequency: always "3-4 prior purchases"
    rating_style: usually positive | mixed | critical
    average_prior_rating: 5.0 | 4.0 | 1.0/2.0/3.0 (coupled to style)
    preference_tags: 1-4 of the official tags
    summary: "Prior purchases emphasize {tags}; ratings are {style}."

    python tools/generate_customer_profiles.py
    python -m evaluator.local_evaluator --dataset local/customer_profiles/customer_probe.jsonl --output local/customer_profiles/results.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluator.local_evaluator import load_jsonl

# Order used when writing tags into preference_tags / summary.
TAG_ORDER = (
    "material",
    "fit",
    "comfort",
    "style",
    "durability",
    "performance",
    "warmth",
    "weather",
)
COMMON_TAGS = ("material", "fit", "comfort", "style")
RARE_TAGS = ("durability", "performance", "warmth", "weather")
STYLES = (
    ("usually positive", 5.0),
    ("mixed", 4.0),
    ("critical", 1.0),
    ("critical", 3.0),
)


def ordered_tags(tags: tuple[str, ...] | list[str]) -> list[str]:
    rank = {name: index for index, name in enumerate(TAG_ORDER)}
    return sorted(tags, key=lambda name: rank.get(name, 99))


def make_profile(tags: list[str], rating_style: str, average: float) -> dict:
    return {
        "average_prior_rating": average,
        "preference_tags": tags,
        "purchase_frequency": "3-4 prior purchases",
        "rating_style": rating_style,
        "summary": (
            f"Prior purchases emphasize {', '.join(tags)}; ratings are {rating_style}."
        ),
    }


def profile_key(profile: dict) -> tuple:
    return (
        tuple(profile["preference_tags"]),
        profile["rating_style"],
        profile["average_prior_rating"],
        profile["purchase_frequency"],
    )


def existing_keys(public: list[dict]) -> set[tuple]:
    return {profile_key(sample["user_profile"]) for sample in public}


def add_combo(
    rows: list[dict],
    seen: set[tuple],
    tags: list[str],
    rating_style: str,
    average: float,
    group: str,
    blocked: set[tuple],
) -> None:
    tags = ordered_tags(tags)
    profile = make_profile(tags, rating_style, average)
    key = profile_key(profile)
    if key in seen or key in blocked:
        return
    seen.add(key)
    slug = "-".join(tags)
    rating_slug = rating_style.replace(" ", "_") + f"_{str(average).replace('.', 'p')}"
    rows.append(
        {
            "profile_id": f"combo_{len(rows) + 1:04d}_{slug}_{rating_slug}",
            "combo_group": group,
            "user_profile": profile,
        }
    )


def build_combinations(blocked: set[tuple]) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple] = set()

    # 1. Every official tag alone, across rating styles.
    for tag in TAG_ORDER:
        for style, average in STYLES:
            add_combo(rows, seen, [tag], style, average, "single_tag", blocked)

    # 2. Pairs that include an underused tag (durability / performance / warmth / weather).
    for rare in RARE_TAGS:
        for other in TAG_ORDER:
            if other == rare:
                continue
            for style, average in STYLES:
                add_combo(rows, seen, [rare, other], style, average, "rare_pair", blocked)

    # 3. Common two-tag pairs (the public set repeats material+fit a lot; cover the rest).
    for pair in combinations(COMMON_TAGS, 2):
        for style, average in STYLES:
            add_combo(rows, seen, list(pair), style, average, "common_pair", blocked)

    # 4. Three-tag mixes of common + rare, which public_set barely covers.
    for rare in RARE_TAGS:
        for pair in combinations(COMMON_TAGS, 2):
            for style, average in (("usually positive", 5.0), ("critical", 1.0)):
                add_combo(rows, seen, [*pair, rare], style, average, "common_plus_rare_triple", blocked)

    # 5. Official four-tag shape with each rating personality.
    four = ["material", "fit", "comfort", "style"]
    for style, average in STYLES:
        add_combo(rows, seen, four, style, average, "core_quad", blocked)

    # 6. Edge tag from the public set, kept in official template form.
    for style, average in STYLES:
        add_combo(rows, seen, ["general shopping"], style, average, "general_shopping", blocked)

    return rows


def bind_to_public(profiles: list[dict], public: list[dict]) -> list[dict]:
    sessions = []
    for index, item in enumerate(profiles):
        base = public[index % len(public)]
        sessions.append(
            {
                "sample_id": item["profile_id"],
                "source_sample_id": base["sample_id"],
                "combo_group": item["combo_group"],
                "scenario_type": base["scenario_type"],
                "difficulty_bucket": base["difficulty_bucket"],
                "category_bucket": base["category_bucket"],
                "ground_truth": {"parent_asin": base["ground_truth"]["parent_asin"]},
                "user_profile": item["user_profile"],
            }
        )
    return sessions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate official-format customer profile combinations.")
    parser.add_argument("--public-set", default=str(ROOT / "data" / "public_set.jsonl"))
    parser.add_argument("--profiles", default=str(ROOT / "local" / "customer_profiles" / "customer_profiles.jsonl"))
    parser.add_argument("--sessions", default=str(ROOT / "local" / "customer_profiles" / "customer_probe.jsonl"))
    parser.add_argument("--manifest", default=str(ROOT / "local" / "customer_profiles" / "manifest.json"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    public = load_jsonl(args.public_set)
    blocked = existing_keys(public)
    profiles = build_combinations(blocked)
    sessions = bind_to_public(profiles, public)

    for path, rows in ((args.profiles, profiles), (args.sessions, sessions)):
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    manifest = {
        "n_profiles": len(profiles),
        "n_sessions": len(sessions),
        "skipped_already_in_public_set": len(blocked),
        "format": {
            "purchase_frequency": "3-4 prior purchases",
            "rating_style": ["usually positive", "mixed", "critical"],
            "average_prior_rating": [5.0, 4.0, 3.0, 1.0],
            "preference_tags": list(TAG_ORDER) + ["general shopping"],
            "summary_template": "Prior purchases emphasize {tags}; ratings are {rating_style}.",
        },
        "combo_group_counts": dict(Counter(item["combo_group"] for item in profiles)),
        "rating_style_counts": dict(Counter(item["user_profile"]["rating_style"] for item in profiles)),
        "n_tags_counts": dict(Counter(len(item["user_profile"]["preference_tags"]) for item in profiles)),
        "note": (
            "customer_profiles.jsonl is the profile library. "
            "customer_probe.jsonl wraps each profile onto a public_set product so the official evaluator can run."
        ),
    }
    Path(args.manifest).write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    print(f"\nWrote {args.profiles}")
    print(f"Wrote {args.sessions}")
    print(f"Wrote {args.manifest}")


if __name__ == "__main__":
    main()
