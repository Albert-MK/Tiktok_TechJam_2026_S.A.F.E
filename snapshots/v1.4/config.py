"""Agent 策略开关（配置表）。

这份文件不负责“怎么搜商品”，只负责告诉 Agent：
  - 当前用哪一版策略（VERSION / STRATEGY）
  - 哪些功能打开、哪些关闭
  - 分数权重取多少

非计算机同学可以把它理解成「开关面板 + 配方表」：
  agent.py 是厨师，config.py 是菜谱。

本地做对比实验时，可以通过环境变量临时改开关，
例如 AGENT_STRATEGY=final、AGENT_EXP_FLAGS='{"bm25_coef":0.04}'。
正式评分默认使用 PRESETS["final"]，也就是当前 v1.4。
"""

from __future__ import annotations

import json
import os


def _flag(name: str, default: str = "1") -> bool:
    """把环境变量读成 True/False。

    常见写法：
      AGENT_ASK=1 / true / on  -> True
      AGENT_ASK=0 / false / off -> False
    """
    return os.environ.get(name, default).strip().lower() not in {"0", "false", "no", "off"}


# 当前默认发布版本号（文档与快照应对齐这个值）。
VERSION = "v1.4"

# 默认策略名。可通过环境变量 AGENT_STRATEGY 覆盖，例如 baseline / final。
STRATEGY = os.environ.get("AGENT_STRATEGY", "final").strip().lower()

# ---------------------------------------------------------------------------
# 预设配方表
# 每个 key 是一套完整开关组合，方便复现历史实验。
# 真正线上/本地默认用的是最下面的 "final"。
# ---------------------------------------------------------------------------
PRESETS = {
    # 官方弱基线：几乎不记历史、也不提问，每轮只用当前这句话检索。
    "baseline": {
        "accumulate": False,
        "ask": False,
        "override_reset": False,
        "phrase_rerank": False,
        "profile_boost": False,
        "ask_mode": "typed",
        "retrieve_k": 10,
    },
    # 只累积用户说过的词，仍然不提问。
    "accumulate_only": {
        "accumulate": True,
        "ask": False,
        "override_reset": True,
        "phrase_rerank": False,
        "profile_boost": False,
        "ask_mode": "typed",
        "retrieve_k": 40,
    },
    # 按固定属性顺序提问（material → color → ...），并累积约束。
    "ask_typed": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "phrase_rerank": False,
        "profile_boost": False,
        "ask_mode": "typed",
        "retrieve_k": 40,
    },
    # 先问 other：模拟器会一次吐出剩余约束，通常更快摸清需求。
    "ask_other_first": {
        "accumulate": True,
        "ask": True,
        "override_reset": True,
        "phrase_rerank": False,
        "profile_boost": False,
        "ask_mode": "other_first",
        "retrieve_k": 40,
    },
    # 混合检索 + 重排，typed 提问。
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
    # 混合检索 + 重排，other 优先；Override 后清空旧约束。
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
    # 同上，但 Override 后保留旧约束（实验证明通常更好）。
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
    # 在 keep 基础上加入评分/热度微弱加权。
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
    # 候选池更大（150），用于验证扩大召回是否有用。
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
    # ---------------------------------------------------------------------
    # 当前默认冠军配方（v1.4）
    # 核心含义（白话）：
    #   1) 会提问，且优先问 other，尽快拿到细节；
    #   2) 多路召回 + 短语重排；
    #   3) 长短语命中、叶类目、店铺匹配都有加分；
    #   4) 已展示过却没命中的商品后续排除；
    #   5) v1.3：字段条目前缀证据 + Override 后才用画像标签弱加权；
    #   6) v1.4：首轮若还没有强约束，先不交 Top-10，避免把目标锁在尾部。
    # ---------------------------------------------------------------------
    "final": {
        "accumulate": True,                 # 累积多轮约束，不要每轮忘掉
        "ask": True,                        # 允许追问
        "override_reset": True,             # 识别“ignore earlier preference”
        "override_keep": True,              # Override 后保留旧约束（不清空）
        "phrase_rerank": True,              # 召回后再做精细打分排序
        "profile_boost": True,              # 评分/评价数轻微加权
        "ask_mode": "other_first",          # 先问 other
        "retrieve_k": 80,                   # 重排前先取约 80 个候选
        "exclude_shown": True,              # 排除本会话已推过且未命中的商品
        "distinctive_exact_bonus": True,    # 长/具体约束精确命中大幅加分
        "category_must_match": True,        # 粗类目对不上则扣分
        "leaf_category_boost": True,        # 叶类目（更细的类）命中加分
        "relaxed_distinctive": True,        # 放宽“有区分度”判定
        "store_match_boost": True,          # 店铺/品牌字段匹配小加分
        "bm25_coef": 0.04,                  # 越信关键词检索排序，该系数越大
        "entry_prefix_weight": 1.1,         # v1.3：features/details 条目前缀一致性
        "profile_tag_weight": 0.03,         # v1.3：画像标签弱加权
        "profile_tags_override_only": True, # v1.3：画像只在 Override 后启用
        "delay_generic_first": True,        # v1.4：首轮无强约束时暂缓交卷
    },
}


def active_config() -> dict:
    """组装最终生效的配置字典。

    优先级（后写覆盖前写）：
      1. PRESETS[STRATEGY]
      2. 若干 AGENT_* 环境变量
      3. AGENT_EXP_FLAGS（JSON，适合做单项实验）
      4. 对缺失开关补默认值，避免 agent.py 里反复写 if key in cfg
    """
    preset = PRESETS.get(STRATEGY, PRESETS["final"])
    cfg = dict(preset)
    cfg.setdefault("override_keep", False)
    cfg.setdefault("exclude_shown", True)

    # ---- 单项环境变量覆盖（便于脚本/命令行快速切换）----
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

    # ---- 批量实验开关：AGENT_EXP_FLAGS='{"leaf_category_boost": true}' ----
    raw_flags = os.environ.get("AGENT_EXP_FLAGS", "").strip()
    if raw_flags:
        try:
            extra = json.loads(raw_flags)
            if isinstance(extra, dict):
                cfg.update(extra)
        except json.JSONDecodeError:
            # JSON 写错时忽略，避免整次评测直接崩掉。
            pass

    # ---- 布尔实验开关：没写就默认 False ----
    for key in (
        "distinctive_exact_bonus",
        "punct_normalize",
        "distinctive_query_focus",
        "title_distinctive_boost",
        "category_must_match",
        "override_clear_old",
        "cover_sort",
        "relaxed_distinctive",
        "semi_distinctive_bonus",
        "features_field_boost",
        "distinctive_partial_boost",
        "full_cover_bonus",
        "leaf_category_boost",
        "title_category_boost",
        "store_match_boost",
        "profile_when_generic_only",
        "popularity_dampen",
        "wide_phrase_retrieve",
        "override_reset_asked",
        "eager_second_other",
        "profile_tags_generic_only",
        "profile_tags_override_only",
        "skip_covered_attrs",
        "dynamic_typed_ask",
        "delay_weak_recs",
        "delay_generic_first",
    ):
        cfg.setdefault(key, False)

    # ---- 数值开关：没写就用保守默认 ----
    cfg.setdefault("bm25_coef", 0.02)
    cfg.setdefault("generic_exact_score", 1.2)
    cfg.setdefault("distinctive_exact_base", 20.0)
    cfg.setdefault("category_miss_penalty", 8.0)
    cfg.setdefault("soft_cover_bonus", 0.0)
    cfg.setdefault("idf_coverage_weight", 0.0)
    cfg.setdefault("route_rrf_weight", 0.0)
    cfg.setdefault("route_rrf_k", 10.0)
    cfg.setdefault("entry_prefix_weight", 0.0)
    cfg.setdefault("profile_tag_weight", 0.0)
    cfg.setdefault("neighbor_overlap_weight", 0.0)
    cfg.setdefault("shown_dissimilarity_weight", 0.0)
    return cfg
