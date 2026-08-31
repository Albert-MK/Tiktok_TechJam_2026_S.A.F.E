"""Strategy configuration and experiment presets.

v2.0 exposes far fewer tunables than v1.5: ranking is driven by prior × likelihood
Bayesian inference, and ask/submit decisions by dynamic programming. Only a handful
of calibration knobs remain.

For local sweeps, override via environment variable:

    AGENT_EXP_FLAGS='{"temperature": 3.0}' python -m evaluator.local_evaluator
"""

from __future__ import annotations

import json
import os

VERSION = "v2.0"
STRATEGY = os.environ.get("AGENT_STRATEGY", "bayes").strip().lower()

PRESETS = {
    # Production recipe: full inverse simulation + Bayesian posterior + DP policy.
    "bayes": {
        "pool_size": 400,        # Max candidates kept in the belief pool
        "temperature": 1.0,      # Posterior softening; higher => less aggressive bets
        "leak_gap": 9.0,         # Log-penalty for "target not in candidate pool"
        "sequential": True,      # Single-guess-per-turn submission (False => batch Top-10)
        "eliminate": True,       # Use "shown but missed => definitely not target"
        "ask": True,             # Allow clarification questions
    },
    # Ablation: no sequential betting; submit full Top-10 every turn.
    "batch": {
        "pool_size": 400,
        "temperature": 1.0,
        "leak_gap": 9.0,
        "sequential": False,
        "eliminate": True,
        "ask": True,
    },
    # Ablation: disable miss-based elimination.
    "no_elimination": {
        "pool_size": 400,
        "temperature": 1.0,
        "leak_gap": 9.0,
        "sequential": True,
        "eliminate": False,
        "ask": True,
    },
    # Ablation: no questions; rely on opening message only.
    "no_ask": {
        "pool_size": 400,
        "temperature": 1.0,
        "leak_gap": 9.0,
        "sequential": True,
        "eliminate": True,
        "ask": False,
    },
}


def active_config() -> dict:
    cfg = dict(PRESETS.get(STRATEGY, PRESETS["bayes"]))
    raw = os.environ.get("AGENT_EXP_FLAGS", "").strip()
    if raw:
        try:
            extra = json.loads(raw)
            if isinstance(extra, dict):
                cfg.update(extra)
        except json.JSONDecodeError:
            pass
    return cfg
