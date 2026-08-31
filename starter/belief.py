"""Belief state: maintain a posterior over which catalog product is the target.

## Core idea

For each candidate product p after every utterance, ask the counterfactual:

    "If p were the target, what should the customer say this turn?"

Replay the public generative model via `user_model`, compare prediction to
observation, and accumulate penalty terms:

    log P(p | dialogue) = log prior(p) - sum of turn penalties

Three evidence types converge here:

* **Positive**: disclosed constraints matched against p's intent card.
* **Negative**: customer says "no more preference for this attribute" — rules out
  candidates that would still have something to say.
* **Elimination**: last turn's recommendations missed => those products are
  definitively not the target (exact ID match in the evaluator). Free, lossless
  information that retrieval-style agents typically discard.

## Why penalties are soft

All penalties are finite; nothing hard-filters the pool. If organizers swap intent
card sources or paraphrase wording, candidates never vanish — match quality drops
smoothly and scoring degrades to lexical similarity + prior, i.e. a reasonable
retrieval fallback.
"""

from __future__ import annotations

import math

from .catalog_index import CatalogIndex, tokenize
from .user_model import (
    SCENARIO_BROWSING,
    SCENARIO_BUYING,
    SCENARIO_OVERRIDE,
    SCENARIO_UNKNOWN,
    parse_opening,
    parse_reply,
    payload_fragments,
    render_reply,
    simulate_reply,
)

# Penalty weights (log-likelihood scale). Prior log1p(review_count) peaks ~13,
# so a single constraint mismatch must exceed that span for evidence to dominate popularity.
W_CONSTRAINT = 22.0      # One constraint completely mismatched
W_REPLY = 30.0           # Whole reply mismatched (typically 1–2 constraints)
W_SILENT = 26.0          # Customer spoke but candidate predicts silence
W_CATEGORY_FLAT = 20.0   # Flat penalty for wrong coarse category
W_CATEGORY = 14.0          # Graded category similarity penalty
W_NONE = 16.0            # Customer said "no preference" but candidate still has more to say
ORDER_DISCOUNT = 0.45    # Similarity retained when content matches but slot order differs
CONTAINMENT_SIM = 0.6    # Floor when constraint text appears verbatim in product blob
COVERAGE_CAP = 0.9       # Max match from IDF-weighted keyword coverage (paraphrase path)
LEXICAL_RESCUE_PENALTY = 15.0  # Trigger lexical fallback when best penalty exceeds this
BROWSING_PRIOR_MATCH = 0.35    # Baseline when opening scenario is unknown and browsing assumed


def similarity(a: str, b: str) -> float:
    """Constraint text similarity in [0, 1], tolerant to paraphrase."""
    if a == b:
        return 1.0
    la, lb = a.lower(), b.lower()
    if la == lb:
        return 0.98
    if la in lb or lb in la:
        return 0.85
    ta, tb = set(tokenize(la)), set(tokenize(lb))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


class Candidate:
    """One product hypothesis with accumulated penalty and disclosed constraints."""

    __slots__ = ("pid", "penalty", "disclosed")

    def __init__(self, pid: int, penalty: float, disclosed: frozenset[str]) -> None:
        self.pid = pid
        self.penalty = penalty
        self.disclosed = disclosed


class Belief:
    """Belief state for a single dialogue session."""

    def __init__(self, index: CatalogIndex, pool_size: int = 400, temperature: float = 1.0,
                 leak_gap: float = 9.0) -> None:
        self.index = index
        self.pool_size = pool_size
        self.temperature = temperature
        self.leak_gap = leak_gap

        self.scenario = SCENARIO_BROWSING
        self.category = ""
        self.boundary_seen = False
        self.override_applied = True     # Non-override sessions are scoreable from turn 1
        self.fuzzy = False               # Template parse failed => paraphrase scoring path
        self.safe_from_turn = 1          # Earliest turn where a miss is trustworthy negative evidence
        self.observed: list[str] = []    # Heard constraint texts (for lexical rescue)

        self.candidates: dict[int, Candidate] = {}
        self.eliminated: set[int] = set()
        self._log: list[tuple] = []      # Observation log for replaying new candidates

    # -- Observations ---------------------------------------------------------

    def observe_opening(self, message: str) -> None:
        """Parse and score the session opening message."""
        scenario, category, constraint, strict = parse_opening(message)
        if not strict:
            # Template miss (likely paraphrase). Use robust path: infer category from
            # catalog vocabulary; leave scenario unknown and score both hypotheses.
            self.fuzzy = True
            category = self.index.find_category(message)
            constraint = message.strip()
        self.scenario = scenario
        self.category = category
        if scenario == SCENARIO_OVERRIDE:
            # Override sessions are not scoreable until the override message arrives.
            self.override_applied = False
        elif scenario == SCENARIO_UNKNOWN:
            # Still submit recommendations (misses are free), but do not eliminate
            # on miss until turn 4 — override can arrive as late as turn 4.
            self.safe_from_turn = 4
        if constraint:
            self.observed.append(constraint)
        self._log.append(("open", scenario, category, constraint))
        self._seed_pool(constraint)

    def observe_turn(self, message: str, ask: str | None) -> None:
        """Parse and score a subsequent customer reply."""
        kind, payload, strict = parse_reply(message)
        if not strict:
            self.fuzzy = True
        if kind == "boundary":
            # Consumes the question turn; carries no product information.
            self.boundary_seen = True
            self._log.append(("boundary",))
            return
        if kind == "idle":
            self._log.append(("idle",))
            return
        if kind == "override":
            self.override_applied = True
        if payload:
            self.observed.append(payload)
        self._log.append((kind, ask, payload))
        self._absorb(kind, ask, payload)

    def eliminate(self, asins: list[str]) -> None:
        """Last turn's recommendations missed => these products are not the target."""
        for asin in asins:
            pid = self.index.pid_of.get(asin)
            if pid is not None:
                self.eliminated.add(pid)
                self.candidates.pop(pid, None)

    # -- Candidate pool maintenance -------------------------------------------

    def _seed_pool(self, constraint: str) -> None:
        """Initialize candidates from category, constraint, and lexical recall."""
        pool = list(self.index.category_pool(self.category))
        if constraint:
            for fragment in payload_fragments(constraint):
                pool.extend(self.index.constraint_pool(fragment))
        if len(pool) < 32:
            phrases = [p for p in (self.category, constraint) if p]
            pool.extend(self.index.lexical_pool(phrases, 512))
        if not pool:
            pool = self.index.popular(256)
        self._install(dict.fromkeys(pool))

    def _absorb(self, kind: str, ask: str | None, payload: str) -> None:
        """Update existing candidates and pull in new ones triggered by payload."""
        newcomers: list[int] = []
        for fragment in payload_fragments(payload):
            newcomers.extend(self.index.constraint_pool(fragment))
        fresh = [pid for pid in dict.fromkeys(newcomers)
                 if pid not in self.candidates and pid not in self.eliminated]

        for cand in self.candidates.values():
            self._step(cand, kind, ask, payload)
        for pid in fresh:
            cand = self._replay(pid)
            if cand is not None:
                self.candidates[pid] = cand

        # Lexical rescue: if no candidate explains the latest utterance, the target
        # may be outside the pool (paraphrase, foreign intent card, category error).
        best = min((c.penalty for c in self.candidates.values()), default=float("inf"))
        if best > LEXICAL_RESCUE_PENALTY:
            phrases = self.observed[-3:] or [self.category]
            self._install(dict.fromkeys(self.index.lexical_pool(phrases, 256)))
        self._prune()

    def _install(self, pids) -> None:
        for pid in pids:
            if pid in self.eliminated or pid in self.candidates:
                continue
            cand = self._replay(pid)
            if cand is not None:
                self.candidates[pid] = cand
        self._prune()

    def _replay(self, pid: int) -> Candidate | None:
        """Replay full dialogue from scratch to compute cumulative penalty for pid."""
        if pid in self.eliminated:
            return None
        cand = Candidate(pid, 0.0, frozenset())
        for entry in self._log:
            head = entry[0]
            if head == "open":
                cand.penalty += self._opening_penalty(pid, entry[1], entry[2], entry[3])
                if entry[1] == SCENARIO_BUYING:
                    values = self.index.constraints[pid]
                    if values:
                        cand.disclosed = frozenset((values[0],))
            elif head in ("boundary", "idle"):
                continue
            else:
                self._step(cand, head, entry[1], entry[2])
        return cand

    def _opening_penalty(self, pid: int, scenario: str, category: str, constraint: str) -> float:
        penalty = 0.0
        if category and self.index.cats[pid] != category:
            # Category is deterministically derived; mismatch should be heavily penalized.
            penalty += W_CATEGORY_FLAT
            penalty += W_CATEGORY * (1.0 - similarity(self.index.cats[pid], category))
        if not constraint:
            return penalty

        values = self.index.constraints[pid]
        n_hard = self.index.n_hard[pid]
        buying_slot = values[0] if values else ""
        override_slot = values[-1] if len(values) > n_hard else ""
        if scenario == SCENARIO_BUYING:
            match = self._match(pid, buying_slot, constraint)
        elif scenario == SCENARIO_OVERRIDE:
            match = self._match(pid, override_slot, constraint)
        else:
            # Unknown scenario: score buying slot, override slot, and browsing (no constraint).
            match = max(
                self._match(pid, buying_slot, constraint),
                self._match(pid, override_slot, constraint),
                BROWSING_PRIOR_MATCH,
            )
        penalty += W_CONSTRAINT * (1.0 - match)
        return penalty

    def _step(self, cand: Candidate, kind: str, ask: str | None, payload: str) -> None:
        pid = cand.pid
        if kind == "override":
            # Override message reveals hard_constraints[0] of the (unchanged) target.
            all_values = self.index.constraints[pid]
            expected = all_values[0] if all_values else ""
            cand.penalty += W_CONSTRAINT * (1.0 - self._match(pid, expected, payload))
            if expected:
                cand.disclosed = cand.disclosed | {expected}
            return

        predicted = simulate_reply(
            list(self.index.constraints[pid]), list(self.index.ctypes[pid]), ask, cand.disclosed
        )
        if kind == "none":
            # Customer said no more preference; candidate predicted more to disclose => inconsistent.
            cand.penalty += W_NONE * len(predicted)
        else:
            # Render what the candidate should have said and compare to heard payload.
            rendered = render_reply(predicted)
            if not predicted:
                cand.penalty += W_SILENT
            elif rendered != payload:
                cand.penalty += W_REPLY * (1.0 - self._match(pid, rendered, payload))
        if predicted:
            cand.disclosed = cand.disclosed | set(predicted)

    def _match(self, pid: int, expected: str, heard: str) -> float:
        """Match between expected utterance at this slot and what was heard.

        Primary path is exact slot comparison; fallbacks handle order swap,
        paraphrase, and foreign intent-card sources via any-slot match,
        substring containment, and IDF-weighted coverage.
        """
        if expected and expected == heard:
            return 1.0
        best = similarity(expected, heard) if expected else 0.0
        for value in self.index.constraints[pid]:
            if value == heard:
                best = max(best, ORDER_DISCOUNT)
                break
            best = max(best, ORDER_DISCOUNT * similarity(value, heard))
        if self.fuzzy and expected:
            # Paraphrase path: measure recall of expected keywords in heard text
            # (packaging words dilute whole-string similarity).
            best = max(best, COVERAGE_CAP * self._coverage(expected, heard))
        if best < CONTAINMENT_SIM and heard and heard.lower() in self.index.blobs[pid]:
            best = CONTAINMENT_SIM
        return min(best, 1.0)

    def _coverage(self, expected: str, heard: str) -> float:
        """IDF-weighted keyword recall of expected content in heard text."""
        wanted = tokenize(expected)
        if not wanted:
            return 0.0
        present = set(tokenize(heard))
        idf = self.index.idf
        total = matched = 0.0
        for token in wanted:
            weight = idf.get(token, 1.0)
            total += weight
            if token in present:
                matched += weight
        return matched / total if total else 0.0

    def _prune(self) -> None:
        if len(self.candidates) <= self.pool_size:
            return
        ranked = sorted(self.candidates.values(), key=lambda c: -self.score(c.pid))
        self.candidates = {c.pid: c for c in ranked[: self.pool_size]}

    # -- Posterior ------------------------------------------------------------

    def score(self, pid: int) -> float:
        cand = self.candidates.get(pid)
        if cand is None:
            return -math.inf
        return self.index.log_prior[pid] - cand.penalty

    def posterior(self) -> tuple[list[int], list[float], float]:
        """Return (product ids by descending posterior, probabilities, leak mass).

        leak mass = probability the true target is not in the current candidate pool.
        """
        if not self.candidates:
            return [], [], 1.0
        scored = [(pid, self.score(pid)) for pid in self.candidates]
        scored.sort(key=lambda kv: -kv[1])
        best = scored[0][1]
        temp = max(self.temperature, 1e-6)
        weights = [math.exp((value - best) / temp) for _, value in scored]
        leak = math.exp(-self.leak_gap / temp)
        total = sum(weights) + leak
        pids = [pid for pid, _ in scored]
        return pids, [w / total for w in weights], leak / total
