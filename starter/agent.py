"""多轮购物推荐 Agent（当前默认：v1.5）。

===============================================================================
给非计算机背景同学的总览
===============================================================================

这个 Agent 的任务很像“导购员”：
  1) 听顾客说了什么（解析自然语言）；
  2) 记下关键需求（类目、材质、细节约束……）；
  3) 必要时追问一个属性（ask_attribute）；
  4) 从 5 万商品里找出最像目标的 Top-10 推荐。

它不调用大模型 API，主要靠：
  - 规则解析（正则匹配固定句式）
  - 全文检索 BM25（SQLite FTS5，像“增强版关键词搜索”）
  - 手工设计的重排打分（谁更像目标就排谁前面）

一轮对话的标准流水线：
  reset() 初始化会话
    -> respond() 收到用户一句话
      -> _update_state() 更新“记忆”
      -> _retrieve() 多路召回候选商品
      -> _rerank() 精细打分排序
      -> _next_ask() 决定要不要再问一个问题
      -> 返回 message / ask_attribute / recommendations

评分只看 parent_asin 是否命中隐藏目标商品，所以排序非常关键。
详细实验记录见 docs/OPTIMIZATION_REPORT_V1_3.md、docs/OPTIMIZATION_REPORT_V1_4.md 与 docs/OPTIMIZATION_REPORT_V1_5.md。
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path

from starter.config import active_config


# ---------------------------------------------------------------------------
# 文本处理与句式模板
# ---------------------------------------------------------------------------

# 抽出英文/数字词：把句子切成 token（词片）。
TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

# 停用词：这些词太普通，几乎不帮助区分商品，检索时丢掉。
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "please", "some",
    "that", "the", "this", "to", "want", "with", "would", "you", "looking",
    "im", "still", "exploring", "key", "requirement", "quite", "right",
    "yet", "ask", "about", "one", "specific", "attribute", "those", "options",
    "not", "have", "preference", "additional", "judgment", "your", "use",
    "ignore", "earlier", "actually", "what", "need", "matters", "here",
}

# 按“具体属性类型”提问时的顺序。
ASK_ORDER_TYPED = (
    "material", "color", "feature", "budget", "style", "size",
    "use_case", "brand", "category", "other",
)

# 当前默认：先问 other。
# 原因：评测模拟器遇到 ask_attribute=other 时，会把剩余约束（最多 2 条）
# 一次性吐出来，通常比一个个问 material/color 更快。
ASK_ORDER_OTHER_FIRST = (
    "other", "material", "color", "feature", "budget", "style", "size",
    "use_case", "brand", "category",
)

# 实验用：other 之后先问 feature。material 经常已在 other 回答里出现，
# 再问一次容易空转；feature 长句通常更有区分度。
ASK_ORDER_FEATURE_FIRST = (
    "other", "feature", "style", "use_case", "color", "budget", "size",
    "brand", "material", "category",
)

# 自适应收窄提问：other 之后按候选分支信息增益选 typed 属性（顺序本身不重要）。
ADAPTIVE_TYPED_ATTRS = (
    "feature", "material", "color", "style", "use_case", "budget", "size", "brand", "category",
)

# 画像 preference_tags → ask_attribute 先验（v8 profile_branch 实验）。
TAG_TO_ASK_PRIOR: dict[str, dict[str, float]] = {
    "material": {"material": 1.0, "feature": 0.5},
    "fit": {"style": 1.0, "size": 0.8},
    "comfort": {"feature": 1.0, "material": 0.4},
    "style": {"style": 1.0, "color": 0.6},
    "durability": {"feature": 1.0, "material": 0.5},
    "performance": {"use_case": 1.0, "feature": 0.7},
    "warmth": {"feature": 1.0, "material": 0.5},
    "weather": {"use_case": 1.0, "feature": 0.6},
    "general shopping": {},
}

# 模拟器里常空转、且不在 preference_tags 里的低产出维度。
LOW_YIELD_ASK = frozenset({"brand", "budget", "category"})

# 每个 ask_attribute 对应的顾客可见问题文案。
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

# ---- 下面这些正则，用来识别评测模拟器的固定句式 ----

# “我没有某某偏好” -> 该属性已问空，之后别再问。
NO_PREF_RE = re.compile(
    r"i don't have (?:an additional )?preference for ([a-z_]+)",
    re.I,
)
# “I'm looking for Sun Hats.” / “... but I'm still exploring.”
LOOKING_FOR_RE = re.compile(
    r"i(?:'m| am) looking for (.+?)(?:\.|, but i'm still exploring)",
    re.I,
)
# Buying 场景常见：A key requirement is: ...
KEY_REQ_RE = re.compile(r"a key requirement is:\s*(.+)$", re.I)
# 追问后常见：For that, what matters is: ...
MATTERS_RE = re.compile(r"for that, what matters is:\s*(.+)$", re.I)
# Override / 直接陈述：What I need is: ...
NEED_IS_RE = re.compile(r"what i need is:\s*(.+)$", re.I)

# 泛化词：太常见，单独出现时几乎锁不住唯一商品（如 leather、cotton）。
GENERIC_PHRASES = {
    "imported", "cotton", "polyester", "leather", "nylon", "wool", "spandex",
    "silk", "rayon", "fabric", "100% leather", "100% cotton", "100% polyester",
    "100 leather", "100 cotton", "100 polyester", "machine wash",
    "buckle closure", "zipper closure", "pull on closure", "button closure",
    "tie closure", "no closure closure",
}

# Intent Override 触发句。
OVERRIDE_RE = re.compile(r"ignore my earlier preference", re.I)
# 预算数字，例如 "$29.99"。
PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d+)?)", re.I)

# 与评测模拟器 classify_constraint 对齐，用于动态提问/跳过已覆盖类型。
MATERIAL_RE = re.compile(
    r"\b(cotton|polyester|nylon|leather|wool|spandex|silk|rayon|fabric|croslite)\b",
    re.I,
)
COLOR_RE = re.compile(
    r"\b(black|white|blue|red|pink|green|brown|gray|grey|purple|yellow|orange)\b",
    re.I,
)
SIZE_RE = re.compile(r"\b(size|sizing|width|wide|narrow|small|medium|large)\b", re.I)
STYLE_RE = re.compile(r"\b(department|style|fit|sleeve|neck|slim|regular|relaxed)\b", re.I)
USE_CASE_RE = re.compile(r"\b(hiking|running|gym|winter|outdoor|work|tactical|military)\b", re.I)
TYPED_ASK_SKIP_COVERED = (
    "material", "color", "budget", "size", "style", "use_case", "brand",
)


def _text(value: object) -> str:
    """把商品字段统一转成可检索的纯文本。

    catalog 里 features/details 可能是字符串、列表或字典，这里都拼成一段话。
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        return " ".join(f"{key} {item}" for key, item in value.items())
    if isinstance(value, list):
        return " ".join(str(item) for item in value)
    return str(value)


def _field_entries(value: object) -> list[str]:
    """把 features/details 拆成“原始条目列表”。

    官方模拟器生成的约束，往往来自这些条目本身。
    v1.3 用“前缀是否一致”做很弱的来源证据加分。
    """
    if isinstance(value, dict):
        return [f"{key}: {item}" for key, item in value.items() if item not in (None, "", [])]
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def _terms(text: str) -> list[str]:
    """分词：去掉停用词和单字母，得到检索用 token 列表。"""
    return [
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 1 and token.lower() not in STOPWORDS
    ]


def _split_constraints(blob: str) -> list[str]:
    """模拟器常把多条约束用分号拼在一句里，这里拆开成独立约束。"""
    parts = [part.strip(" -;,.\t\n") for part in re.split(r";|\n", blob)]
    return [part for part in parts if part]


def _normalize_alnum(text: str) -> str:
    """只保留字母数字并压空白。用于弱化标点差异（实验开关控制是否启用）。"""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _is_generic_constraint(phrase: str) -> bool:
    """判断约束是否过于泛化。

    泛化约束（如 leather）召回面太大，不能当“主证据”过度加分。
    """
    compact = re.sub(r"\s+", " ", phrase.lower()).strip()
    if compact in GENERIC_PHRASES:
        return True
    terms = _terms(phrase)
    return len(terms) <= 2 and len(compact) < 24


def _is_semi_distinctive(phrase: str) -> bool:
    """介于“泛化”和“强区分度”之间的中等具体短语。

    例如长度还行、但不算很长的特征描述。
    """
    if _is_generic_constraint(phrase):
        return False
    terms = _terms(phrase)
    compact = re.sub(r"\s+", " ", phrase.lower()).strip()
    return len(terms) >= 2 and len(compact) >= 12


class Agent:
    """混合购物 Agent：槽位记忆 + 多路召回 + 短语重排。

    对外只保证两个接口（竞赛契约）：
      - reset(session_id, user_profile)
      - respond(session_id, user_message, turn, top_k) -> dict
    """

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        # 商品目录文件路径（默认 5 万条 Clothing 商品）。
        self.catalog_path = Path(catalog_path)
        # 当前策略开关（来自 config.py）。
        self.cfg = active_config()
        # 内存数据库：启动时把目录建索引，检索时不反复扫文件。
        self.connection = sqlite3.connect(":memory:")
        # 每个会话一份独立记忆（不同顾客互不影响）。
        self._sessions: dict[str, dict] = {}
        # ASIN -> 预处理后的商品字段，方便重排时快速读取。
        self._products: dict[str, dict] = {}
        # 词稀有度缓存（实验用；默认权重为 0 时几乎不触发）。
        self._idf_cache: dict[str, float] = {}
        self._build_index()

    def _build_index(self) -> None:
        """启动时构建检索索引。

        做两件事：
          1) FTS5 全文表：支持关键词/短语搜索（BM25）；
          2) 内存字典 _products：重排时按字段加分用。
        """
        cursor = self.connection.cursor()
        # parent_asin 不参与全文匹配（UNINDEXED），只作为返回的商品 ID。
        # 后面几个字段按重要程度在 BM25 公式里给不同权重。
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
                # blob = 所有文本拼在一起，重排时做“整段包含”检查。
                blob = " ".join(
                    part for part in (title, categories, features, details, store, description) if part
                )
                blob_l = blob.lower()
                self._products[asin] = {
                    "title": title,
                    "categories": categories,
                    "features": features.lower(),
                    "details": details.lower(),
                    "description": description.lower(),
                    # 原始 features/details 条目（规范化后），供 v1.3 前缀匹配。
                    "constraint_entries": [
                        _normalize_alnum(entry)
                        for entry in (
                            *_field_entries(product.get("features")),
                            *_field_entries(product.get("details")),
                        )
                    ],
                    # 条目级 token，供轻量商品相似度（已展示惩罚 / 锚点重叠）。
                    "entry_tokens": frozenset(
                        token
                        for entry in (
                            *_field_entries(product.get("features")),
                            *_field_entries(product.get("details")),
                        )
                        for token in _terms(entry)
                    ),
                    "store": store,
                    "blob": blob_l,
                    "blob_norm": _normalize_alnum(blob_l),
                    "price": product.get("price"),
                    "rating": float(product.get("average_rating") or 0.0),
                    "rating_n": int(product.get("rating_number") or 0),
                }
                batch.append((asin, title, categories, features, details, store, description))
                # 分批写入，避免一次塞太多行导致内存尖峰。
                if len(batch) >= 1000:
                    cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
                    batch.clear()
        if batch:
            cursor.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?, ?, ?)", batch)
        # 词表：可查某个词出现在多少商品里（用于可选的 IDF 实验）。
        cursor.execute("CREATE VIRTUAL TABLE product_vocab USING fts5vocab(products, 'row')")
        self.connection.commit()

    def _idf(self, token: str) -> float:
        """计算词的稀有度（Inverse Document Frequency）。

        白话：一个词出现在越少商品里，就越“稀有”，越有区分力。
        当前默认配方里 idf_coverage_weight=0，所以这条路径通常不生效；
        保留是为了本地消融实验可复现。
        """
        cached = self._idf_cache.get(token)
        if cached is not None:
            return cached
        row = self.connection.execute(
            "SELECT doc FROM product_vocab WHERE term = ?",
            (token.lower(),),
        ).fetchone()
        document_frequency = int(row[0]) if row else 0
        value = math.log((len(self._products) + 1.0) / (document_frequency + 1.0))
        self._idf_cache[token] = value
        return value

    def reset(self, session_id: str, user_profile: dict) -> None:
        """开始一个新会话时清空记忆。

        user_profile 是官方给的匿名画像，例如 preference_tags=["fit","comfort"]。
        我们不会拿到真实用户 ID / 历史评论原文。
        """
        self._sessions[session_id] = {
            "profile": user_profile or {},   # 匿名画像
            "category": "",                  # 用户正在找的粗类目，如 "Sun Hats"
            "constraints": [],               # 已披露的硬/软约束列表
            "asked": [],                     # 已经问过哪些属性
            "exhausted": set(),              # 用户明确说“没有偏好”的属性
            "mode": "browsing",              # browsing / buying / override
            "history": [],                   # 原始用户句（调试用）
            "shown": set(),                  # 已推荐过的 ASIN（未命中则后续排除）
            "empty_streak": 0,               # 连续“无更多偏好”次数
            "delayed_turns": 0,              # 本会话已暂缓交卷的次数
            "_candidates": [],               # 最近一轮重排候选，供动态提问估算区分度
            "_top_scores": [],               # 最近一轮 Top 分，供不确定时再等一轮
        }

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict:
        """处理一轮对话，返回竞赛要求的结构化结果。

        返回字段：
          - message: 给顾客看的自然语言
          - ask_attribute: 结构化追问字段（或 null）
          - recommendations: 最多 top_k 个 {parent_asin}
          - usage: token 用量（本 Agent 不用 LLM，固定为 0）
        """
        if session_id not in self._sessions:
            raise RuntimeError("reset must be called before respond")
        state = self._sessions[session_id]

        # 1) 听懂并记住这轮新信息
        self._update_state(state, user_message, turn)
        # 2) 根据记忆检索并排序
        recommendations = self._retrieve(state, top_k)
        # 4) 先决定下一问：若已经不问了，就不能再交空列表（否则可能 miss）。
        ask_attribute = self._next_ask(state) if self.cfg["ask"] else None
        # 3) 弱约束 / 排序不确定时先不交卷，避免把目标锁在 Top-10 尾部。
        if self._should_delay_recommendations(state, ask_attribute):
            recommendations = []
            state["delayed_turns"] = int(state.get("delayed_turns") or 0) + 1
        # 把本轮推过的商品记入 shown（若仍未命中，后面会排除它们）
        if self.cfg.get("exclude_shown", True):
            for item in recommendations:
                state["shown"].add(str(item["parent_asin"]))
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
        """从用户这句话里抽取信息，更新会话记忆。

        主要识别四类信号：
          A. Intent Override（忽略先前偏好）
          B. looking for ...（类目 + browsing/buying 模式）
          C. 没有某属性偏好（exhausted）
          D. key requirement / what matters / what I need（具体约束）
        """
        text = (user_message or "").strip()
        state["history"].append(text)
        lowered = text.lower()

        # ---- A. Intent Override ----
        # 协议规定：覆盖消息发出前，即使推到目标也不计分。
        # 覆盖后，原先 shown 黑名单要清空，避免误杀真正目标。
        if self.cfg["override_reset"] and OVERRIDE_RE.search(text):
            state["mode"] = "override"
            # Pre-override recs are not scored, so they may contain the target.
            state["shown"] = set()
            if self.cfg.get("override_reset_asked"):
                # 实验开关（默认关）：覆盖后重开提问序列。
                # The replacement intent starts a new information-gathering phase.
                # Keep useful product constraints, but allow the high-yield "other"
                # question to be asked again immediately.
                state["asked"] = []
            if self.cfg.get("override_clear_old") or not self.cfg.get("override_keep"):
                # 默认 final 配方是 override_keep=True，所以通常不会走清空分支。
                state["constraints"] = []
                state["exhausted"] = set()
                state["asked"] = []
                state["empty_streak"] = 0

        # ---- B. 类目与模式 ----
        looking = LOOKING_FOR_RE.search(text)
        if looking:
            state["category"] = looking.group(1).strip()
            if "still exploring" in lowered:
                state["mode"] = "browsing"
            elif "key requirement" in lowered:
                state["mode"] = "buying"
            elif state["mode"] != "override":
                state["mode"] = "buying"

        # ---- C. “没有偏好” ----
        no_pref = NO_PREF_RE.search(text)
        if no_pref:
            state["exhausted"].add(no_pref.group(1).lower().strip())
            state["empty_streak"] = int(state.get("empty_streak") or 0) + 1

        # ---- D. 抽取具体约束 ----
        extracted: list[str] = []
        for pattern in (KEY_REQ_RE, MATTERS_RE, NEED_IS_RE):
            match = pattern.search(text)
            if match:
                extracted.extend(_split_constraints(match.group(1)))
        if state["mode"] == "override" and not extracted:
            # Keep the trailing clause after the override preamble.
            # 有些 Override 句子结构略怪，再兜底切一次。
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
            # 基线模式：不累积历史，几乎等于“每轮重新开始”。
            state["constraints"] = extracted[:] if extracted else [text]
            if looking:
                state["category"] = looking.group(1).strip()

    def _should_delay_recommendations(self, state: dict, ask_attribute: str | None) -> bool:
        """弱约束或排序不确定时是否暂缓交出 Top-10。

        评测在目标第一次进入 Top-10 时就锁死名次。
        v1.4：首轮没有强约束就先交空列表。
        后续实验：在仍会提问、且未超过 delay_max_empty 时，再多等几轮。
        """
        has_distinctive = any(self._is_distinctive(phrase) for phrase in state["constraints"])
        first_turn = len(state.get("history") or []) <= 1
        delayed = int(state.get("delayed_turns") or 0)
        max_empty = int(self.cfg.get("delay_max_empty") or 0)

        # v1.4：只挡首轮。
        if (
            (self.cfg.get("delay_generic_first") or self.cfg.get("delay_weak_recs"))
            and first_turn
            and not has_distinctive
        ):
            if self.cfg.get("delay_generic_first") or state["mode"] in {"browsing", "boundary"}:
                return True

        extra = bool(
            self.cfg.get("delay_until_distinctive")
            or self.cfg.get("delay_uncertain")
            or int(self.cfg.get("delay_until_n_constraints") or 0)
        )
        if not extra:
            return False
        # 没有下一问就必须交卷，否则可能 10 轮都空。
        if not ask_attribute:
            return False
        cap = max_empty if max_empty > 0 else 2
        if delayed >= cap:
            return False
        if self.cfg.get("delay_until_distinctive") and not has_distinctive:
            return True
        need_n = int(self.cfg.get("delay_until_n_constraints") or 0)
        if need_n and len(state["constraints"]) < need_n:
            return True
        if self.cfg.get("delay_uncertain"):
            scores = list(state.get("_top_scores") or [])
            min_margin = float(self.cfg.get("delay_min_margin") or 2.0)
            if len(scores) >= 2 and (scores[0] - scores[1]) < min_margin:
                return True
            if not has_distinctive:
                return True
        return False

    def _classify_constraint(self, value: str) -> str:
        """粗分类约束类型，规则与评测模拟器保持一致。"""
        lowered = value.lower()
        if "budget" in lowered or re.search(r"(?:\$|<=|under)\s*\d", lowered):
            return "budget"
        if MATERIAL_RE.search(lowered):
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

    def _covered_ask_types(self, state: dict) -> set[str]:
        """已经从用户约束里拿到的属性类型。feature 可多条，不在跳过集合里。"""
        covered = {self._classify_constraint(phrase) for phrase in state["constraints"]}
        return {attr for attr in covered if attr in TYPED_ASK_SKIP_COVERED}

    def _filter_candidates_by_constraints(self, asins: list[str], state: dict) -> list[str]:
        """在候选池内做硬过滤：只保留满足已披露约束的商品。

        用于估算“当前有效搜索范围”，让下一问基于已收窄的分支选属性。
        """
        constraints = [c for c in state.get("constraints") or [] if c.strip()]
        if not constraints:
            return list(asins)
        kept: list[str] = []
        for asin in asins:
            product = self._products.get(asin)
            if not product:
                continue
            if all(self._needle_in_product(c.lower(), product) for c in constraints):
                kept.append(asin)
        # 过滤过猛时回退，避免把目标误删后熵估计失真。
        return kept if kept else list(asins)

    def _active_narrow_candidates(self, state: dict) -> list[str]:
        """自适应提问用的当前候选分支。"""
        raw = list(state.get("_candidates") or [])
        if not raw:
            return []
        if self.cfg.get("ask_mode") == "adaptive_narrow" or self.cfg.get("narrow_filter_active"):
            return self._filter_candidates_by_constraints(raw, state)
        if self.cfg.get("ask_mode") == "profile_branch":
            return self._active_profile_branch_candidates(state)
        return raw

    def _distinctive_constraints(self, state: dict) -> list[str]:
        """只取有区分度的约束，用于估算有效搜索分支。"""
        return [
            phrase
            for phrase in state.get("constraints") or []
            if phrase.strip() and self._is_distinctive(phrase)
        ]

    def _active_profile_branch_candidates(self, state: dict) -> list[str]:
        """profile_branch：用 distinctive 约束硬过滤候选，泛词不参与。"""
        raw = list(state.get("_candidates") or [])
        if not raw:
            return []
        if self.cfg.get("profile_branch_all_constraints"):
            return self._filter_candidates_by_constraints(raw, state)
        distinctive = self._distinctive_constraints(state)
        if not distinctive:
            return raw
        kept: list[str] = []
        for asin in raw:
            product = self._products.get(asin)
            if not product:
                continue
            if all(self._needle_in_product(c.lower(), product) for c in distinctive):
                kept.append(asin)
        return kept if kept else raw

    def _profile_ask_prior(self, state: dict, attr: str) -> float:
        """用户画像 tag 与 ask_attribute 的对齐程度。"""
        tags = state.get("profile", {}).get("preference_tags") or []
        best = 0.0
        for tag in tags:
            priors = TAG_TO_ASK_PRIOR.get(str(tag).lower().strip(), {})
            best = max(best, float(priors.get(attr, 0.0)))
        return best

    def _ask_yield_prior(self, attr: str) -> float:
        """低产出维度降权（brand/budget/category）。"""
        if self.cfg.get("profile_branch_no_low_yield_penalty"):
            return 1.0
        return 0.25 if attr in LOW_YIELD_ASK else 1.0

    def _combined_ask_score(self, attr: str, candidate_asins: list[str], state: dict) -> float:
        """分支 split × 画像对齐 × 产出先验。"""
        split = self._narrow_ask_score(attr, candidate_asins)
        if split <= 0:
            return 0.0
        profile = self._profile_ask_prior(state, attr)
        return split * self._ask_yield_prior(attr) * (1.0 + profile)

    def _attribute_bucket(self, product: dict, attr: str) -> str | None:
        """从商品文本抽出某属性的一个桶值，用来估提问能拆多开。"""
        blob = product.get("blob") or ""
        if attr == "material":
            match = MATERIAL_RE.search(blob)
            return match.group(1).lower() if match else None
        if attr == "color":
            match = COLOR_RE.search(blob)
            return match.group(1).lower() if match else None
        if attr == "size":
            match = SIZE_RE.search(blob)
            return match.group(0).lower() if match else None
        if attr == "style":
            match = STYLE_RE.search(blob)
            return match.group(0).lower() if match else None
        if attr == "use_case":
            match = USE_CASE_RE.search(blob)
            return match.group(0).lower() if match else None
        if attr == "budget":
            try:
                return str(int(float(product["price"]) // 25) * 25)
            except (TypeError, ValueError):
                return None
        if attr == "brand":
            store = (product.get("store") or "").strip().lower()
            return store or None
        if attr == "feature":
            entries = product.get("constraint_entries") or []
            return entries[0][:24] if entries else None
        if attr == "category":
            cats = (product.get("categories") or "").lower()
            parts = [part for part in re.split(r"[/,>|]", cats) if part.strip()]
            return parts[-1].strip() if parts else None
        return None

    def _typed_split_score(self, attr: str, candidate_asins: list[str]) -> float:
        """当前候选里该属性取值越分散，提问后越有利于筛掉无关商品。"""
        values: list[str] = []
        for asin in candidate_asins:
            product = self._products.get(asin)
            if not product:
                continue
            bucket = self._attribute_bucket(product, attr)
            if bucket:
                values.append(bucket)
        if len(values) < 2:
            return 0.0
        counts = Counter(values)
        total = len(values)
        entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
        coverage = total / max(len(candidate_asins), 1)
        return entropy * coverage

    def _narrow_ask_score(self, attr: str, candidate_asins: list[str]) -> float:
        """估算问该属性能把当前分支收窄多少。

        熵越高 = 候选在该属性上取值越分散 = 用户回答后更可能删掉大量竞品。
        coverage 低则该属性在候选上几乎不可见，问了也白问。
        """
        if len(candidate_asins) < 2:
            return 0.0
        counts: Counter[str] = Counter()
        for asin in candidate_asins:
            product = self._products.get(asin)
            if not product:
                continue
            bucket = self._attribute_bucket(product, attr)
            if bucket:
                counts[bucket] += 1
        if len(counts) <= 1:
            return 0.0
        total = sum(counts.values())
        entropy = -sum((count / total) * math.log(count / total) for count in counts.values())
        max_entropy = math.log(len(counts))
        norm_entropy = entropy / max_entropy if max_entropy > 0 else 0.0
        coverage = total / len(candidate_asins)
        max_bucket_share = max(counts.values()) / total
        reduction_potential = 1.0 - max_bucket_share
        return norm_entropy * coverage * (1.0 + reduction_potential)

    def _next_ask(self, state: dict) -> str | None:
        """决定下一轮问哪个属性；若不需要再问则返回 None。

        设计原则（白话）：
          - 优先问 other，让模拟器一次吐出剩余细节；
          - 不要重复问已经问过的，或用户已说“没偏好”的；
          - 若 typed 问空且还没有强约束，允许再问一次 other（v1 关键修复）。
        """
        ask_mode = self.cfg["ask_mode"]
        if ask_mode in {"adaptive_narrow", "profile_branch"}:
            order = ("other", *ADAPTIVE_TYPED_ATTRS)
        elif ask_mode == "feature_first":
            order = ASK_ORDER_FEATURE_FIRST
        elif ask_mode == "other_first":
            order = ASK_ORDER_OTHER_FIRST
        else:
            order = ASK_ORDER_TYPED
        asked = set(state["asked"])
        exhausted = state["exhausted"]
        other_asks = sum(1 for attr in state["asked"] if attr == "other")
        last_ask = state["asked"][-1] if state["asked"] else None
        has_distinctive = any(self._is_distinctive(phrase) for phrase in state["constraints"])
        covered = self._covered_ask_types(state) if self.cfg.get("skip_covered_attrs") else set()

        # 实验开关（默认关）：拿到首批 other 回答后立刻再问一次 other。
        # 实测会伤害 Hit/MRR，所以默认不启用。
        if (
            self.cfg.get("eager_second_other")
            and other_asks == 1
            and last_ask == "other"
            and "other" not in exhausted
        ):
            return "other"

        # After a typed attribute comes back empty, ask "other" once more so
        # leftover constraints of any type can still be disclosed.
        if (
            other_asks == 1
            and last_ask not in {None, "other"}
            and int(state.get("empty_streak") or 0) >= 1
            and not has_distinctive
        ):
            return "other"

        # profile_branch：任意 typed 空答后优先回 other（避免连续空转 typed）。
        if (
            ask_mode == "profile_branch"
            and last_ask not in {None, "other"}
            and int(state.get("empty_streak") or 0) >= 1
            and other_asks < 2
            and "other" not in exhausted
            and not has_distinctive
        ):
            return "other"

        # ---- profile_branch：画像先验 × 分支 split 选下一问 ----
        if ask_mode == "profile_branch" and other_asks >= 1:
            active = self._active_profile_branch_candidates(state)
            stop_at = int(self.cfg.get("narrow_stop_candidates") or 0)
            if stop_at and 0 < len(active) <= stop_at:
                if other_asks < 2 and not has_distinctive and "other" not in asked:
                    return "other"
                return None
            typed_pool = [
                attr
                for attr in ADAPTIVE_TYPED_ATTRS
                if attr not in asked and attr not in exhausted and attr not in covered
            ]
            if active and typed_pool:
                scored = [
                    (self._combined_ask_score(attr, active, state), attr)
                    for attr in typed_pool
                ]
                scored = [(score, attr) for score, attr in scored if score > 0]
                if scored:
                    scored.sort(reverse=True)
                    return scored[0][1]

        # ---- 自适应收窄：基于当前候选分支的信息增益选下一问 ----
        if ask_mode == "adaptive_narrow" and other_asks >= 1:
            active = self._active_narrow_candidates(state)
            stop_at = int(self.cfg.get("narrow_stop_candidates") or 0)
            if stop_at and 0 < len(active) <= stop_at:
                if other_asks < 2 and not has_distinctive and "other" not in asked:
                    return "other"
                return None
            typed_pool = [
                attr
                for attr in ADAPTIVE_TYPED_ATTRS
                if attr not in asked and attr not in exhausted and attr not in covered
            ]
            if active and typed_pool:
                scored = [
                    (self._narrow_ask_score(attr, active), attr)
                    for attr in typed_pool
                ]
                scored = [(score, attr) for score, attr in scored if score > 0]
                if scored:
                    scored.sort(reverse=True)
                    return scored[0][1]

        remaining = [
            attr
            for attr in order
            if attr not in asked and attr not in exhausted and attr not in covered
        ]
        if self.cfg.get("dynamic_typed_ask"):
            typed = [attr for attr in remaining if attr != "other"]
            candidates = list(state.get("_candidates") or [])
            if typed and candidates:
                typed.sort(key=lambda attr: self._typed_split_score(attr, candidates), reverse=True)
                if remaining and remaining[0] == "other":
                    remaining = ["other", *typed]
                else:
                    remaining = [*typed, *[attr for attr in remaining if attr == "other"]]

        for attr in remaining:
            return attr

        # 兜底：仍无强约束时，最多再给一次 other。
        if other_asks < 2 and not has_distinctive:
            return "other"
        return None

    def _query_parts(self, state: dict) -> tuple[list[str], list[str]]:
        """把会话记忆整理成：短语列表 + token 列表，供检索使用。"""
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
        """构造较宽的 FTS 查询：短语 OR 单词。

        宽查询负责“别漏掉”，精确排序交给后面的 _rerank。
        """
        clauses: list[str] = []
        for phrase in phrases:
            cleaned = " ".join(_terms(phrase)[:12])
            if cleaned:
                clauses.append(f'"{cleaned}"')
        for token in tokens[:50]:
            clauses.append(f'"{token}"')
        return " OR ".join(clauses)

    def _is_distinctive(self, phrase: str) -> bool:
        """判断约束是否“足够具体”，值得当主证据。

        规则大致是：词够多，或文本够长；
        v1.2+ 在 relaxed_distinctive 打开时，也会接纳半具体短语。
        """
        terms = _terms(phrase)
        if len(terms) >= 4:
            return True
        compact = re.sub(r"\s+", " ", phrase.lower()).strip()
        if len(compact) >= 24 and len(terms) >= 2:
            return True
        if self.cfg.get("relaxed_distinctive") and _is_semi_distinctive(phrase):
            return True
        return False

    def _match(self, expression: str, limit: int) -> list[tuple[str, float]]:
        """执行一次 FTS5 BM25 检索，返回 [(asin, rank), ...]。

        bm25(...) 里的一串数字是各字段权重：
          parent_asin 不参与匹配（0），随后是
          title / categories / features / details / store / description。
        """
        weights = self.cfg.get("bm25_field_weights") or [6.0, 4.0, 2.5, 2.5, 1.5, 1.0]
        if not isinstance(weights, (list, tuple)) or len(weights) != 6:
            weights = [6.0, 4.0, 2.5, 2.5, 1.5, 1.0]
        rendered = ", ".join(f"{float(weight):.4f}" for weight in (0.0, *weights))
        try:
            return self.connection.execute(
                f"SELECT parent_asin, bm25(products, {rendered}) AS rank "
                "FROM products WHERE products MATCH ? ORDER BY rank LIMIT ?",
                (expression, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            # 查询语法异常时返回空，避免整轮会话崩溃。
            return []

    def _needle_in_product(self, needle: str, product: dict) -> bool:
        """检查某段约束文本是否出现在商品全文里。"""
        if not needle:
            return False
        if needle in product["blob"]:
            return True
        if self.cfg.get("punct_normalize"):
            norm = _normalize_alnum(needle)
            return bool(norm) and norm in product["blob_norm"]
        return False

    def _exact_candidates(self, phrases: list[str]) -> list[str]:
        """精确短语召回：把“足够具体”的约束当针，在全库做子串命中。

        这是对 FTS 的补充：有时长句被拆词后，目标反而被挤出 Top-N。
        """
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
        """多路召回：先尽量把目标捞进候选池，再交给重排。

        召回顺序（越靠前的路径越“精确”）：
          1) 精确长短语子串命中
          2) 每个强约束的 FTS 短语查询
          3) 类目 AND 约束词
          4) 宽 OR 查询兜底
        """
        phrases, tokens = self._query_parts(state)

        # 实验开关：有强约束时，检索只盯强约束（默认关，历史实测帮助不大）。
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
            state["_candidates"] = []
            return []

        # 重排需要比最终 top_k 更大的候选池。
        fetch_k = max(top_k, int(self.cfg["retrieve_k"])) if self.cfg["phrase_rerank"] else top_k
        shown = state["shown"] if self.cfg.get("exclude_shown", True) else set()
        fetch_k = max(fetch_k, top_k + len(shown) + 20)

        ranked: list[str] = []
        seen: set[str] = set()
        bm25_rank: dict[str, int] = {}
        route_ranks: list[dict[str, int]] = []
        # 只有打开 route_rrf_weight 时才记录各路排名（默认关）。
        collect_route_ranks = bool(self.cfg.get("route_rrf_weight"))

        def add_rows(rows: list[tuple], bonus: int = 0) -> None:
            """把一路检索结果并入总候选。

            bonus 越大，表示这路结果越“值得优先”。
            bm25_rank 会变成后续重排的“名次惩罚”输入。
            """
            route: dict[str, int] = {}
            for route_rank, row in enumerate(rows, 1):
                asin = str(row[0])
                if collect_route_ranks:
                    route.setdefault(asin, route_rank)
                if asin in seen:
                    continue
                seen.add(asin)
                bm25_rank[asin] = len(ranked) - bonus
                ranked.append(asin)
            if collect_route_ranks and route:
                route_ranks.append(route)

        # 路径 1：精确长短语
        add_rows([(asin, 0.0) for asin in self._exact_candidates(state["constraints"])], bonus=50)
        phrase_limit = 60 if self.cfg.get("wide_phrase_retrieve") else 30
        phrase_bonus = 35 if self.cfg.get("wide_phrase_retrieve") else 20

        # 路径 2：每个强约束单独做短语检索
        for phrase in state["constraints"]:
            if not self._is_distinctive(phrase):
                continue
            cleaned = " ".join(_terms(phrase)[:12])
            if cleaned:
                add_rows(self._match(f'"{cleaned}"', phrase_limit), bonus=phrase_bonus)

        # 路径 3：类目 AND 约束（要求候选同时贴合类目和细节）
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

        # 路径 4：宽 OR 兜底
        add_rows(self._match(self._fts_expression(phrases, tokens), fetch_k))
        if not ranked and tokens:
            add_rows(self._match(" OR ".join(f'"{token}"' for token in tokens[:30]), fetch_k))

        # 精细重排
        if self.cfg["phrase_rerank"]:
            ranked = self._rerank(state, phrases, tokens, ranked, bm25_rank, route_ranks)

        state["_candidates"] = ranked[:40]

        # 排除本会话已展示且未命中的商品（协议下它们不可能是目标）
        if shown:
            ranked = [asin for asin in ranked if asin not in shown]
        state["_candidates"] = ranked[:40]
        return [{"parent_asin": asin} for asin in ranked[:top_k]]

    def _rerank(
        self,
        state: dict,
        phrases: list[str],
        tokens: list[str],
        candidates: list[str],
        bm25_rank: dict[str, int],
        route_ranks: list[dict[str, int]],
    ) -> list[str]:
        """对候选商品做精细打分，分数高者排前。

        可以把它理解成“导购打分表”：
          + 具体约束精确命中        （很重要）
          + 叶类目 / 标题 / 店铺匹配
          + 预算接近、评分略高
          - 粗类目对不上
          - 关键词检索名次太靠后

        v1.3 额外两点：
          1) features/details 原始条目前缀一致 -> 小加分
          2) 仅在 Override 后，画像标签词命中 -> 极弱加分
        """
        # ---- 预算：若约束里写了 $xx，则价格越接近越好 ----
        budget = None
        for phrase in state["constraints"]:
            match = PRICE_RE.search(phrase)
            if match:
                budget = float(match.group(1))
                break

        category_terms = _terms(state["category"])
        # 叶类目 = 类目路径里最后一个词，通常最具体（如 "Sun Hats"）。
        leaf_category = category_terms[-1] if category_terms else ""

        # 把约束整理成：全部针 / 强区分针 / 半具体针
        constraint_needles = []
        distinctive_needles = []
        semi_needles = []
        for phrase in state["constraints"]:
            raw = re.sub(r"\s+", " ", phrase.lower()).strip()
            if raw:
                constraint_needles.append(raw)
                if self._is_distinctive(phrase) and not _is_generic_constraint(phrase):
                    distinctive_needles.append(raw)
                elif self.cfg.get("semi_distinctive_bonus") and _is_semi_distinctive(phrase):
                    semi_needles.append(raw)
            joined = " ".join(_terms(phrase))
            if joined and joined not in constraint_needles:
                constraint_needles.append(joined)

        has_distinctive = bool(distinctive_needles)
        bm25_coef = float(self.cfg.get("bm25_coef", 0.02))
        generic_exact = float(self.cfg.get("generic_exact_score", 1.2))
        distinctive_exact_base = float(self.cfg.get("distinctive_exact_base", 20.0))
        category_miss_penalty = float(self.cfg.get("category_miss_penalty", 8.0))
        soft_cover = float(self.cfg.get("soft_cover_bonus", 0.0))
        idf_coverage_weight = float(self.cfg.get("idf_coverage_weight", 0.0))
        route_rrf_weight = float(self.cfg.get("route_rrf_weight", 0.0))
        route_rrf_k = float(self.cfg.get("route_rrf_k", 10.0))
        entry_prefix_weight = float(self.cfg.get("entry_prefix_weight", 0.0))
        profile_tag_weight = float(self.cfg.get("profile_tag_weight", 0.0))
        profile_tags = [
            token
            for tag in state.get("profile", {}).get("preference_tags", [])
            for token in _terms(str(tag))
        ]

        scored: list[tuple[float, int, str]] = []
        for asin in candidates:
            product = self._products.get(asin)
            if not product:
                continue
            blob = product["blob"]
            features = product.get("features") or ""
            score = 0.0
            cover = 0  # 命中了几条强约束

            # 关键词检索名次：越靠后扣越多（系数由 bm25_coef 控制）。
            score -= bm25_coef * bm25_rank.get(asin, 100)

            # 多路 RRF（默认关）：在多条召回路里都靠前的商品会加分。
            if route_rrf_weight:
                score += route_rrf_weight * sum(
                    1.0 / (route_rrf_k + route[asin])
                    for route in route_ranks
                    if asin in route
                )

            # ---- 约束匹配是最核心的分数来源 ----
            for needle in constraint_needles:
                matched = (
                    self._needle_in_product(needle, product)
                    if self.cfg.get("punct_normalize")
                    else (needle in blob)
                )
                generic = _is_generic_constraint(needle)
                distinctive = any(needle == d or needle in d or d in needle for d in distinctive_needles) or (
                    len(_terms(needle)) >= 4
                )
                semi = (not distinctive) and any(
                    needle == d or needle in d or d in needle for d in semi_needles
                )
                if matched:
                    if self.cfg.get("distinctive_exact_bonus") and generic:
                        # 泛词命中只给很低分，避免 leather 这类词统治排序。
                        score += generic_exact
                    elif self.cfg.get("distinctive_exact_bonus") and distinctive:
                        # 具体长短语精确命中：主证据。
                        score += distinctive_exact_base + min(len(needle), 80) / 8.0
                        cover += 1
                    elif self.cfg.get("semi_distinctive_bonus") and semi:
                        score += 10.0 + min(len(needle), 40) / 10.0
                    else:
                        score += 8.0 + min(len(needle), 80) / 10.0
                        if distinctive:
                            cover += 1
                    if self.cfg.get("features_field_boost") and needle in features:
                        score += 4.0 if distinctive or semi else 1.0
                else:
                    # 没整段命中时，按命中单词数给一点部分分。
                    partial_coef = (
                        0.8 if (self.cfg.get("distinctive_partial_boost") and distinctive) else 0.35
                    )
                    hits = sum(1 for token in needle.split() if token in blob)
                    score += partial_coef * hits

            # ---- v1.3：字段条目前缀一致性 ----
            # 如果用户约束刚好像某条原始 features/details 的开头，
            # 说明更可能“同源”，给很弱加分；越靠前的条目权重略高。
            if entry_prefix_weight:
                for needle in dict.fromkeys(constraint_needles):
                    if _is_generic_constraint(needle):
                        continue
                    normalized = _normalize_alnum(needle)
                    if not normalized:
                        continue
                    for entry_index, entry in enumerate(product["constraint_entries"]):
                        if entry.startswith(normalized):
                            score += entry_prefix_weight / (1.0 + 0.2 * entry_index)
                            break

            # 稀有词覆盖（默认关）
            if idf_coverage_weight:
                matched_tokens = {
                    token
                    for token in tokens
                    if len(token) > 1 and token in blob
                }
                score += idf_coverage_weight * sum(self._idf(token) for token in matched_tokens)

            if soft_cover and cover:
                score += soft_cover * cover
            if (
                self.cfg.get("full_cover_bonus")
                and distinctive_needles
                and cover >= len(distinctive_needles)
            ):
                score += 12.0

            # ---- 类目匹配 ----
            cat_blob = product["categories"].lower()
            cat_hits = 0
            if category_terms:
                cat_hits = sum(1 for token in category_terms if token in cat_blob or token in blob)
                score += 1.8 * cat_hits
                if cat_hits == len(category_terms):
                    score += 2.5
            if self.cfg.get("leaf_category_boost") and leaf_category:
                if leaf_category in cat_blob:
                    score += 4.5
                elif leaf_category in blob:
                    score += 2.0

            # ---- 标题 / 店铺 ----
            title = product["title"].lower()
            title_hits = sum(1 for token in tokens[:20] if token in title)
            score += 0.25 * title_hits
            if self.cfg.get("title_category_boost") and category_terms:
                score += 1.2 * sum(1 for token in category_terms if token in title)
            if self.cfg.get("title_distinctive_boost"):
                for needle in distinctive_needles:
                    if needle and needle in title:
                        score += 12.0
                    elif needle and _normalize_alnum(needle) in _normalize_alnum(title):
                        score += 6.0
            if self.cfg.get("store_match_boost"):
                store = (product.get("store") or "").lower()
                if store:
                    store_hits = sum(1 for token in tokens[:20] if len(token) > 2 and token in store)
                    score += 0.6 * store_hits

            # ---- 预算接近度 ----
            if budget is not None:
                price = product["price"]
                try:
                    price_value = float(price)
                    delta = abs(price_value - budget)
                    score += max(0.0, 3.0 - delta / max(budget, 1.0))
                except (TypeError, ValueError):
                    score -= 0.2

            # ---- 评分/热度微弱加权（不是主信号）----
            apply_profile = self.cfg["profile_boost"]
            if apply_profile and self.cfg.get("profile_when_generic_only") and has_distinctive:
                apply_profile = False
            if apply_profile:
                score += 0.05 * product["rating"]
                if product["rating_n"] > 200:
                    score += 0.1

            # ---- v1.3：画像标签弱加权（默认仅 Override 后）----
            # preference_tags 如 fit/comfort 只是弱提示，不能压过明确商品约束。
            apply_profile_tags = bool(profile_tag_weight and profile_tags)
            if self.cfg.get("profile_tags_generic_only") and has_distinctive:
                apply_profile_tags = False
            if self.cfg.get("profile_tags_override_only") and state["mode"] != "override":
                apply_profile_tags = False
            if apply_profile_tags:
                score += profile_tag_weight * sum(
                    1 for token in profile_tags if token in blob
                )

            # 热门商品惩罚（默认关）：避免超高评论数商品抢镜。
            if self.cfg.get("popularity_dampen") and product["rating_n"] > 500 and has_distinctive:
                score -= 0.35

            # 粗类目对不上：重罚（默认开）。
            if self.cfg.get("category_must_match") and category_terms and cat_hits < len(category_terms):
                score -= category_miss_penalty

            scored.append((cover if self.cfg.get("cover_sort") else 0, score, asin))

        neighbor_weight = float(self.cfg.get("neighbor_overlap_weight") or 0.0)
        shown_weight = float(self.cfg.get("shown_dissimilarity_weight") or 0.0)
        if neighbor_weight or shown_weight:
            scored = self._apply_similarity_adjustments(
                state, scored, neighbor_weight, shown_weight
            )

        # 默认按总分降序；可选先按“强约束覆盖数”再按总分。
        if self.cfg.get("cover_sort"):
            scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        else:
            scored.sort(key=lambda item: item[1], reverse=True)
        state["_top_scores"] = [score for _, score, _ in scored[:10]]
        return [asin for _, _, asin in scored]

    def _apply_similarity_adjustments(
        self,
        state: dict,
        scored: list[tuple[float, float, str]],
        neighbor_weight: float,
        shown_weight: float,
    ) -> list[tuple[float, float, str]]:
        """用商品条目重叠做轻量相似度调整，不引入向量库。

        - neighbor: 向“已精确命中强约束”的锚点商品靠拢
        - shown: 与本会话已展示且未命中的商品越像，越往下调
        """
        anchor_token_sets: list[frozenset[str]] = []
        if neighbor_weight:
            anchors = [asin for cover, _, asin in scored if cover > 0][:12]
            for asin in anchors:
                tokens = self._products.get(asin, {}).get("entry_tokens") or frozenset()
                if tokens:
                    anchor_token_sets.append(tokens)

        shown_union: set[str] = set()
        if shown_weight:
            for asin in state.get("shown") or []:
                tokens = self._products.get(asin, {}).get("entry_tokens") or frozenset()
                shown_union.update(tokens)

        adjusted: list[tuple[float, float, str]] = []
        for cover, score, asin in scored:
            tokens = self._products.get(asin, {}).get("entry_tokens") or frozenset()
            if neighbor_weight and anchor_token_sets and tokens:
                overlap = sum(
                    len(tokens & anchor) / max(len(tokens | anchor), 1)
                    for anchor in anchor_token_sets
                )
                score += neighbor_weight * (overlap / len(anchor_token_sets))
            if shown_weight and shown_union and tokens:
                union = len(tokens | shown_union)
                if union:
                    score -= shown_weight * (len(tokens & shown_union) / union)
            adjusted.append((cover, score, asin))
        return adjusted
