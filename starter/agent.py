"""Conversational product-search agent (v2.0, Bayesian inverse inference).

## One-line summary

Instead of treating user utterances as query strings, each catalog product is a
**hypothesis**. We replay the public customer simulator to predict what the user
*should* say if that product were the target, then update beliefs with what we
actually hear. Questions and submissions are chosen by expected-score dynamic
programming.

## Four components

    user_model.py     Customer generative model: product -> utterance (invertible)
    catalog_index.py  Intent cards, review-count prior, inverted indexes (50k items)
    belief.py         Posterior P(target = p | dialogue); positive / negative / elimination evidence
    policy.py         Optimal-experiment question choice + optimal-stopping submission schedule

## Key differences vs v1.5

| Stage      | v1.5                              | v2.0                                      |
| ---------- | --------------------------------- | ----------------------------------------- |
| Ranking    | ~20 hand-tuned additive weights   | Posterior = prior × likelihood            |
| Prior      | Weak rating / review boost        | Proportional to review count (sampling)   |
| Questions  | Fixed attribute order             | Expected information gain each turn       |
| Submit     | Empty list early turns            | DP-optimal list length                    |
| Miss       | Dedup exclusion only              | Deterministic evidence in posterior       |

## Cost profile

Zero external calls, zero tokens, standard library only. Index built once at
startup; per-turn decisions are millisecond-scale in-memory computation.
"""

from __future__ import annotations

from .belief import Belief
from .catalog_index import CatalogIndex
from .config import VERSION, active_config
from .policy import (
    choose_ask,
    choose_submission,
    compose_message,
    future_utilities,
    scoring_horizon,
)
from .user_model import TOP_K


class _Session:
    """Per-dialogue mutable state."""

    __slots__ = ("belief", "profile", "last_ask", "last_recs", "last_turn", "last_scoreable", "started")

    def __init__(self, belief: Belief, profile: dict) -> None:
        self.belief = belief
        self.profile = profile
        self.last_ask: str | None = None
        self.last_recs: list[str] = []
        self.last_turn = 0
        self.last_scoreable = False
        self.started = False


class Agent:
    """Official evaluator interface: reset / respond."""

    version = VERSION

    def __init__(self, catalog_path: str = "data/catalog.jsonl", index: CatalogIndex | None = None,
                 config: dict | None = None) -> None:
        # index / config are optional for local sweeps to reuse a built index;
        # official evaluation uses the default branches.
        self.cfg = dict(active_config()) if config is None else dict(config)
        self.index = index if index is not None else CatalogIndex(catalog_path)
        self._sessions: dict[str, _Session] = {}

    # -- Public API -----------------------------------------------------------

    def reset(self, session_id: str, user_profile: dict) -> None:
        """Start a new session with a fresh belief state."""
        belief = Belief(
            self.index,
            pool_size=int(self.cfg.get("pool_size", 400)),
            temperature=float(self.cfg.get("temperature", 1.0)),
            leak_gap=float(self.cfg.get("leak_gap", 9.0)),
        )
        self._sessions[session_id] = _Session(belief, user_profile or {})

    def respond(self, session_id: str, user_message: str, turn: int, top_k: int) -> dict:
        """Produce the next agent turn: message, optional question, and recommendations."""
        session = self._sessions.get(session_id)
        if session is None:
            self.reset(session_id, {})
            session = self._sessions[session_id]
        belief = session.belief
        limit = min(int(top_k or TOP_K), TOP_K)

        self._ingest(session, user_message)

        pids, probs, _leak = belief.posterior()
        scoreable = belief.override_applied
        horizon = scoring_horizon(turn, scoreable)
        ask, groups = (
            choose_ask(self.index, belief, pids, probs, turn, horizon)
            if self.cfg.get("ask", True)
            else (None, {})
        )

        if not scoreable:
            length = 0
        elif self.cfg.get("sequential", True):
            future = future_utilities(groups, dict(zip(pids, probs)), horizon)
            length = choose_submission(pids, turn, future, scoreable)
        else:
            length = limit
        length = min(length, limit, len(pids))

        recommendations = [{"parent_asin": self.index.asins[pid]} for pid in pids[:length]]
        session.last_ask = ask
        session.last_recs = [item["parent_asin"] for item in recommendations]
        session.last_scoreable = scoreable
        session.last_turn = turn

        return {
            "message": compose_message(ask, length),
            "ask_attribute": ask,
            "recommendations": recommendations,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    # -- Internal -------------------------------------------------------------

    def _ingest(self, session: _Session, user_message: str) -> None:
        """Merge this turn's utterance (and prior miss evidence) into belief."""
        belief = session.belief
        if not session.started:
            session.started = True
            belief.observe_opening(user_message)
            return
        # Called again => last turn's recommendations did not hit the target.
        # Negative evidence is valid only when that turn was actually scoreable
        # (intent-override sessions are not scored until the override arrives).
        # belief.safe_from_turn raises the bar when scenario is uncertain.
        if (
            self.cfg.get("eliminate", True)
            and session.last_recs
            and session.last_scoreable
            and session.last_turn >= belief.safe_from_turn
        ):
            belief.eliminate(session.last_recs)
        belief.observe_turn(user_message, session.last_ask)
