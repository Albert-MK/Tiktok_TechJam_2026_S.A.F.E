"""策略开关面板。

v2.0 的可调参数比 v1.5 少了一个数量级：老版本有二十多个手工调出来的打分权重，
新版本的排序完全由「先验 × 似然」的贝叶斯推理决定，交卷和提问由动态规划决定，
真正需要人来定的只剩下几个校准量。

本地做实验时可以用环境变量临时覆盖：

    AGENT_EXP_FLAGS='{"temperature": 3.0}' python -m evaluator.local_evaluator
"""

from __future__ import annotations

import json
import os

VERSION = "v2.0"
STRATEGY = os.environ.get("AGENT_STRATEGY", "bayes").strip().lower()

PRESETS = {
    # 主力配方：完整的逆向模拟 + 贝叶斯后验 + 动态规划决策。
    "bayes": {
        "pool_size": 400,        # 保留多少候选参与推理
        "temperature": 1.0,      # 后验软化系数；越大越不敢下重注
        "leak_gap": 9.0,         # 「目标根本不在候选池里」的兜底概率
        "sequential": True,      # 允许逐轮单点押注（关掉就退化成每轮交 Top-10）
        "eliminate": True,       # 利用「推过没命中 ⇒ 一定不是它」这一确定信息
        "ask": True,             # 允许追问
    },
    # 消融用：不做逐轮押注，每轮直接交满 Top-10。
    "batch": {
        "pool_size": 400,
        "temperature": 1.0,
        "leak_gap": 9.0,
        "sequential": False,
        "eliminate": True,
        "ask": True,
    },
    # 消融用：关掉「未命中即排除」。
    "no_elimination": {
        "pool_size": 400,
        "temperature": 1.0,
        "leak_gap": 9.0,
        "sequential": True,
        "eliminate": False,
        "ask": True,
    },
    # 消融用：不追问，只靠开场白。
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
