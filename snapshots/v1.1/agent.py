from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

from starter.config import active_config


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
    "im", "still", "exploring", "key", "requirement", "quite", "right",
    "yet", "ask", "about", "one", "specific", "attribute", "those", "options",
    "not", "have", "preference", "additional", "judgment", "your", "use",
    "ignore", "earlier", "actually", "what", "need", "matters", "here",
}
ASK_ORDER_TYPED = (
    "material", "color", "feature", "budget", "style", "size",
    "use_case", "brand", "category", "other",
)
ASK_ORDER_OTHER_FIRST = (
    "other", "material", "color", "feature", "budget", "style", "size",
    "use_case", "brand", "category",
)
ASK_QUESTIONS = {
    "category": "Which product category or type matters most?",
    "material": "Do you have a material preference?",
    "color": "Is there a color you want me to prioritize?",
    "size": "Do you have a size or fit constraint?",
    "style": "Any style, fit, or department preference?",
    "brand": "Do you have a brand in mind?",
    "budget": "What budget should I stay around?",
    "feature": "Which features or details are most important?",
    "use_case": "What will you use this for?",
    "other": "Is there any other must-have detail I should lock in?",
}
NO_PREF_RE = re.compile(
    r"i don't have (?:an additional )?preference for ([a-z_]+)",
    re.I,
)
LOOKING_FOR_RE = re.compile(
    r"i(?:'m| am) looking for (.+?)(?:\.|, but i'm still exploring)",
    re.I,
)
KEY_REQ_RE = re.compile(r"a key requirement is:\s*(.+)$", re.I)
MATTERS_RE = re.compile(r"for that, what matters is:\s*(.+)$", re.I)
NEED_IS_RE = re.compile(r"what i need is:\s*(.+)$", re.I)
GENERIC_PHRASES = {
    "imported", "cotton", "polyester", "leather", "nylon", "wool", "spandex",
    "silk", "rayon", "fabric", "100% leather", "100% cotton", "100% polyester",
    "100 leather", "100 cotton", "100 polyester", "machine wash",
    "buckle closure", "zipper closure", "pull on closure", "button closure",
    "tie closure", "no closure closure",
}
OVERRIDE_RE = re.compile(r"ignore my earlier preference", re.I)
PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)", re.I)


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _terms(text: str) -> list[str]:
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


def _split_constraints(blob: str) -> list[str]:
    parts = [part.strip(" -;,.\t\n") for part in re.split(r";|\n", blob)]
    return [part for part in parts if part]


def _normalize_alnum(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _is_generic_constraint(phrase: str) -> bool:
    compact = re.sub(r"\s+", " ", phrase.lower()).strip()
    if compact in GENERIC_PHRASES:
        return True
    terms = _terms(phrase)
    return len(terms) <= 2 and len(compact) < 24


class Agent:
    """Hybrid shopping agent: slot tracking, dual-track retrieval, phrase rerank."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog_path = Path(catalog_path)
        self.cfg = active_config()
        self.connection = sqlite3.connect(":memory:")
        self._sessions: dict[str, dict] = {}
        self._products: dict[str, dict] = {}
        self._build_index()

    def _build_index(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE VIRTUAL TABLE products USING fts5("
            "parent_asin UNINDEXED, title, categories, features, details, store, description, "
            "tokenize='unicode61 remove_diacritics 2')"
        )
        batch: list[tuple[str, str, str, str, str, str, str]] = []
        with self.catalog_path.open(encoding="utf-8") as handle:
            for line in handle:
                product = json.loads(line)
                asin = str(product["parent_asin"])
                title = _text(product.get("title"))
                categories = _text(product.get("categories"))
                features = _text(product.get("features"))
                details = _text(product.get("details"))
                store = _text(product.get("store"))
                description = _text(product.get("description"))
                blob = " ".join(
                    part for part in (title, categories, features, details, store, description) if part
                )
                blob_l = blob.lower()
                self._products[asin] = {
                    "title": title,
                    "categories": categories,
                    "store": store,
                    "blob": blob_l,
                    "blob_norm": _normalize_alnum(blob_l),
                    "price": product.get("price"),
                    "rating": float(product.get("average_rating") or 0.0),
                    "rating_n": int(product.get("rating_number") or 0),
                }
                batch.append((asin, title, categories, features, details, store, description))
                if len(batch) >= 1000:
                    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                    batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        self.connection.commit()

    def reset(self, session_id: str, user_profile: dict) -> None:
        self._sessions[session_id] = {
            "profile": user_profile or {},
            "category": "",
            "constraints": [],
            "asked": [],
            "exhausted": set(),
            "mode": "browsing",
            "history": [],
            "shown": set(),
            "empty_streak": 0,
        }

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        if session_id not in self._sessions:
            raise RuntimeError("reset must be called before respond")
        state = self._sessions[session_id]
        self._update_state(state, user_message, turn)
        recommendations = self._retrieve(state, top_k)
        if self.cfg.get("exclude_shown", True):
            for item in recommendations:
                state["shown"].add(str(item["parent_asin"]))
        ask_attribute = self._next_ask(state) if self.cfg["ask"] else None
        if ask_attribute:
            state["asked"].append(ask_attribute)
        message = ASK_QUESTIONS.get(ask_attribute, "Here are the closest matches I found.")
        if recommendations and ask_attribute:
            message = f"{message} I also shortlisted options that already match what you told me."
        elif recommendations:
            message = "Here are the closest matches I found."
        return {
            "message": message,
            "ask_attribute": ask_attribute,
            "recommendations": recommendations,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    def _update_state(self, state: dict, user_message: str, turn: int) -> None:
        text = (user_message or "").strip()
        state["history"].append(text)
        lowered = text.lower()

        if self.cfg["override_reset"] and OVERRIDE_RE.search(text):
            state["mode"] = "override"
            # Pre-override recs are not scored, so they may contain the target.
            state["shown"] = set()
            if self.cfg.get("override_clear_old") or not self.cfg.get("override_keep"):
                state["constraints"] = []
                state["exhausted"] = set()
                state["asked"] = []
                state["empty_streak"] = 0

        looking = LOOKING_FOR_RE.search(text)
        if looking:
            state["category"] = looking.group(1).strip()
            if "still exploring" in lowered:
                state["mode"] = "browsing"
            elif "key requirement" in lowered:
                state["mode"] = "buying"
            elif state["mode"] != "override":
                state["mode"] = "buying"

        no_pref = NO_PREF_RE.search(text)
        if no_pref:
            state["exhausted"].add(no_pref.group(1).lower().strip())
            state["empty_streak"] = int(state.get("empty_streak") or 0) + 1

        extracted: list[str] = []
        for pattern in (KEY_REQ_RE, MATTERS_RE, NEED_IS_RE):
            match = pattern.search(text)
            if match:
                extracted.extend(_split_constraints(match.group(1)))
        if state["mode"] == "override" and not extracted:
            # Keep the trailing clause after the override preamble.
            tail = re.split(r"what i need is:", text, flags=re.I)
            if len(tail) == 2:
                extracted.extend(_split_constraints(tail[1]))

        for item in extracted:
            if item.lower() not in {c.lower() for c in state["constraints"]}:
                state["constraints"].append(item)
        if extracted:
            state["empty_streak"] = 0

        if not self.cfg["accumulate"]:
            # Baseline: forget history except the current utterance terms.
            state["constraints"] = extracted[:] if extracted else [text]
            if looking:
                state["category"] = looking.group(1).strip()

    def _next_ask(self, state: dict) -> str | None:
        order = ASK_ORDER_OTHER_FIRST if self.cfg["ask_mode"] == "other_first" else ASK_ORDER_TYPED
        asked = set(state["asked"])
        exhausted = state["exhausted"]
        other_asks = sum(1 for attr in state["asked"] if attr == "other")
        last_ask = state["asked"][-1] if state["asked"] else None
        has_distinctive = any(self._is_distinctive(phrase) for phrase in state["constraints"])
        # After a typed attribute comes back empty, ask "other" once more so
        # leftover constraints of any type can still be disclosed.
        if (
            other_asks == 1
            and last_ask not in {None, "other"}
            and int(state.get("empty_streak") or 0) >= 1
            and not has_distinctive
        ):
            return "other"
        for attr in order:
            if attr in asked or attr in exhausted:
                continue
            return attr
        if other_asks < 2 and not has_distinctive:
            return "other"
        return None

    def _query_parts(self, state: dict) -> tuple[list[str], list[str]]:
        phrases = [state["category"]] if state["category"] else []
        phrases.extend(state["constraints"])
        tokens: list[str] = []
        seen: set[str] = set()
        for phrase in phrases:
            for token in _terms(phrase):
                if token not in seen:
                    seen.add(token)
                    tokens.append(token)
        return phrases, tokens

    def _fts_expression(self, phrases: list[str], tokens: list[str]) -> str:
        clauses: list[str] = []
        for phrase in phrases:
            cleaned = " ".join(_terms(phrase)[:12])
            if cleaned:
                clauses.append(f'"{cleaned}"')
        for token in tokens[:50]:
            clauses.append(f'"{token}"')
        return " OR ".join(clauses)

    def _is_distinctive(self, phrase: str) -> bool:
        terms = _terms(phrase)
        if len(terms) >= 4:
            return True
        compact = re.sub(r"\s+", " ", phrase.lower()).strip()
        return len(compact) >= 24 and len(terms) >= 2

    def _match(self, expression: str, limit: int) -> list[tuple[str, float]]:
        try:
            return self.connection.execute(
                "SELECT parent_asin, bm25(products, 0.0, 6.0, 4.0, 2.5, 2.5, 1.5, 1.0) AS rank "
                "FROM products WHERE products MATCH ? ORDER BY rank LIMIT ?",
                (expression, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            return []

    def _needle_in_product(self, needle: str, product: dict) -> bool:
        if not needle:
            return False
        if needle in product["blob"]:
            return True
        if self.cfg.get("punct_normalize"):
            norm = _normalize_alnum(needle)
            return bool(norm) and norm in product["blob_norm"]
        return False

    def _exact_candidates(self, phrases: list[str]) -> list[str]:
        needles: list[str] = []
        for phrase in phrases:
            if not self._is_distinctive(phrase):
                continue
            raw = re.sub(r"\s+", " ", phrase.lower()).strip()
            if raw:
                needles.append(raw)
        if not needles:
            return []
        hits: list[str] = []
        seen: set[str] = set()
        for asin, product in self._products.items():
            for needle in needles:
                if self._needle_in_product(needle, product):
                    if asin not in seen:
                        seen.add(asin)
                        hits.append(asin)
                    break
        return hits

    def _retrieve(self, state: dict, top_k: int) -> list[dict]:
        phrases, tokens = self._query_parts(state)
        if self.cfg.get("distinctive_query_focus") and any(
            self._is_distinctive(phrase) for phrase in state["constraints"]
        ):
            focused = [state["category"]] if state["category"] else []
            focused.extend(phrase for phrase in state["constraints"] if self._is_distinctive(phrase))
            tokens = []
            seen_tokens: set[str] = set()
            for phrase in focused:
                for token in _terms(phrase):
                    if token not in seen_tokens:
                        seen_tokens.add(token)
                        tokens.append(token)
            phrases = focused
        if not tokens:
            return []
        fetch_k = max(top_k, int(self.cfg["retrieve_k"])) if self.cfg["phrase_rerank"] else top_k
        shown = state["shown"] if self.cfg.get("exclude_shown", True) else set()
        fetch_k = max(fetch_k, top_k + len(shown) + 20)
        ranked: list[str] = []
        seen: set[str] = set()
        bm25_rank: dict[str, int] = {}

        def add_rows(rows: list[tuple], bonus: int = 0) -> None:
            for row in rows:
                asin = str(row[0])
                if asin in seen:
                    continue
                seen.add(asin)
                bm25_rank[asin] = len(ranked) - bonus
                ranked.append(asin)

        add_rows([(asin, 0.0) for asin in self._exact_candidates(state["constraints"])], bonus=50)
        for phrase in state["constraints"]:
            if not self._is_distinctive(phrase):
                continue
            cleaned = " ".join(_terms(phrase)[:12])
            if cleaned:
                add_rows(self._match(f'"{cleaned}"', 30), bonus=20)
        category_terms = _terms(state["category"])
        if category_terms:
            cat_expr = " AND ".join(f'"{token}"' for token in category_terms[:4])
            constraint_terms = []
            source_constraints = state["constraints"]
            if self.cfg.get("distinctive_query_focus") and any(
                self._is_distinctive(phrase) for phrase in state["constraints"]
            ):
                source_constraints = [
                    phrase for phrase in state["constraints"] if self._is_distinctive(phrase)
                ]
            for phrase in source_constraints:
                constraint_terms.extend(_terms(phrase))
            constraint_terms = list(dict.fromkeys(constraint_terms))[:8]
            if constraint_terms:
                extra = " OR ".join(f'"{token}"' for token in constraint_terms)
                add_rows(self._match(f"({cat_expr}) AND ({extra})", 120))
            else:
                add_rows(self._match(cat_expr, 80))
        add_rows(self._match(self._fts_expression(phrases, tokens), fetch_k))
        if not ranked and tokens:
            add_rows(self._match(" OR ".join(f'"{token}"' for token in tokens[:30]), fetch_k))
        if self.cfg["phrase_rerank"]:
            ranked = self._rerank(state, phrases, tokens, ranked, bm25_rank)
        if shown:
            ranked = [asin for asin in ranked if asin not in shown]
        return [{"parent_asin": asin} for asin in ranked[:top_k]]

    def _rerank(
        self,
        state: dict,
        phrases: list[str],
        tokens: list[str],
        candidates: list[str],
        bm25_rank: dict[str, int],
    ) -> list[str]:
        budget = None
        for phrase in state["constraints"]:
            match = PRICE_RE.search(phrase)
            if match:
                budget = float(match.group(1))
                break
        category_terms = _terms(state["category"])
        constraint_needles = []
        distinctive_needles = []
        for phrase in state["constraints"]:
            raw = re.sub(r"\s+", " ", phrase.lower()).strip()
            if raw:
                constraint_needles.append(raw)
                if self._is_distinctive(phrase) and not _is_generic_constraint(phrase):
                    distinctive_needles.append(raw)
            joined = " ".join(_terms(phrase))
            if joined and joined not in constraint_needles:
                constraint_needles.append(joined)
        scored: list[tuple[float, int, str]] = []
        for asin in candidates:
            product = self._products.get(asin)
            if not product:
                continue
            blob = product["blob"]
            score = 0.0
            cover = 0
            score -= 0.02 * bm25_rank.get(asin, 100)
            for needle in constraint_needles:
                matched = self._needle_in_product(needle, product) if self.cfg.get("punct_normalize") else (needle in blob)
                generic = _is_generic_constraint(needle)
                distinctive = any(needle == d or needle in d or d in needle for d in distinctive_needles) or (
                    len(_terms(needle)) >= 4
                )
                if matched:
                    if self.cfg.get("distinctive_exact_bonus") and generic:
                        score += 1.2
                    elif self.cfg.get("distinctive_exact_bonus") and distinctive:
                        score += 20.0 + min(len(needle), 80) / 8.0
                        cover += 1
                    else:
                        score += 8.0 + min(len(needle), 80) / 10.0
                        if distinctive:
                            cover += 1
                else:
                    hits = sum(1 for token in needle.split() if token in blob)
                    score += 0.35 * hits
            cat_blob = product["categories"].lower()
            cat_hits = 0
            if category_terms:
                cat_hits = sum(1 for token in category_terms if token in cat_blob or token in blob)
                score += 1.8 * cat_hits
                if cat_hits == len(category_terms):
                    score += 2.5
            title = product["title"].lower()
            title_hits = sum(1 for token in tokens[:20] if token in title)
            score += 0.25 * title_hits
            if self.cfg.get("title_distinctive_boost"):
                for needle in distinctive_needles:
                    if needle and needle in title:
                        score += 12.0
                    elif needle and _normalize_alnum(needle) in _normalize_alnum(title):
                        score += 6.0
            if budget is not None:
                price = product["price"]
                try:
                    price_value = float(price)
                    delta = abs(price_value - budget)
                    score += max(0.0, 3.0 - delta / max(budget, 1.0))
                except (TypeError, ValueError):
                    score -= 0.2
            if self.cfg["profile_boost"]:
                score += 0.05 * product["rating"]
                if product["rating_n"] > 200:
                    score += 0.1
            if self.cfg.get("category_must_match") and category_terms and cat_hits < len(category_terms):
                score -= 8.0
            scored.append((cover if self.cfg.get("cover_sort") else 0, score, asin))
        if self.cfg.get("cover_sort"):
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        else:
            scored.sort(key=lambda item: item[1], reverse=True)
        return [asin for _, _, asin in scored]
