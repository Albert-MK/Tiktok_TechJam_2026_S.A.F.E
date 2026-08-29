"""信念状态：对「哪件商品才是目标」维护一个后验分布。

## 核心思想

每听到一句话，就对每个候选商品 p 问一句反事实：

    「如果目标是 p，顾客这一轮**应该**说什么？」

用 `user_model` 重放一遍生成过程，把预测和实听对比，得到惩罚项。于是

    log P(p | 对话) = log 先验(p) − Σ 各轮惩罚(p)

三类证据都在这里汇合：

* **正面证据**：顾客说出的约束，与 p 的意图卡逐位比对。
* **负面证据**：顾客说「这个属性没有更多偏好了」——能筛掉那些「本该还有话说」的候选。
* **淘汰证据**：上一轮推过却没命中，说明那些商品**确定**不是目标（评测规则是精确 ID 匹配）。
  这是完全无损的信息，代价为零，却被朴素的检索式做法整个丢掉了。

## 为什么惩罚是「软」的

所有惩罚都是有限值，没有一处硬过滤。这样即使主办方替换了意图卡来源、
或对措辞做了同义改写，候选集也永远不会为空：匹配度会平滑下降，
打分自动退化成「词面相似度 + 先验」，也就是一个不算差的传统检索器。
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

# 惩罚强度（对数似然尺度）。先验 log1p(评论数) 最大约 13，
# 因此单条约束不匹配的代价必须明显高于先验跨度，才能让证据压过热度。
W_CONSTRAINT = 22.0      # 一条约束完全对不上
W_REPLY = 30.0           # 整段回复对不上（一段通常含 1~2 条约束）
W_SILENT = 26.0          # 顾客说了话，候选却预测「无话可说」
W_CATEGORY_FLAT = 20.0   # 粗类目对不上的固定代价
W_CATEGORY = 14.0        # 粗类目对不上的相似度分级代价
W_NONE = 16.0            # 顾客说「没有更多偏好」，候选却还有话要说
ORDER_DISCOUNT = 0.45    # 约束内容对得上但位置不对时保留的相似度比例
CONTAINMENT_SIM = 0.6    # 约束原文能在商品文本里找到时的相似度下限
COVERAGE_CAP = 0.9       # 抗改写的关键词覆盖率通道能给到的最高匹配度
LEXICAL_RESCUE_PENALTY = 15.0  # 最优候选的惩罚超过这个值就触发词面兜底召回
BROWSING_PRIOR_MATCH = 0.35  # 场景不明时，「这句话其实不含约束」这一假设的基准分


def similarity(a: str, b: str) -> float:
    """两段约束文本的相似度，0~1。用于容忍同义改写。"""
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
    __slots__ = ("pid", "penalty", "disclosed")

    def __init__(self, pid: int, penalty: float, disclosed: frozenset[str]) -> None:
        self.pid = pid
        self.penalty = penalty
        self.disclosed = disclosed


class Belief:
    """单个会话的信念状态。"""

    def __init__(self, index: CatalogIndex, pool_size: int = 400, temperature: float = 1.0,
                 leak_gap: float = 9.0) -> None:
        self.index = index
        self.pool_size = pool_size
        self.temperature = temperature
        self.leak_gap = leak_gap

        self.scenario = SCENARIO_BROWSING
        self.category = ""
        self.boundary_seen = False
        self.override_applied = True     # 非 override 场景一开始就可计分
        self.fuzzy = False               # 模板解析失败过 => 启用抗改写打分通道
        self.safe_from_turn = 1          # 从第几轮起，「未命中」才是可信的否定证据
        self.observed: list[str] = []    # 已听到的约束原文（用于回退召回）

        self.candidates: dict[int, Candidate] = {}
        self.eliminated: set[int] = set()
        self._log: list[tuple] = []      # 观测日志，用于给新进候选补算历史

    # -- 观测 ---------------------------------------------------------------

    def observe_opening(self, message: str) -> None:
        scenario, category, constraint, strict = parse_opening(message)
        if not strict:
            # 模板没对上（多半是措辞被改写了）。改走抗改写通道：
            # 类目从消息里反查已知类目表得到，场景则留作未知、由两种假设各算一次。
            self.fuzzy = True
            category = self.index.find_category(message)
            constraint = message.strip()
        self.scenario = scenario
        self.category = category
        if scenario == SCENARIO_OVERRIDE:
            # 覆盖场景在新意图到达前无法计分，这一点决定了前两轮的策略。
            self.override_applied = False
        elif scenario == SCENARIO_UNKNOWN:
            # 分不清是不是覆盖场景时，推荐照交（未命中本来就免费），
            # 但「未命中即排除」必须等到第 4 轮之后才敢用——
            # 覆盖最晚在第 4 轮到达，从那之后的未命中才一定是真的否定证据。
            self.safe_from_turn = 4
        if constraint:
            self.observed.append(constraint)
        self._log.append(("open", scenario, category, constraint))
        self._seed_pool(constraint)

    def observe_turn(self, message: str, ask: str | None) -> None:
        kind, payload, strict = parse_reply(message)
        if not strict:
            self.fuzzy = True
        if kind == "boundary":
            # 只消耗一次提问，不含任何商品信息。
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
        """上一轮推荐未命中 => 这些商品确定不是目标。"""
        for asin in asins:
            pid = self.index.pid_of.get(asin)
            if pid is not None:
                self.eliminated.add(pid)
                self.candidates.pop(pid, None)

    # -- 候选池维护 ---------------------------------------------------------

    def _seed_pool(self, constraint: str) -> None:
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
        # 新听到的约束可能指向此前被剪掉的商品，按原文精确召回补进来。
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

        # 兜底召回：如果没有任何候选能解释刚听到的这句话，说明目标很可能
        # 压根不在池子里（意图卡来源不同、措辞被改写、类目解析偏了……）。
        # 这时就退回纯词面检索，把搜索面重新放宽。
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
        """从头重放整段对话，算出候选 pid 的累计惩罚。"""
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
            # 类目是确定性推导出来的，对不上就该重罚：固定项保证任何「热门但类目不对」
            # 的商品都压不过正确候选（先验跨度只有 log1p(评论数) ≈ 13）；
            # 分级项只在类目完全解析不出来时提供平滑退化。
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
            # 场景不明：买家会说 hard[0]，覆盖场景会说 soft 的最后一条，
            # 而 browsing 根本不带约束。取三种假设里最合理的那个。
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
            # 覆盖消息给出的是目标的 hard_constraints[0]。
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
            # 顾客说没有更多偏好，候选却预测还能说出东西 => 不一致。
            cand.penalty += W_NONE * len(predicted)
        else:
            # 让候选渲染出「它该说的那句话」，整段与实听载荷比对。
            # 只有真正的目标能一字不差地对上，因此这一步的区分度极高。
            rendered = render_reply(predicted)
            if not predicted:
                cand.penalty += W_SILENT
            elif rendered != payload:
                cand.penalty += W_REPLY * (1.0 - self._match(pid, rendered, payload))
        if predicted:
            cand.disclosed = cand.disclosed | set(predicted)

    def _match(self, pid: int, expected: str, heard: str) -> float:
        """候选在「该位置本该说的话」与「实际听到的话」之间的匹配度。

        逐位精确比对是主路径；位置错乱、同义改写、意图卡来源不同这些情况，
        由「任意位置匹配」「原文包含」「关键词覆盖率」三条兜底通道兜住。
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
            # 抗改写通道：改写只换包装措辞，约束内容本身会保留下来，
            # 所以要看的是「预测内容的关键词有多少出现在实听文本里」（召回率），
            # 而不是两段文本整体有多像——后者会被包装词稀释。
            # 只在模板解析失败时启用，避免拉低逐字场景下的区分度。
            best = max(best, COVERAGE_CAP * self._coverage(expected, heard))
        if best < CONTAINMENT_SIM and heard and heard.lower() in self.index.blobs[pid]:
            best = CONTAINMENT_SIM
        return min(best, 1.0)

    def _coverage(self, expected: str, heard: str) -> float:
        """预测内容的关键词在实听文本中的 IDF 加权召回率。"""
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

    # -- 后验 ---------------------------------------------------------------

    def score(self, pid: int) -> float:
        cand = self.candidates.get(pid)
        if cand is None:
            return -math.inf
        return self.index.log_prior[pid] - cand.penalty

    def posterior(self) -> tuple[list[int], list[float], float]:
        """返回 (按后验降序的商品 id, 概率, 目标不在候选池中的概率)。"""
        if not self.candidates:
            return [], [], 1.0
        scored = [(pid, self.score(pid)) for pid in self.candidates]
        scored.sort(key=lambda kv: -kv[1])
        best = scored[0][1]
        temp = max(self.temperature, 1e-6)
        weights = [math.exp((value - best) / temp) for _, value in scored]
        # 泄漏项：目标有可能根本不在候选池里（改写、召回不足等）。
        leak = math.exp(-self.leak_gap / temp)
        total = sum(weights) + leak
        pids = [pid for pid, _ in scored]
        return pids, [w / total for w in weights], leak / total
