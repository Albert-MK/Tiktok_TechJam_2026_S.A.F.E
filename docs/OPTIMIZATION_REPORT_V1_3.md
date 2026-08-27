# v1.3 Agent 优化实验报告

日期：2026-08-27  
主数据：`data/public_set.jsonl`（官方 200 条开发会话）  
回归数据：`data/customer_probe.jsonl`（187 条自生成 profile 组合，复用公开目标）

## 1. 规则与验收标准

官方评分：

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

本轮遵循以下门槛：

1. 不修改官方 evaluator、catalog 或公开标签。
2. 官方 Hit@10 必须保持 1.0。
3. 官方 TechnicalScore 必须严格高于当前 champion。
4. `customer_probe` 只做 profile/会话种子回归，不用于主检索参数选择。
5. 终评可能断网，因此默认版本不依赖 API、外部模型或重型向量库。

## 2. 基线校准

仓库中的 `local/public_eval` 起初仍是 v1.1 产物（Score 0.883121），
与 `starter/config.py` 的 v1.2 不一致。清除 shell 中残留实验变量后，
重新运行官方 evaluator，确认真实 v1.2 基线：

| 数据 | Hit@10 | MRR | MTTC | Score |
|---|---:|---:|---:|---:|
| 官方 public v1.2 | 1.000000 | 0.753020 | 2.440000 | 0.897106 |
| customer probe v1.2 | 1.000000 | 0.748582 | 2.454545 | 0.895484 |

主要瓶颈已从召回变成排序：全部会话都能命中，但部分目标仍位于 Top-10
尾部。Intent Override 的 MTTC 受协议限制，覆盖消息发出前不能计分。

## 3. 方法调研

官方文档建议的方向包括多路检索、语义重排、结构化状态、动态提问、
安全画像和失败切换。本轮还参考了：

- Clarinet（arXiv 2405.15784）：根据检索分布选择能最大化目标确定性的澄清问题。
- Elasticsearch e-commerce hybrid search：字段检索与 Reciprocal Rank Fusion。
- BM25F 实践：title、attributes、description 分字段赋权。
- 两阶段检索：词法召回后再做结构化或语义重排。

结合本题 evaluator 的确定性机制，约束直接来自商品 metadata，词法一致性
很强；因此优先测试离线、可解释、无需模型的方案。Dense/cross-encoder
没有进入默认实验：它们增加依赖和终评断网风险，且当前剩余问题主要是
精确 metadata 候选之间的排序，不是语义词汇错配。

## 4. 已有开关在 v1.2 上重测

| 方法 | Score | ΔScore | 结论 |
|---|---:|---:|---|
| `punct_normalize` | 0.889141 | -0.007965 | 拒绝；归一化放大噪声 |
| `distinctive_query_focus` | 0.896356 | -0.000750 | 拒绝 |
| `title_distinctive_boost` | 0.897106 | +0.000000 | 拒绝；无变化 |
| `features_field_boost` | 0.894767 | -0.002339 | 拒绝 |

历史 v1.2 已试且未采用的 `generic_match_dampen`、`title_category_boost`、
`popularity_dampen`、`override_clear_old`、扩大候选池等结果保留在
`runs/v3_rank_attempts.json` 与 `docs/VERSION_HISTORY.md`。

## 5. 提问策略实验

| 方法 | Hit@10 | MRR | MTTC | Score | 结论 |
|---|---:|---:|---:|---:|---|
| Override 后重置已问属性 | 1.000 | 0.749187 | 2.420 | 0.896356 | 拒绝 |
| 得到首批约束后立即再问一次 `other` | 0.995 | 0.741423 | 2.395 | 0.892027 | 拒绝；出现 miss |
| 两者组合 | 0.995 | 0.742958 | 2.380 | 0.892787 | 拒绝；出现 miss |

结论：更激进提问虽略降 MTTC，却会改变 `shown` 排除轨迹并伤害 MRR/Hit。
当前 `other → typed → 必要时再 other` 的策略继续保留。

## 6. 检索与全局重排实验

### 6.1 BM25 名次先验

| `bm25_coef` | Score | ΔScore |
|---:|---:|---:|
| 0.03 | 0.891879 | -0.005227 |
| 0.05 | 0.893011 | -0.004095 |
| 0.06 | 0.894166 | -0.002940 |
| 0.08 | 0.894097 | -0.003009 |
| 0.12 | 0.886854 | -0.010252 |

v1.2 的 0.04 保持最优。

### 6.2 稀有词 IDF coverage

通过 FTS5 vocabulary 取得 document frequency，对候选覆盖的稀有 query
token 加权。

| 权重 | Score | ΔScore |
|---:|---:|---:|
| 0.02 | 0.896370 | -0.000736 |
| 0.05 | 0.896204 | -0.000902 |
| 0.10 | 0.892916 | -0.004190 |
| 0.20 | 0.892289 | -0.004817 |
| 0.40 | 0.894214 | -0.002892 |

全部拒绝。BM25 已包含 IDF，再叠加会重复放大稀有但不稳定的 token。

### 6.3 多路 RRF

融合精确短语、类目约束和宽检索列表。

| 权重 / k | Score | ΔScore |
|---|---:|---:|
| 1 / 10 | 0.892888 | -0.004218 |
| 3 / 10 | 0.890126 | -0.006980 |
| 5 / 10 | 0.890506 | -0.006600 |
| 10 / 10 | 0.885589 | -0.011517 |
| 20 / 10 | 0.877333 | -0.019773 |
| 10 / 30 | 0.889756 | -0.007350 |

全部拒绝。不同 route 并非独立信号，RRF 会把多路重复出现的泛化商品抬高。

### 6.4 第一轮组合

| 组合 | Score | ΔScore |
|---|---:|---:|
| BM25 0.06 + IDF 0.02 | 0.895768 | -0.001338 |
| BM25 0.06 + RRF 1/10 | 0.893789 | -0.003317 |
| BM25 0.06 + Override 重置提问 | 0.893620 | -0.003486 |
| IDF 0.02 + RRF 1/10 | 0.891984 | -0.005122 |
| IDF 0.02 + Override 重置提问 | 0.896370 | -0.000736 |
| RRF 1/10 + Override 重置提问 | 0.892888 | -0.004218 |
| BM25 + IDF + RRF | 0.894461 | -0.002645 |
| BM25 + IDF + Override | 0.895212 | -0.001894 |
| BM25 + RRF + Override | 0.894514 | -0.002592 |
| IDF + RRF + Override | 0.891984 | -0.005122 |

没有组合通过门槛。

## 7. 字段条目来源一致性

官方模拟约束来自 `features/details` 条目。新信号仅检查一个已披露的非泛化
约束是否匹配候选原始条目的前缀，并对较早条目给予轻微先验；不构造或读取
任何 private label。

| 权重 | Score | ΔScore |
|---:|---:|---:|
| 0.5 | 0.897106 | +0.000000 |
| 0.7–1.0 | 0.897123 | +0.000017 |
| 1.1–1.7 | **0.897143** | **+0.000037** |
| 1.8 | 0.895894 | -0.001212 |
| 1.9 | 0.895910 | -0.001196 |
| 2.0 | 0.895910 | -0.001196 |
| 4.0 | 0.896043 | -0.001063 |
| 8.0–12.0 | 0.896181 | -0.000925 |
| 20.0 | 0.896431 | -0.000675 |

采用保守边界 `entry_prefix_weight=1.1`。会话级变化是
`public_0154` rank 10→8；其他会话不变。customer probe 也从
0.895484 微升至 0.895502。

## 8. 匿名 profile 实验

### 8.1 全局弱加权

| 权重 | Score | ΔScore |
|---:|---:|---:|
| 0.01 | 0.897262 | +0.000156 |
| 0.03 | 0.897389 | +0.000283 |
| 0.05 | 0.895937 | -0.001169 |
| 0.10 | 0.894399 | -0.002707 |
| 0.20 | 0.894578 | -0.002528 |
| 0.50 | 0.886864 | -0.010242 |

全局 0.03 虽提升总分，但 Buying MRR 0.748130→0.743705，且随机 profile
回归集轻微下降，因此不采用全局方案。

### 8.2 条件化加权

| 条件 | Score | ΔScore | 结论 |
|---|---:|---:|---|
| 无 distinctive 约束时，权重 0.03 | 0.897425 | +0.000319 | 未采用；仍伤 Buying |
| 仅 Override，权重 0.01/0.02/0.025 | 0.897070 | -0.000036 | 拒绝 |
| 仅 Override，权重 0.03 | **0.897820** | **+0.000714** | 采用 |
| 仅 Override，权重 0.035/0.04/0.05 | 0.897070 | -0.000036 | 拒绝 |

0.03 的提升来自排序边界变化，不代表连续线性收益，因此保留非常小的权重，
并明确限制在 Agent 已从用户消息识别到 Override 之后。Buying、Browsing
与 Boundary 均不受该信号影响。

## 9. 最终组合与版本决策

最终采用：

```text
entry_prefix_weight = 1.1
profile_tag_weight = 0.03
profile_tags_override_only = true
```

| 数据 | 版本 | Hit@10 | MRR | MTTC | Score | ΔScore |
|---|---|---:|---:|---:|---:|---:|
| 官方 public | v1.2 | 1.000000 | 0.753020 | 2.440000 | 0.897106 | — |
| 官方 public | v1.3 | 1.000000 | **0.755526** | 2.440000 | **0.897858** | **+0.000752** |
| customer probe | v1.2 | 1.000000 | 0.748582 | 2.454545 | 0.895484 | — |
| customer probe | v1.3 | 1.000000 | **0.751263** | 2.454545 | **0.896288** | **+0.000804** |

官方分场景变化：

- Buying MRR：0.748130→0.748442。
- Intent Override MRR：0.855556→0.871429。
- Browsing MRR：0.712336，不变。
- Boundary MRR：0.810000，不变。

因此更新默认版本为 v1.3。提升来自 MRR，Hit 与 MTTC 均没有退化。

## 10. 风险与后续方向

1. Public 只有 200 条，且 v1.2/v1.3 都在其上调参；private 800 的真实提升
   无法在提交前验证。
2. Customer probe 复用了公开目标，不是独立 holdout；其价值仅是不同 profile
   和 sample-id 种子的回归检查。
3. 0.03 profile 权重存在明显排序阈值效应，必须保持 Override-only，不能外推
   为更强个性化。
4. 下一阶段若有独立 holdout，优先验证字段来源信号、Override profile 信号和
   分场景置信区间；有稳定离线模型运行环境后，再单独比较 lexical、dense 和
   cross-encoder，而不是直接叠加到当前排序器。

## 11. 机器可读记录

- `runs/v12_baseline_recheck.json`
- `runs/v4_optimization_attempts.json`
- `runs/v4_entry_attempts.json`
- `runs/v4_entry_refine_attempts.json`
- `runs/v4_entry_boundary_attempts.json`
- `runs/v4_profile_attempts.json`
- `runs/v4_conditional_attempts.json`
- `runs/v13_customer_entry_profile_override_combo.json`
- `local/public_eval/metrics.json`
- `local/customer_eval/metrics.json`

