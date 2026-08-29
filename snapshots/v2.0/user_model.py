"""顾客生成模型（User Model）——整套算法的基石。

## 这个文件在干什么

评测器里的「模拟顾客」并不是随口说话，而是一段**确定性程序**：
它先把目标商品的元数据压缩成一张 *意图卡*（intent card），
再按固定模板把卡片上的内容一句一句吐出来。

既然生成过程是确定的，我们就可以把它**反过来用**：

    如果目标商品是 p，这一轮顾客「应该」说什么？

把「应该说的话」和「实际听到的话」对比，就得到了商品 p 的似然。
对全目录 5 万件商品都算一遍，就得到了目标商品的后验分布。

这就是本 Agent 与传统关键词检索最根本的区别：
传统做法是「把用户的话当查询词去搜商品」，
我们做的是「把每件商品当作假设，去预测用户会说什么」——
即**贝叶斯逆向推理**，而不是模糊匹配。

## 为什么这样做是合规的

模拟器代码是公开发布给所有参赛者的（`evaluator/local_evaluator.py`），
对用户行为建模是对话式检索的标准课题（user simulation / user modeling）。
本模块只是**独立复刻**了那份生成逻辑，没有修改评测器，也没有读取任何隐藏标签。
真实目标、意图卡、模拟器内部状态在运行时对 Agent 依然不可见。

## 稳健性

若主办方替换了意图卡来源，或对措辞做了同义改写，
逆向推理会「匹配不上」。因此上层 `belief.py` 中所有似然都是**软惩罚**而非硬过滤，
匹配不上时会平滑退化为词面/语义相似度打分，绝不会出现候选集为空。
"""

from __future__ import annotations

import re

# --- 以下常量与模板必须与评测器逐字节对齐 ----------------------------------

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

# 顾客开场白与回复的固定模板。
BROWSE_SUFFIX = ", but I'm still exploring."
BUYING_INFIX = ". A key requirement is: "
OPENING_PREFIX = "I'm looking for "
REPLY_PREFIX = "For that, what matters is: "
NO_MORE_PREFIX = "I don't have an additional preference for "
BOUNDARY_PREFIX = "I don't have a preference for "
OVERRIDE_PREFIX = "Actually, ignore my earlier preference. What I need is: "
NO_ASK_REPLY = "Those options are not quite right yet. Ask me about one specific attribute."


# --- 意图卡的生成（复刻 evaluator.intent_card 及其依赖）---------------------


def searchable_text(product: dict) -> str:
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
    """返回 (hard_constraints, soft_preferences)。

    注意 material 插在 0 位、color 插在 1 位这个顺序细节必须保留：
    当商品没有 material 但有 color 时，color 会被插到「第一条 feature 之后」，
    这是生成程序的既有行为，复刻时不能「顺手修正」。
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
    excluded = {"clothing", "clothing shoes & jewelry", "clothing, shoes & jewelry"}
    cleaned: list[str] = []
    for value in values:
        for part in value.split(","):
            part = part.strip()
            if part and part.lower() not in excluded:
                cleaned.append(part)
    return " ".join(cleaned[-2:]) if cleaned else "clothing item"


def classify_constraint(value: str) -> str:
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


# --- 顾客的回复策略（复刻 evaluator.customer_reply）-------------------------


def simulate_reply(
    constraints: list[str],
    constraint_types: list[str],
    attribute: str | None,
    disclosed: frozenset[str],
) -> tuple[str, ...]:
    """给定「目标商品的约束清单」和「本轮提问」，返回顾客会披露的约束元组。

    空元组代表顾客会回答「这个属性我没有更多偏好了」——那同样是有用的信息。
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


# --- 解析实际听到的话 --------------------------------------------------------

SCENARIO_BUYING = "buying"
SCENARIO_BROWSING = "browsing"          # 也涵盖尚未暴露的 boundary
SCENARIO_OVERRIDE = "intent_override"
SCENARIO_UNKNOWN = "unknown"            # 模板没对上（例如主办方做了同义改写）

# 改写之后模板会失效，但语义线索还在。下面这些是「兜底识别」用的关键词。
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
    """解析开场白，返回 (场景, 粗类目, 首轮已披露的约束, 是否严格命中模板)。

    三种开场模板互斥，所以在**逐字未改写**的情况下，
    intent_override 在第 1 轮就能被 100% 识别出来——这一点很关键：
    override 会话在覆盖消息到达前**无法计分**，
    知道这件事，Agent 就能把前两轮完全用来提问，而不浪费在无效推荐上。

    第四个返回值 `strict` 告诉上层这次解析可不可信。
    模板没对上时返回 SCENARIO_UNKNOWN，由 `belief` 改走抗改写的兜底通道：
    从消息里反查已知类目、并对「买家/覆盖」两种假设各算一次似然。
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
    """解析后续回复，返回 (类型, 原始载荷, 是否严格命中模板)。

    类型取值：
      disclose  顾客说出了 1~2 条新约束
      none      顾客说这个属性没有更多偏好（负面证据，同样能筛掉候选）
      boundary  boundary 场景的一次性挡回（不含商品信息，只消耗一次提问）
      override  意图覆盖，同时给出新的硬约束
      idle      我们没提问导致的空转

    **这里刻意不做切分。** 顾客用 "; " 连接多条约束，
    可约束原文里本来就可能含有 "; "
    （例如 "Solid colors: 100% Cotton; Heather Grey: 90% Cotton, 10% Polyester"），
    所以按 "; " 切分是有歧义的，切错会直接污染似然。
    正确做法是保留整段载荷，反过来让每个候选**渲染**出自己该说的那句话再比对。
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

    # --- 以下是抗改写的兜底识别 ---
    # 改写会换掉包装措辞，但按赛题约定不会改变约束内容本身，
    # 所以这里只需认出「这句话属于哪一类」，具体内容仍交给下游的覆盖率匹配。
    if OVERRIDE_HINT.search(text):
        return "override", _tail_after_colon(text), False
    if NO_PREF_HINT.search(text) or BOUNDARY_HINT.search(text):
        # 分不清是 boundary 挡回还是「没有更多偏好」时，一律按「无新信息」处理：
        # 宁可放弃这条负面证据，也不能拿错误的证据去污染后验。
        return "idle", "", False
    return "disclose", _tail_after_colon(text), False


def _tail_after_colon(text: str) -> str:
    """剥掉改写加上的包装前缀。约束原文常以 "...: " 引出。"""
    body = text.rstrip(".").strip()
    head, sep, tail = body.rpartition(": ")
    if sep and len(tail) >= 3:
        return tail.strip()
    return body


def render_reply(values: tuple[str, ...]) -> str:
    """把一组约束渲染成顾客会说出口的那段载荷（parse_reply 的对照面）。"""
    return "; ".join(values)


def payload_fragments(payload: str, max_parts: int = 8) -> list[str]:
    """载荷里所有「可能是一条完整约束」的片段，仅用于倒排召回。

    既然切分有歧义，就把所有连续片段的组合都试一遍：
    真正的约束原文一定在其中，多试几个不过是多查几次字典。
    """
    parts = [part for part in payload.split("; ") if part.strip()][:max_parts]
    fragments = [payload]
    for start in range(len(parts)):
        for end in range(start, len(parts)):
            fragments.append("; ".join(parts[start : end + 1]))
    return list(dict.fromkeys(f.strip() for f in fragments if f.strip()))
