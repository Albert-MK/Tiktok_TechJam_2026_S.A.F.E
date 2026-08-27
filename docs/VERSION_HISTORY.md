# 算法版本迭代记录

公开开发集 200 条（Buying 80 / Browsing 80 / Intent Override 30 / Boundary 10）。  
评分：`TechnicalScore = 0.5×Hit@10 + 0.3×MRR + 0.2×Efficiency`，`Efficiency = clip((11−MTTC)/10, 0, 1)`。  
未命中记 MTTC=11。只改 `starter/agent.py`，不改官方 evaluator 与标签。

当前发布版本：**v1.3**（代码在 `starter/`）。  
快照：`snapshots/v1/`、`snapshots/v1.1/`、`snapshots/v1.3/`。

---

## 总览

| 版本 | Hit@10 | MRR | MTTC | TechnicalScore | 相对上一采用版 |
|------|--------|-----|------|----------------|----------------|
| Baseline（官方弱 BM25） | 0.125 | 0.068 | 9.81 | 0.107 | — |
| v0.1 只累积不问 | ≈0.05（40 条子集） | — | ~10.6 | 0.036 | 无效 |
| v0.2 按属性提问 | 0.775（40 条） | 0.528 | 4.98 | 0.666 | 提问是最大单点 |
| v0.3 先问 `other` | 0.860 | 0.536 | 3.66 | 0.738 | 全量 |
| v0.4 混合检索+重排 | 0.880–0.925 | — | — | 0.740–0.777 | 召回/排序 |
| v0.5 Override 保留旧槽 | 0.915 | 0.530 | 3.16 | 0.773 | Override 好转 |
| v0.6 评分加权（不把 tags 进检索） | 0.925 | 0.581 | 3.05 | 0.796 | |
| v0.7 精确短语 + 类目 AND | 0.965 | 0.667 | 2.66 | 0.850 | 第二跳 |
| v0.8 Browsing 先问 material | 0.965 | 0.667 | 2.82 | 0.846 | **回滚** |
| v0.9 剔除已展示商品 | 0.995 | 0.682 | 2.39 | 0.874 | |
| **v1** 失败后再问一次 `other` | **1.000** | 0.695 | 2.35 | **0.882** | 冻结合格线 |
| **v1.1** 长短语加分 + 类目必匹配 | **1.000** | 0.703 | 2.385 | **0.883** | |
| **v1.2** 叶类目/放宽区分度/店铺/BM25 | **1.000** | **0.753** | 2.44 | **0.897** | |
| **v1.3** 字段条目前缀 + Override 画像弱加权 | **1.000** | **0.756** | 2.44 | **0.898** | 当前 |

---

## Baseline — 官方弱 BM25

**实现：** `starter/agent.py` 原版。无状态；每轮只用当前用户句做 SQLite FTS5 BM25；`ask_attribute=null`；不累积历史。

**发现的问题：**
- 不问属性时，模拟器固定回复 *Ask me about one specific attribute*，10 轮耗尽。
- Browsing Hit≈0.025，Boundary **0**，Buying 相对最好也只有 ~0.24。
- 同一会话后几轮检索条件几乎不变。

**分数：** Hit 0.125 / MRR 0.068 / MTTC 9.81 / Score **0.107**。

---

## v0.1 — 累积 query、仍然不问

**问题：** 以为「把历史词 OR 进 BM25」就能涨分。  
**做法：** 累积用户文本；仍不提问。  
**结果：** 与 baseline 几乎一样。Browsing 没有新约束，问不出来就搜不准。  
**结论：** **不采用。** 必须提问。

---

## v0.2 — 槽位 + 按类型提问 + 累积 BM25

**问题：** 模拟器每轮只认一个 `ask_attribute`，且按 `classify_constraint` 吐剩余约束。  
**做法：** 解析 *looking for / key requirement / what matters is*；按 material → color → feature… 提问；用已填槽检索。  
**结果（40 条）：** Hit 0.775 / Score 0.666。  
**结论：** 采用方向。会问是第一件正确的事。

---

## v0.3 — 优先问 `other`

**问题：** 硬约束里 material 很多，但真正能锁死商品的是 feature 长句；按类型问太慢。  
**发现：** `ask_attribute=other` 会匹配**任意**未披露约束，每轮最多 2 条。  
**做法：** 提问顺序改为 other → material → color → …  
**结果（200 条）：** Hit 0.86 / MRR 0.536 / MTTC 3.66 / Score **0.738**。  
**结论：** 采用。

---

## v0.4 — 混合检索与短语重排

**问题：** 只靠 BM25 Top-10，目标常在候选外或排不上去。  
**做法：** 扩大召回（~80）+ 约束子串/类目/标题加权重排；Override 时清空旧槽再写。  
**结果：** `hybrid_typed` Score 0.740；`hybrid_other` 更好，但 Override 清空旧槽会掉点。  
**结论：** 混合检索保留；Override 清空策略待改。

---

## v0.5 — Override 保留类目与已填槽

**问题：** 覆盖前命中不计分；覆盖后若只剩 `leather` 这类泛词，检索崩溃。旧偏好其实也来自同一目标商品。  
**做法：** 识别 *ignore my earlier preference* 后**不清空**已有约束，只追加新意图；覆盖前推荐过的 ASIN 在覆盖时清黑名单（避免误杀目标）。  
**结果：** Hit 0.915 / Score **0.773**。  
**结论：** 采用。后续单独试「覆盖后清空」再次失败（见 v1.1 实验）。

---

## v0.6 — 画像只做评分加权

**问题：** 把 `preference_tags`（fit/comfort…）塞进 BM25 会引入噪声。  
**做法：** tags 不进检索；重排用 `average_rating` / 评价数轻微加权。  
**结果：** Hit 0.925 / MRR 0.581 / Score **0.796**。  
**结论：** 采用「评分加权」；tags 进 query **不采用**。

---

## v0.7 — 精确短语召回 + 类目 AND

**问题：** 还剩约 15 条 miss。约束已含商品原文长句，但泛词 OR 查询把目标挤出 Top-80，重排看不见。  
**做法：**
1. 长约束对 5 万商品做内存子串命中，并入候选；
2. 类目 token AND 约束词的 FTS；
3. 再并上原来的宽 OR。

**结果：** Hit **0.965** / MRR 0.667 / MTTC 2.66 / Score **0.850**。miss 降到 7 条，多为纯泛词。  
**结论：** 采用。这是第二大跳。

---

## v0.8 — Browsing 先问 material（回滚）

**问题：** Boundary 第一次提问会被烧掉；先问 `other` 等于浪费「倾倒剩余约束」的槽。  
**做法：** 探索态改为先问 material。  
**结果：** 7 个 miss 一个没少；MTTC 变差（Score 0.846）。根因是 `other` 每轮最多 2 条，且剩余长句常被标成 material，**需要再问一次 other**，而不是改首问。  
**结论：** **回滚。**

---

## v0.9 — 剔除已展示且未命中的商品

**问题：** `public_0016` 等会话在约束不变时，第 2–4 轮推完全相同的 Top-10。评测协议下，会话还能继续 ⇒ 上一轮 Top-10 **一定不是目标**（Override 覆盖前除外）。  
**做法：** 会话内维护 `shown` 集合，后续轮次排除；检测到 Override 时清空黑名单。  
**结果：** Hit **0.995** / MRR 0.682 / MTTC 2.39 / Score **0.874**。Buying / Browsing / Override Hit 均为 1.0。  
**结论：** 采用。

---

## v1 — 问空后再问一次 `other`（冻结）

**问题：** 唯一 miss `public_0187`（Boundary）。首问 `other` 被 Boundary 烧掉；之后 material 只拿到 `leather; 100% Leather`；辨识度高的 *dual gore panels…* 也被标成 material，且 `other` 不会问第二遍。

**做法（通用规则，非 sample 特例）：**
- 已问过一次 `other`；
- 最近一次 typed 属性得到「没有更多偏好」；
- 还没有长约束；
- 则再问一次 `other`。

**结果：** Hit **1.000**（200/200）/ MRR 0.695 / MTTC 2.35 / Score **0.882**。`public_0187` 第 5 轮 rank 1 命中。

**快照：** `snapshots/v1/`  
**结论：** 冻结为 v1。

---

## v1 → v1.1 实验（只保留涨分项）

规则：Hit 不得下降，TechnicalScore 必须严格更高才采用。

| 实验 | 做法 | Score | 采用 |
|------|------|-------|------|
| distinctive_exact_bonus | 长约束精确命中大加分；泛词小加分 | **0.88287** | **是** |
| punct_normalize | 去标点再匹配 | 0.878 | 否，噪声 |
| distinctive_query_focus | 有长句就不用泛词做 BM25 | 持平 | 否 |
| title_distinctive_boost | 长句在 title 再加分 | 持平 | 否 |
| category_must_match | 粗类目 token 不全中则扣分 | **0.88312** | **是** |
| cover_sort | 先比命中了几条长约束 | 持平 | 否 |
| override_clear_old | Override 清空旧槽 | 0.866，Hit 0.99 | 否 |

未上 cross-encoder / 外置向量库：额外依赖、终评可能断网，公开集已 Hit 1.0。

---

## v1.1 — 长短语加分 + 类目必匹配

**相对 v1 新增：**
1. `distinctive_exact_bonus`：泛词不再主导重排。
2. `category_must_match`：粗类目不全中扣分。

**分数：** Hit **1.0** / MRR **0.703** / MTTC **2.385** / Score **0.883**

**快照：** `snapshots/v1.1/`

---

## v1.2 — 排序消融（官方 public_set 200）

规则：Hit 不得下降，TechnicalScore 必须严格更高才采用。基准为 v1.1 final。  
完整机器可读日志：`runs/v3_rank_attempts.json`；复现脚本：`run_v3_rank_experiments.py`。

| 实验 | 做法 | Score | ΔScore | 采用 |
|------|------|-------|--------|------|
| soft_cover_bonus | 区分度约束命中数 ×5 加分 | 0.883121 | 0 | 否 |
| generic_match_dampen | 泛词精确命中 1.2→0.4 | 0.873574 | -0.0095 | 否 |
| profile_when_generic_only | 有长约束时关掉评分加权 | 0.882371 | -0.0008 | 否 |
| **leaf_category_boost** | 叶类目 token 命中加分 | **0.887827** | **+0.0047** | **是** |
| title_category_boost | 类目词出现在 title 加分 | 0.879514 | -0.0083 | 否 |
| features_field_boost | features 字段命中额外加分 | 0.885675 | -0.0022 | 否 |
| semi_distinctive_bonus | 中等长度短语中等加分 | 0.887827 | 0 | 否 |
| **relaxed_distinctive** | 放宽「有区分度」阈值（检索+重排） | **0.892761** | **+0.0049** | **是** |
| distinctive_partial_boost | 长约束部分词命中 0.35→0.8 | 0.892761 | 0 | 否 |
| full_cover_bonus | 全部长约束命中大加分 | 0.892761 | 0 | 否 |
| **store_match_boost** | store/品牌字段词命中小加分 | **0.894332** | **+0.0016** | **是** |
| popularity_dampen | 有长约束时惩罚超高评论数商品 | 0.889171 | -0.0052 | 否 |
| stronger_category_penalty | 类目缺失惩罚 8→15 | 0.894332 | 0 | 否 |
| bm25_lighter | BM25 名次惩罚系数 0.02→0.01 | 0.893811 | -0.0005 | 否 |
| **bm25_heavier** | BM25 名次惩罚系数 0.02→0.04 | **0.897106** | **+0.0028** | **是** |
| distinctive_exact_base_28 | 长约束精确命中基数 20→28 | 0.897106 | 0 | 否 |
| wide_phrase_retrieve | 长约束 FTS 召回 30→60 | 0.897106 | 0 | 否 |
| retrieve_k_150 | 候选池 80→150 | 0.897106 | 0 | 否 |
| soft_cover_plus_leaf | soft_cover 叠在冠军上 | 0.897106 | 0 | 否 |

**采用组合：** `leaf_category_boost` + `relaxed_distinctive` + `store_match_boost` + `bm25_coef=0.04`

**分数：** Hit **1.0** / MRR **0.753** / MTTC **2.44** / Score **0.897**

**默认策略：** `starter/config.py` 中 `VERSION = "v1.2"`，`PRESETS["final"]`。

---

## v1.3 — 字段来源证据与 Override 安全画像

在 v1.2 官方全量基线（Score 0.897106）上继续做提问、RRF、IDF、BM25
系数、字段来源和 profile 消融。采用规则不变：Hit@10 必须保持 1.0，
TechnicalScore 必须严格提升，并在 customer probe 上复核方向。

**采用项：**

1. `entry_prefix_weight=1.1`：当已披露约束匹配原始 `features/details`
   条目的前缀时给予很弱的来源一致性加分；官方 Score 0.897143。
2. `profile_tag_weight=0.03` + `profile_tags_override_only=True`：只在
   Intent Override 已发生后，将匿名偏好标签作为极弱 tie-break，避免影响
   Buying/Browsing 的明确约束排序。
3. 两者组合后，官方 MRR 从 0.753020 升至 0.755526，Score 从
   0.897106 升至 **0.897858**；Hit@10=1.0、MTTC=2.44 不变。
4. customer probe 同方向：MRR 0.748582→0.751263，Score
   0.895484→**0.896288**，Hit@10=1.0。

**未采用：** 全局/条件化 RRF、IDF coverage、BM25 系数网格、连续第二次
`other`、Override 重置提问、全局 profile 加权，以及过强的字段前缀权重。
完整记录见 `docs/OPTIMIZATION_REPORT_V1_3.md` 与 `runs/v4_*attempts.json`。

**默认策略：** `starter/config.py` 中 `VERSION = "v1.3"`，
`PRESETS["final"]`。

---

## 复现

```text
# 解压官方 catalog 到 data/catalog.jsonl 后
python -m evaluator.local_evaluator
python evaluate_with_transcripts.py   # 对话覆盖写入 runs/latest
python run_v3_rank_experiments.py     # 重跑 v1.2 排序消融
python run_v4_experiments.py          # v1.3 第一轮检索/提问消融
python run_v4_entry_experiments.py    # 字段条目前缀权重
python run_v4_profile_experiments.py  # profile 弱加权
python run_v4_conditional_experiments.py # 条件化与最终组合
```
