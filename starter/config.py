"""Runtime switches for local ablation. Official scoring uses AGENT_STRATEGY env or default."""

from __future__ import annotations

import json
import os


def _flag(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in {"0", "false", "no", "off"}


STRATEGY = os.environ.get("AGENT_STRATEGY", "final").strip().lower()

PRESETS = {
    # Official weak starter behavior, reimplemented behind flags.
    "baseline": {
        "accumulate": False,
        "ask": False,
        "override_reset": False,
        "phrase_rerank": False,
        "profile_boost": False,
        "ask_mode": "typed",
        "retrieve_k": 10,
    },
    # Accumulate all user text into BM25, still never ask.
    "accumulate_only": {
        "accumulate": True,
        "ask": False,
        "override_reset": True,
        "phrase_rerank": False,
        "profile_boost": False,
        "ask_mode": "typed",
        "retrieve_k": 40,
    },
    # Ask typed attributes + accumulate BM25.
    "ask_typed": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "phrase_rerank": False,
        "profile_boost": False,
        "ask_mode": "typed",
        "retrieve_k": 40,
    },
    # Ask "other" first so the simulator can dump remaining constraints.
    "ask_other_first": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "phrase_rerank": False,
        "profile_boost": False,
        "ask_mode": "other_first",
        "retrieve_k": 40,
    },
    # Phrase-aware rerank on a larger candidate pool.
    "hybrid_typed": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "override_keep": True,
        "phrase_rerank": True,
        "profile_boost": False,
        "ask_mode": "typed",
        "retrieve_k": 80,
    },
    "hybrid_other": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "override_keep": False,
        "phrase_rerank": True,
        "profile_boost": False,
        "ask_mode": "other_first",
        "retrieve_k": 80,
    },
    "hybrid_other_keep": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "override_keep": True,
        "phrase_rerank": True,
        "profile_boost": False,
        "ask_mode": "other_first",
        "retrieve_k": 80,
    },
    "hybrid_other_profile": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "override_keep": True,
        "phrase_rerank": True,
        "profile_boost": True,
        "ask_mode": "other_first",
        "retrieve_k": 80,
    },
    "hybrid_other_keep_wide": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "override_keep": True,
        "phrase_rerank": True,
        "profile_boost": True,
        "ask_mode": "other_first",
        "retrieve_k": 150,
    },
    # Kept combination after ablations on the public 200.
    "final": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "override_keep": True,
        "phrase_rerank": True,
        "profile_boost": True,
        "ask_mode": "other_first",
        "retrieve_k": 80,
        "exclude_shown": True,
        "distinctive_exact_bonus": True,
        "category_must_match": True,
    },
}


def active_config() -> dict:
    preset = PRESETS.get(STRATEGY, PRESETS["final"])
    cfg = dict(preset)
    cfg.setdefault("override_keep", False)
    cfg.setdefault("exclude_shown", True)
    if "AGENT_ASK_MODE" in os.environ:
        cfg["ask_mode"] = os.environ["AGENT_ASK_MODE"].strip().lower()
    if "AGENT_RETRIEVE_K" in os.environ:
        cfg["retrieve_k"] = int(os.environ["AGENT_RETRIEVE_K"])
    if "AGENT_ASK" in os.environ:
        cfg["ask"] = _flag("AGENT_ASK")
    if "AGENT_ACCUMULATE" in os.environ:
        cfg["accumulate"] = _flag("AGENT_ACCUMULATE")
    if "AGENT_RERANK" in os.environ:
        cfg["phrase_rerank"] = _flag("AGENT_RERANK")
    if "AGENT_PROFILE" in os.environ:
        cfg["profile_boost"] = _flag("AGENT_PROFILE")
    if "AGENT_OVERRIDE" in os.environ:
        cfg["override_reset"] = _flag("AGENT_OVERRIDE")
    raw_flags = os.environ.get("AGENT_EXP_FLAGS", "").strip()
    if raw_flags:
        try:
            extra = json.loads(raw_flags)
            if isinstance(extra, dict):
                cfg.update(extra)
        except json.JSONDecodeError:
            pass
    for key in (
        "distinctive_exact_bonus",
        "punct_normalize",
        "distinctive_query_focus",
        "title_distinctive_boost",
        "category_must_match",
        "override_clear_old",
        "cover_sort",
    ):
        cfg.setdefault(key, False)
    return cfg
