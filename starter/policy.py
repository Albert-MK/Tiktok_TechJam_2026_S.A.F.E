"""Decision layer: which attribute to ask and how many recommendations to submit.

## What the scoring rule rewards

Per-session utility (hit on turn t at rank r):

    U(r, t) = 0.50 + 0.30 / r + 0.02 × (11 − t)

Two implications drive the entire policy:

1. **Waiting one turn costs 0.02; dropping from rank 1 to rank 2 costs 0.15.**
   Submitting early without confidence is expensive; batch Top-10 every turn is worse.
2. **A miss is free** and yields a deterministic elimination of those products.

Optimal shape: **submit one highest-posterior guess per turn**, eliminate on miss,
then reveal the full list when information is exhausted.

Example at rank 5: batch Top-10 scores 0.5 + 0.3/5 + 0.2 = 0.76;
five sequential guesses hitting on turn 5 scores 0.5 + 0.3 + 0.02×6 = 0.92.

## Submission: per-candidate opportunity cost

Whether to submit candidate i now compares cleanly:

    submit now, if i is target  -> U(i, t)
    wait, if i is target        -> U(r, τ) from the future schedule at rank r, turn τ

Both sides are **conditional on i being the target**, so probabilities cancel —
the decision is robust to posterior calibration.

Future schedules are computed by forward-simulating deterministic customer replies
and running backward dynamic programming over remaining turns.

## Questions: optimal experimental design

For each allowed attribute, simulate how each candidate would answer, partition the
posterior mass, and pick the attribute maximizing expected endgame utility.
This adapts each turn (feature vs other vs material) and beats any fixed order.
"""

from __future__ import annotations

from .user_model import ALLOWED_ATTRIBUTES, MAX_TURNS, TOP_K, simulate_reply

HIT_WEIGHT = 0.50
MRR_WEIGHT = 0.30
EFF_PER_TURN = 0.02     # 0.20 efficiency weight / 10 turns
PLAN_POOL = 60          # Candidates participating in ask planning (mass concentrates here)

# Tie-break when expected values are equal (belief already peaked).
# Prefer broad "other" first; deprioritize "category" which often yields nothing.
ASK_ORDER = ("other", "feature", "material", "color", "style",
             "size", "use_case", "brand", "budget", "category")


def turn_utility(rank: int, turn: int) -> float:
    """Instant utility if the target is hit at rank on turn."""
    return HIT_WEIGHT + MRR_WEIGHT / rank + EFF_PER_TURN * (MAX_TURNS + 1 - turn)


def endgame_plan(probs: list[float], turn: int, top_k: int = TOP_K) -> tuple[float, list[tuple[int, int]]]:
    """Optimal submission schedule assuming no further information arrives.

    Returns (expected utility, schedule). Schedule[j] = (turn, rank) for candidate j;
    (0, 0) means that candidate never receives a scored slot.

    probs are absolute probabilities so group values add directly.
    """
    n = len(probs)
    if n == 0 or turn > MAX_TURNS:
        return 0.0, []

    future = [0.0] * (n + 1)
    choices: dict[int, list[int]] = {}
    for t in range(MAX_TURNS, turn - 1, -1):
        base = HIT_WEIGHT + EFF_PER_TURN * (MAX_TURNS + 1 - t)
        current = [0.0] * (n + 1)
        picked = [0] * (n + 1)
        for k in range(n - 1, -1, -1):
            best, chosen = future[k], 0      # L = 0: submit nothing this turn
            acc = 0.0
            for length in range(1, min(top_k, n - k) + 1):
                acc += probs[k + length - 1] * (base + MRR_WEIGHT / length)
                value = acc + future[k + length]
                if value > best:
                    best, chosen = value, length
            current[k], picked[k] = best, chosen
        choices[t] = picked
        future = current

    schedule = [(0, 0)] * n
    cursor = 0
    for t in range(turn, MAX_TURNS + 1):
        if cursor >= n:
            break
        length = choices[t][cursor]
        for offset in range(length):
            schedule[cursor + offset] = (t, offset + 1)
        cursor += length
    return future[0], schedule


def _partition(index, belief, pids: list[int], attribute: str) -> dict[tuple, list[int]]:
    """Simulate customer reply if each candidate in pids were the target."""
    groups: dict[tuple, list[int]] = {}
    for pid in pids:
        predicted = simulate_reply(
            list(index.constraints[pid]),
            list(index.ctypes[pid]),
            attribute,
            belief.candidates[pid].disclosed,
        )
        groups.setdefault(predicted, []).append(pid)
    return groups


def scoring_horizon(turn: int, scoreable: bool) -> int:
    """Earliest turn when the next submission would actually be scored.

    Intent-override sessions are not scored until the override message (turn 3 or 4).
    Planning must respect this or DP undervalues asking on early turns.
    """
    if scoreable or turn >= 3:
        return turn + 1
    return 3


def choose_ask(index, belief, pids: list[int], probs: list[float], turn: int, horizon: int):
    """Pick the ask_attribute with highest expected endgame utility."""
    plan_pids = pids[:PLAN_POOL]
    if not plan_pids or turn >= MAX_TURNS:
        return None, {}
    prob_of = dict(zip(pids, probs))

    best_attr, best_value, best_groups = None, -1.0, {}
    for attribute in ASK_ORDER:
        groups = _partition(index, belief, plan_pids, attribute)
        value = 0.0
        for members in groups.values():
            members.sort(key=lambda pid: -prob_of[pid])
            value += endgame_plan([prob_of[pid] for pid in members], horizon)[0]
        if value > best_value:
            best_attr, best_value, best_groups = attribute, value, groups
    return best_attr, best_groups


def future_utilities(groups: dict[tuple, list[int]], prob_of: dict[int, float], horizon: int) -> dict[int, float]:
    """If we do not submit now, utility each candidate would get later (conditional on being target)."""
    result: dict[int, float] = {}
    for members in groups.values():
        _, schedule = endgame_plan([prob_of[pid] for pid in members], horizon)
        for pid, (slot_turn, slot_rank) in zip(members, schedule):
            result[pid] = turn_utility(slot_rank, slot_turn) if slot_rank else 0.0
    return result


def choose_submission(pids: list[int], turn: int, future: dict[int, float], scoreable: bool) -> int:
    """How many recommendations to submit: compare submit-now vs wait for each prefix."""
    if not scoreable or turn > MAX_TURNS:
        return 0
    if turn >= MAX_TURNS:
        return min(TOP_K, len(pids))
    length = 0
    for rank in range(1, min(TOP_K, len(pids)) + 1):
        if turn_utility(rank, turn) <= future.get(pids[rank - 1], 0.0):
            break
        length = rank
    return length


QUESTION_TEMPLATES = {
    "material": "Do you have a material in mind — cotton, leather, wool, something else?",
    "color": "Any particular colour you're set on?",
    "size": "How about sizing or fit — anything I should match?",
    "style": "What style or cut are you going for?",
    "brand": "Is there a brand or store you tend to buy from?",
    "budget": "Roughly what price range works for you?",
    "feature": "Which specific features matter most to you?",
    "use_case": "What will you mainly be using it for?",
    "category": "Could you narrow down the type of item you want?",
    "other": "Tell me anything else that matters — details, features, must-haves.",
}


def compose_message(attribute: str | None, shortlist: int) -> str:
    """Natural-language agent message combining question and optional shortlist lead-in."""
    if attribute is None:
        return (
            "Here are my best matches based on everything you've told me."
            if shortlist
            else "Let me know a bit more and I'll narrow it down."
        )
    if shortlist > 1:
        lead = f"Here are {shortlist} options that fit so far. "
    elif shortlist:
        lead = "Here's my strongest match so far. "
    else:
        lead = ""
    return lead + QUESTION_TEMPLATES.get(attribute, QUESTION_TEMPLATES["other"])
