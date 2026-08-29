# v1.5 Agent 优化实验报告

日期：2026-08-29  
主数据：`data/public_set.jsonl`（官方 200 条开发会话）  
回归数据：`data/customer_probe.jsonl`（187 条自生成 profile 组合）  
基线：v1.4（Hit@10=1.0，MRR=0.811940，MTTC=2.61，Score=0.911382）

## 1. 规则与验收标准

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

1. 不修改官方 evaluator、catalog 或公开标签。
2. 官方 Hit@10 必须保持 1.0。
3. 官方 TechnicalScore 必须严格高于 v1.4。
4. `customer_probe` 只做回归。
5. 不引入向量库或外部模型。

本轮实验两个想法：

1. 若能把目标排到更靠前，是否值得再多空几轮推荐。
2. 微调 FTS5 分字段 BM25 权重（title / categories / features / details / store / description）。

## 2. 方法

### 方向 1：多轮延迟交卷

v1.4 只在 **第 1 轮且没有强约束** 时交空列表。剩余 rank≥5 的会话多半发生在第 2 轮：已经拿到泛化约束（如 `100% Polyester; Imported`），但候选仍然很挤。

新增开关（默认关，除非写入 final）：

- `delay_until_distinctive` + `delay_max_empty`：没有强约束就继续空，直到达到上限。
- `delay_until_n_constraints`：已披露约束条数不足 N 时继续空。
- `delay_uncertain` + `delay_min_margin`：重排第 1/2 名分差过小则继续空。

硬约束：若本轮已经不再提问，必须交卷，避免 10 轮全空造成 miss。

### 方向 2：BM25 字段权重

默认权重为 `title=6, categories=4, features=2.5, details=2.5, store=1.5, description=1.0`。
做成 `bm25_field_weights` 列表，每次只改一个字段或做一个轻组合。

## 3. 官方公开集结果

机器可读记录：`runs/v6_delay_bm25_attempts.json`。

### 3.1 多轮延迟

| 方法 | Hit@10 | MRR | MTTC | Score | ΔScore | 结论 |
|---|---:|---:|---:|---:|---:|---|
| v1.4 复测 | 1.000 | 0.811940 | 2.610 | 0.911382 | — | 基线 |
| delay until distinctive, max 2 | 1.000 | 0.823810 | 2.900 | 0.909143 | -0.002239 | 拒绝；效率损失大于 MRR |
| delay until distinctive, max 3 | 0.995 | 0.874435 | 3.190 | 0.916030 | +0.004648 | 拒绝；出现 miss |
| **delay until 2 constraints, max 2** | **1.000** | **0.818940** | 2.645 | **0.912782** | **+0.001400** | **单点采用** |
| delay until 3 constraints, max 2 | 1.000 | 0.820482 | 3.005 | 0.906045 | -0.005337 | 拒绝 |
| delay uncertain, margin 1–4, max 2 | 1.000 | 0.827810 | 2.98–3.05 | 0.907–0.909 | 负 | 拒绝；空得太多 |
| delay uncertain, margin 2, max 3 | 0.995 | 0.882018 | 3.460 | 0.912905 | +0.001523 | 拒绝；出现 miss |

结论：再空一轮 **可以** 抬高 MRR，但超过 2 轮空列表或“分差不够就空”很容易 miss。
只在「约束还不满 2 条」时最多空 2 轮，是唯一既保 Hit 又涨分的延迟策略。

### 3.2 BM25 字段权重

| 方法 | Hit@10 | MRR | MTTC | Score | ΔScore | 结论 |
|---|---:|---:|---:|---:|---:|---|
| **title 6→4** | **1.000** | **0.816815** | 2.605 | **0.912945** | **+0.001563** | **单点采用** |
| title 8 / 10 | 1.000 | 0.801–0.808 | 2.61–2.62 | 0.908–0.910 | 负 | 拒绝 |
| categories 2 | 0.995 | 0.790 | 2.685 | 0.901 | -0.011 | 拒绝；miss |
| categories 6 | 1.000 | 0.792 | 2.565 | 0.906 | -0.005 | 拒绝 |
| features 4 | 1.000 | 0.814 | 2.590 | 0.912343 | +0.000961 | 弱于降 title |
| features 6 / 8 | 1.000 | 0.794–0.808 | 2.56–2.58 | 0.907–0.911 | 负或持平 | 拒绝 |
| details 4 / 6 | 1.000 | 0.801 | 2.60 | 0.908 | 负 | 拒绝 |
| store 0.5 / 3 | 1.000 | 0.812 | 2.610 | 0.911382 | 0 | 无变化 |
| description 0.5 | 1.000 | 0.792 | 2.585 | 0.906 | 负 | 拒绝 |
| description 2 | 1.000 | 0.816 | 2.625 | 0.912157 | +0.000775 | 弱于降 title |
| features+details 4 | 1.000 | 0.806 | 2.575 | 0.910 | 负 | 拒绝 |
| title 8 + features 4 | 1.000 | 0.803 | 2.585 | 0.909 | 负 | 拒绝 |
| title 4 + features 6 | 1.000 | 0.787 | 2.560 | 0.905 | 负 | 拒绝 |

约束主要来自 features/details 原文，但把这两列加得太重会放大泛词（leather、imported）。
略降 title 权重，让类目和短语精确匹配少受热门标题干扰，是本轮唯一稳定的 BM25 增益。

### 3.3 组合

| 方法 | Hit@10 | MRR | MTTC | Score | ΔScore |
|---|---:|---:|---:|---:|---:|
| delay until 2 constraints + title=4 | **1.000** | **0.825260** | 2.640 | **0.914778** | **+0.003396** |

两项近似加性，Hit 保持 1.0。

## 4. 采用项与分场景变化

采用：

```text
delay_until_n_constraints = 2
delay_max_empty = 2
bm25_field_weights = [4.0, 4.0, 2.5, 2.5, 1.5, 1.0]
```

保留 v1.4 的 `delay_generic_first=True`。

官方分场景（v1.4 → v1.5）：

| 场景 | MRR | MTTC |
|---|---|---|
| Buying | 0.819911 → **0.831612** | 2.2125 → 2.2875 |
| Browsing | 0.781905 → **0.790987** | 2.2875 → 2.2750 |
| Boundary | 0.810000 → **0.950000** | 3.8 → 4.0 |
| Intent Override | 0.871429 → 0.858135 | 4.133 → 4.100 |

Boundary 受益最大：第 2 轮仍无约束时再空一轮，等 typed 问题。Override MRR 略降，但总分仍升。

## 5. Customer probe 回归

| 数据 | 版本 | Hit@10 | MRR | MTTC | Score | ΔScore |
|---|---|---:|---:|---:|---:|---:|
| customer probe | v1.4 | 1.000 | 0.802432 | 2.625668 | 0.908216 | — |
| customer probe | v1.5 | 1.000 | **0.816544** | 2.657754 | **0.911808** | **+0.003592** |

方向一致。记录：`runs/v6_customer_probe_combo.json`。

## 6. 最终版本决策

| 数据 | 版本 | Hit@10 | MRR | MTTC | Score | ΔScore |
|---|---|---:|---:|---:|---:|---:|
| 官方 public | v1.4 | 1.000000 | 0.811940 | 2.610000 | 0.911382 | — |
| 官方 public | v1.5 | 1.000000 | **0.825260** | 2.640000 | **0.914778** | **+0.003396** |

因此更新默认版本为 **v1.5**。

未采用：等到强约束才交卷（max 3 会 miss）、按重排分差延迟、升高 title/features/categories 权重。

## 7. 风险

1. 再空一轮依赖「下一问仍能拿到约束」。私有集若大量会话第 2 问仍空，MTTC 会上升。
2. Override MRR 在公开集和 probe 上都略降，若终评 Override 占比更高，收益会被稀释。
3. title 权重 4 是公开集网格上的局部最优，不能外推成“标题越不重要越好”。

## 8. 机器可读记录

- `runs/v6_delay_bm25_attempts.json`
- `runs/v6_customer_probe_combo.json`
- `local/public_eval/metrics.json`
- `local/customer_eval/metrics.json`
- `snapshots/v1.5/`
