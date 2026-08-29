"""决策层：这一轮该问什么、该交几个答案。

## 先看清楚记分规则在奖励什么

单场会话的得分（命中在第 t 轮、排名第 r 位）：

    U(r, t) = 0.50 + 0.30 / r + 0.02 × (11 − t)

两个推论直接决定了整套策略：

1. **多等一轮只花 0.02 分，而从第 1 名掉到第 2 名要花 0.15 分。**
   所以「没把握就先别交」是划算的；把 10 个候选一次性交上去反而很亏。
2. **推荐没命中是免费的**，而且等于白拿一次「这件商品被排除」的确定信息。

于是最优形态不是「每轮交一份 Top-10」，而是
**每轮只押一个最可能的答案，押错就把它划掉，直到信息用尽再一次性摊牌**。

对比一下：候选排在第 5 位时，
一次性交 Top-10 得 0.5 + 0.3/5 + 0.2 = 0.76；
连猜 5 轮、第 5 轮猜中得 0.5 + 0.3 + 0.02×6 = 0.92。

## 交卷：逐候选的机会成本比较

要不要现在就把候选 i 交上去，取决于一个干净的比较：

    现在交，它若是目标 → U(i, t)
    先不交，它若是目标 → 它在未来计划里会被安排到第 τ 轮第 r 位，得 U(r, τ)

**注意这两边都是「以 i 就是目标」为条件的**，所以概率被约掉了，
比较结果几乎不依赖后验概率标定得准不准——这让策略非常稳。

未来的安排怎么算？因为顾客的回答规则是确定的，
「假如 i 是目标」这个世界里，下一句话是什么完全可以预演出来，
于是未来的候选集也能预演出来，再用动态规划排出最优交卷时间表即可。

## 提问：最优实验设计

对每个可选属性，预演每个候选会怎么回答，把候选集切成若干组，
再算切完之后的期望得分，取最高的那个属性。
它会随会话自适应——该问 feature 就问 feature，该问 other 就问 other，
比任何写死的提问顺序都强。
"""

from __future__ import annotations

from .user_model import ALLOWED_ATTRIBUTES, MAX_TURNS, TOP_K, simulate_reply

HIT_WEIGHT = 0.50
MRR_WEIGHT = 0.30
EFF_PER_TURN = 0.02     # 0.20 权重 / 10 轮
PLAN_POOL = 60          # 参与提问规划的候选数（后验质量几乎都集中在这里）

# 当多个属性的期望价值打平时（信念已经确定，问什么都一样），按这个顺序取第一个。
# 把覆盖面最广的 other 放在最前、把注定问不出东西的 category 放在最后，
# 这样万一信念其实是错的，我们至少还在问一个能拿到新信息的问题。
ASK_ORDER = ("other", "feature", "material", "color", "style",
             "size", "use_case", "brand", "budget", "category")


def turn_utility(rank: int, turn: int) -> float:
    return HIT_WEIGHT + MRR_WEIGHT / rank + EFF_PER_TURN * (MAX_TURNS + 1 - turn)


def endgame_plan(probs: list[float], turn: int, top_k: int = TOP_K) -> tuple[float, list[tuple[int, int]]]:
    """假设不再有新信息，用剩余轮次排出最优交卷时间表。

    返回 (期望得分, 时间表)。时间表第 j 项是候选 j 的 (轮次, 名次)；
    排不进剩余轮次的候选记为 (0, 0)，代表它拿不到分。

    probs 用**绝对**概率，于是不同分组的价值可以直接相加。
    """
    n = len(probs)
    if n == 0 or turn > MAX_TURNS:
        return 0.0, []

    future = [0.0] * (n + 1)                 # f_{t+1}[k]
    choices: dict[int, list[int]] = {}
    for t in range(MAX_TURNS, turn - 1, -1):
        base = HIT_WEIGHT + EFF_PER_TURN * (MAX_TURNS + 1 - t)
        current = [0.0] * (n + 1)
        picked = [0] * (n + 1)
        for k in range(n - 1, -1, -1):
            best, chosen = future[k], 0      # L = 0：这一轮什么都不交
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
    """预演：若目标分别是各个候选，本轮提问会得到哪种回答。"""
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
    """下一次「交卷真的算数」最早是哪一轮。

    意图覆盖场景在新意图到达前，命中不会被记录（新意图固定在第 3 或第 4 轮到）。
    规划时必须诚实面对这一点，否则动态规划会以为自己能在第 2 轮拿分，
    从而低估「多问一个问题」的价值——而那两轮本来就是白送的提问机会。
    """
    if scoreable or turn >= 3:
        return turn + 1
    return 3


def choose_ask(index, belief, pids: list[int], probs: list[float], turn: int, horizon: int):
    """挑期望价值最高的提问属性，并返回它导致的候选集划分。"""
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
    """若现在不交，每个候选将来能拿到的分（以「它就是目标」为条件）。"""
    result: dict[int, float] = {}
    for members in groups.values():
        _, schedule = endgame_plan([prob_of[pid] for pid in members], horizon)
        for pid, (slot_turn, slot_rank) in zip(members, schedule):
            result[pid] = turn_utility(slot_rank, slot_turn) if slot_rank else 0.0
    return result


def choose_submission(pids: list[int], turn: int, future: dict[int, float], scoreable: bool) -> int:
    """决定本轮交几个：逐位比较「现在交」与「留到将来」，取最优前缀。"""
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
