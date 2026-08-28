# v1.4 Agent 优化实验报告

日期：2026-08-28  
主数据：`data/public_set.jsonl`（官方 200 条开发会话）  
回归数据：`data/customer_probe.jsonl`（187 条自生成 profile 组合，复用公开目标）  
基线：v1.3（Hit@10=1.0，MRR=0.755526，MTTC=2.44，Score=0.897858）

## 1. 规则与验收标准

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

1. 不修改官方 evaluator、catalog 或公开标签。
2. 官方 Hit@10 必须保持 1.0。
3. 官方 TechnicalScore 必须严格高于 v1.3。
4. `customer_probe` 只做回归，不用于主检索参数选择。
5. 终评可能断网，不引入向量库、外部模型或 API。

本轮针对三个方向做对照：动态提问、用轮次换排序、轻量商品相似度。

## 2. 方法

评测在目标 **第一次** 进入 Top-10 时锁死 `best_rank` 并结束会话。
v1.3 已把 Hit@10 做到 1.0，剩余瓶颈是首次命中时的名次（24 条会话 rank≥7）。

实现全部做成默认关闭的开关，基线 v1.3 复测分数不变。

### 方向 1：动态提问

- `skip_covered_attrs`：已披露约束对应的 typed 属性不再问（feature 可多条，不跳过）。
- `dynamic_typed_ask`：`other` 之后，按当前候选分支上属性取值熵选择下一个 typed 问题。
- `ask_mode=feature_first`：静态重排，`other` 后先问 feature/style，material 放到后面。

### 方向 2：用轮次换排序

评测器不会“再排一轮把第 10 名抬上去”，除非本轮目标不在 Top-10。
因此合法做法是：**约束还太弱时先交空推荐**，继续提问。

- `delay_weak_recs`：仅 browsing/boundary 的第 1 轮，且尚无强约束。
- `delay_generic_first`：任意场景第 1 轮，只要还没有强约束。

### 方向 3：轻量商品相似度（不用向量库）

- `shown_dissimilarity_weight`：与本会话已展示且未命中商品的 feature token Jaccard 越高，越往下调。
- `neighbor_overlap_weight`：向已精确命中强约束的锚点商品靠拢。

完整商品向量库未实现：竞赛把重型向量库列为 out of scope，且当前失败模式是同类目精确 metadata 的 tie-break，不是语义错配。

## 3. 官方公开集结果

机器可读记录：`runs/v5_direction_attempts.json`。

| 方法 | Hit@10 | MRR | MTTC | Score | ΔScore | 结论 |
|---|---:|---:|---:|---:|---:|---|
| v1.3 复测 | 1.000 | 0.755526 | 2.440 | 0.897858 | — | 基线 |
| skip_covered_attrs | 1.000 | 0.728645 | 2.415 | 0.890294 | -0.007564 | 拒绝 |
| dynamic_typed_ask | 0.995 | 0.730970 | 2.470 | 0.887391 | -0.010467 | 拒绝；出现 miss |
| skip_covered + dynamic | 0.995 | 0.730970 | 2.470 | 0.887391 | -0.010467 | 拒绝；出现 miss |
| feature_first | 0.990 | 0.726222 | 2.440 | 0.884067 | -0.013791 | 拒绝；出现 miss |
| feature_first + skip_covered | 0.990 | 0.726222 | 2.440 | 0.884067 | -0.013791 | 拒绝；出现 miss |
| **delay_weak_recs** | **1.000** | **0.783353** | 2.505 | **0.904906** | **+0.007048** | 有效，但是子集 |
| **delay_generic_first** | **1.000** | **0.811940** | 2.610 | **0.911382** | **+0.013524** | **采用** |
| shown_dissimilarity 0.5–8 | 1.000 | 0.706–0.748 | 2.44–2.45 | 0.883–0.896 | 负 | 拒绝 |
| neighbor_overlap 0.5–4 | 1.000 | 0.755526 | 2.440 | 0.897858 | 0 | 拒绝；无变化 |

方向 1 会改变 `shown` 排除轨迹和约束披露顺序，Hit/MRR 都掉。
方向 3 的已展示惩罚伤害同簇目标；锚点重叠与现有精确匹配高度共线。

## 4. 采用项与分场景变化

采用 `delay_generic_first=True`。

官方分场景（v1.3 → v1.4）：

| 场景 | MRR | MTTC |
|---|---|---|
| Buying | 0.748442 → **0.819911** | 1.95 → 2.2125 |
| Browsing | 0.712336 → **0.781905** | 2.15 → 2.2875 |
| Boundary | 0.810000 → 0.810000 | 3.6 → 3.8 |
| Intent Override | 0.871429 → 0.871429 | 4.133 → 4.133 |

总分提升全部来自 MRR。Efficiency 因 MTTC 2.44→2.61 略降（0.856→0.839），但 0.30×MRR 的增益远大于 0.20×Efficiency 的损失。
Override 几乎不变：覆盖消息发出前本就不计分。

## 5. Customer probe 回归

| 数据 | 版本 | Hit@10 | MRR | MTTC | Score | ΔScore |
|---|---|---:|---:|---:|---:|---:|
| customer probe | v1.3 | 1.000 | 0.751263 | 2.454545 | 0.896288 | — |
| customer probe | v1.4 | 1.000 | **0.802432** | 2.625668 | **0.908216** | **+0.011928** |

方向一致，Hit@10 仍为 1.0。记录：`runs/v5_customer_probe_delay_generic_first.json`。

## 6. 最终版本决策

| 数据 | 版本 | Hit@10 | MRR | MTTC | Score | ΔScore |
|---|---|---:|---:|---:|---:|---:|
| 官方 public | v1.3 | 1.000000 | 0.755526 | 2.440000 | 0.897858 | — |
| 官方 public | v1.4 | 1.000000 | **0.811940** | 2.610000 | **0.911382** | **+0.013524** |

因此更新默认版本为 **v1.4**。未采用动态提问与商品相似度。

## 7. 风险

1. 该策略依赖“首轮无强约束时，下一轮提问仍能拿到可用约束”。若私有集大量会话首轮之后仍然只有泛词，MTTC 会上升且 MRR 不一定补回来。
2. Public 200 条上调参存在过拟合；私有 800 无法在提交前验证。
3. 动态提问与相似度开关保留在代码中且默认关闭，便于后续复现，不进入 `final` 配方。

## 8. 机器可读记录

- `runs/v5_direction_attempts.json`
- `runs/v5_customer_probe_delay_generic_first.json`
- `local/public_eval/metrics.json`
- `local/customer_eval/metrics.json`
- `snapshots/v1.4/`
