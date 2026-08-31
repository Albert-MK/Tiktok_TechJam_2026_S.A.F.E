"""Customer generative model (User Model) — foundation of the entire agent.

## Purpose

The evaluator's simulated customer is a **deterministic program**: it compresses
target product metadata into an *intent card*, then emits card contents through
fixed templates turn by turn.

Because generation is deterministic, we invert it:

    If the target were product p, what should the customer say this turn?

Compare predicted vs observed utterance to get likelihood for p. Repeat over all
50k products to obtain the posterior. This is **Bayesian inverse inference**,
not fuzzy keyword retrieval.

## Compliance

Simulator logic is public (`evaluator/local_evaluator.py`). User simulation is
standard in conversational search. This module independently reimplements that
generative logic without modifying the evaluator or reading hidden labels.
Target ASIN, intent cards, and simulator state remain invisible at runtime.

## Robustness

If organizers swap intent-card sources or paraphrase wording, strict template
matching fails. Upper-layer `belief.py` uses **soft penalties** not hard filters,
degrading smoothly to lexical / coverage similarity without empty candidate sets.
"""

from __future__ import annotations

import re

# --- Constants and templates must align byte-for-byte with the evaluator --------

MAX_TURNS = 10
TOP_K = 10

ALLOWED_ATTRIBUTES = (
    "category", "material", "color", "size", "style", "brand",
    "budget", "feature", "use_case", "other",
)

MATERIALS = (
    "cotton", "polyester", "nylon", "leather", "wool",
    "spandex", "silk", "rayon", "fabric",
)
SEARCH_FIELDS = ("title", "features", "details", "description", "categories", "store")

MATERIAL_RE = re.compile(
    r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric)\b", re.I
)
COLOR_RE = re.compile(
    r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange)\b", re.I
)

# Fixed customer utterance templates.
BROWSE_SUFFIX = ", but I'm still exploring."
BUYING_INFIX = ". A key requirement is: "
OPENING_PREFIX = "I'm looking for "
REPLY_PREFIX = "For that, what matters is: "
NO_MORE_PREFIX = "I don't have an additional preference for "
BOUNDARY_PREFIX = "I don't have a preference for "
OVERRIDE_PREFIX = "Actually, ignore my earlier preference. What I need is: "
NO_ASK_REPLY = "Those options are not quite right yet. Ask me about one specific attribute."


# --- Intent card generation (replicates evaluator.intent_card) ------------------


def searchable_text(product: dict) -> str:
    """Concatenate catalog fields used for constraint extraction and lexical fallback."""
    parts: list[str] = []
    for field in SEARCH_FIELDS:
        value = product.get(field)
        if isinstance(value, dict):
            parts.extend(f"{key} {item}" for key, item in value.items())
        elif isinstance(value, list):
            parts.extend(str(item) for item in value)
        elif value is not None:
            parts.append(str(value))
    return " ".join(parts).strip()


def flatten_values(value: object) -> list[str]:
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items() if item not in (None, "", [])]
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def clean_constraint(value: str, limit: int = 180) -> str:
    return re.sub(r"\s+", " ", value).strip(" -;,.\t\n")[:limit].rstrip()


def intent_card(product: dict, limit: int = 180) -> tuple[list[str], list[str]]:
    """Return (hard_constraints, soft_preferences) for a catalog product.

    Preserve insert-at-0 material / insert-at-1 color ordering: when material is
    absent but color exists, color lands after the first feature — existing simulator
    behavior that must not be "fixed" during replication.
    """
    candidates = [*flatten_values(product.get("features")), *flatten_values(product.get("details"))]
    corpus = searchable_text(product)
    material = MATERIAL_RE.search(corpus)
    color = COLOR_RE.search(corpus)
    if material:
        candidates.insert(0, material.group(1).lower())
    if color:
        candidates.insert(1, f"color: {color.group(1).lower()}")
    price = product.get("price")
    if price not in (None, ""):
        candidates.append(f"budget around ${price}")
    cleaned = list(
        dict.fromkeys(
            clean_constraint(item, limit)
            for item in candidates
            if clean_constraint(item, limit)
        )
    )
    if not cleaned:
        cleaned = [clean_constraint(str(product.get("title") or "product"), limit)]
    hard = cleaned[:2]
    soft = cleaned[2:4] or cleaned[:1]
    return hard, soft


def coarse_category(values: list[str]) -> str:
    """Derive a coarse category string from Amazon category breadcrumbs."""
    excluded = {"clothing", "clothing shoes & jewelry", "clothing, shoes & jewelry"}
    cleaned: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part and part.lower() not in excluded:
                cleaned.append(part)
    return " ".join(cleaned[-2:]) if cleaned else "clothing item"


def classify_constraint(value: str) -> str:
    """Map a constraint string to an ask_attribute bucket."""
    lowered = value.lower()
    if "budget" in lowered or re.search(r"(?:\$|<=|under)\s*\d", lowered):
        return "budget"
    if any(material in lowered for material in MATERIALS):
        return "material"
    if any(word in lowered for word in ("color", "black", "white", "blue", "red", "pink", "green")):
        return "color"
    if any(word in lowered for word in ("size", "sizing", "width", "wide", "narrow")):
        return "size"
    if any(word in lowered for word in ("department", "style", "fit", "sleeve", "neck")):
        return "style"
    if any(word in lowered for word in ("hiking", "running", "gym", "winter", "outdoor", "work")):
        return "use_case"
    return "feature"


# --- Customer reply simulation (replicates evaluator.customer_reply) ------------


def simulate_reply(
    constraints: list[str],
    constraint_types: list[str],
    attribute: str | None,
    disclosed: frozenset[str],
) -> tuple[str, ...]:
    """Given target constraints and ask_attribute, return disclosed constraint tuple.

    Empty tuple => customer would say "no additional preference" — still informative.
    """
    if attribute is None:
        return ()
    if attribute not in ALLOWED_ATTRIBUTES:
        attribute = "other"
    matches: list[str] = []
    for value, kind in zip(constraints, constraint_types):
        if value in disclosed:
            continue
        if attribute == "other" or kind == attribute:
            matches.append(value)
            if len(matches) == 2:
                break
    return tuple(matches)


# --- Parse observed utterances --------------------------------------------------

SCENARIO_BUYING = "buying"
SCENARIO_BROWSING = "browsing"          # Also covers boundary before it is exposed
SCENARIO_OVERRIDE = "intent_override"
SCENARIO_UNKNOWN = "unknown"            # Template miss (e.g. paraphrased opening)

# Fallback regex hints when templates fail but semantic cues remain.
OVERRIDE_HINT = re.compile(
    r"\b(ignore|forget|scratch|disregard|nevermind|never mind)\b", re.I
)
NO_PREF_HINT = re.compile(
    r"(no preference|don'?t have a preference|no strong (feeling|opinion)|"
    r"nothing (more|further|else)|no (further|additional|other) (thought|preference)|"
    r"you (pick|choose|decide)|your (judgment|judgement|call)|up to you)",
    re.I,
)
BOUNDARY_HINT = re.compile(r"(use your judg|you (pick|choose|decide)|your call|up to you)", re.I)


def parse_opening(message: str) -> tuple[str, str, str, bool]:
    """Parse opening message -> (scenario, coarse_category, first_constraint, strict_template_hit).

    Three opening templates are mutually exclusive; with verbatim text, intent_override
    is identifiable on turn 1. Override sessions are not scoreable until override
    arrives — critical for spending early turns on questions only.

    Fourth return `strict` signals whether parsing is trustworthy; on miss return
    SCENARIO_UNKNOWN and let belief.py use paraphrase fallbacks.
    """
    text = message.strip()
    body = text[len(OPENING_PREFIX):] if text.startswith(OPENING_PREFIX) else text
    strict = text.startswith(OPENING_PREFIX)

    if strict and body.endswith(BROWSE_SUFFIX):
        return SCENARIO_BROWSING, body[: -len(BROWSE_SUFFIX)].strip(), "", True

    head, sep, tail = body.partition(BUYING_INFIX)
    if strict and sep:
        return SCENARIO_BUYING, head.strip(), clean_constraint(tail.rstrip(".")), True

    head, sep, tail = body.partition(". ")
    if strict and sep:
        return SCENARIO_OVERRIDE, head.strip(), clean_constraint(tail), True
    if strict:
        return SCENARIO_BROWSING, body.strip(" ."), "", True
    return SCENARIO_UNKNOWN, "", text, False


def parse_reply(message: str) -> tuple[str, str, bool]:
    """Parse follow-up message -> (kind, payload, strict_template_hit).

    kind values:
      disclose  customer disclosed 1–2 new constraints
      none      no more preference for asked attribute (negative evidence)
      boundary  boundary pushback (no product info, consumes one question)
      override  intent override with new hard constraint
      idle      no question was asked / no useful reply

    **Do not split on "; ".** Constraints may contain "; " verbatim; splitting is
    ambiguous. Keep full payload and let each candidate render its expected reply.
    """
    text = message.strip()
    if text.startswith(OVERRIDE_PREFIX):
        return "override", clean_constraint(text[len(OVERRIDE_PREFIX):].rstrip(".")), True
    if text.startswith(REPLY_PREFIX):
        return "disclose", text[len(REPLY_PREFIX):].rstrip(".").strip(), True
    if text.startswith(NO_MORE_PREFIX):
        return "none", "", True
    if text.startswith(BOUNDARY_PREFIX):
        return "boundary", "", True
    if text == NO_ASK_REPLY:
        return "idle", "", True

    # Paraphrase fallbacks: recognize utterance class; content matching is downstream.
    if OVERRIDE_HINT.search(text):
        return "override", _tail_after_colon(text), False
    if NO_PREF_HINT.search(text) or BOUNDARY_HINT.search(text):
        # When boundary vs "no preference" is ambiguous, treat as idle — avoid corrupting posterior.
        return "idle", "", False
    return "disclose", _tail_after_colon(text), False


def _tail_after_colon(text: str) -> str:
    """Strip paraphrase packaging; constraints often follow "...: "."""
    body = text.rstrip(".").strip()
    head, sep, tail = body.rpartition(": ")
    if sep and len(tail) >= 3:
        return tail.strip()
    return body


def render_reply(values: tuple[str, ...]) -> str:
    """Render constraint tuple into customer payload (inverse of parse_reply)."""
    return "; ".join(values)


def payload_fragments(payload: str, max_parts: int = 8) -> list[str]:
    """All substring combinations that might be a full constraint — for inverted recall only.

    True constraint text must appear among combinations; extra lookups are cheap.
    """
    parts = [part for part in payload.split("; ") if part.strip()][:max_parts]
    fragments = [payload]
    for start in range(len(parts)):
        for end in range(start, len(parts)):
            fragments.append("; ".join(parts[start : end + 1]))
    return list(dict.fromkeys(f.strip() for f in fragments if f.strip()))
