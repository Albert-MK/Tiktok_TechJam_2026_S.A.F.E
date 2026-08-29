# 实验总览与结果索引

本文档汇总本项目在官方 200 条 public set 上尝试过的所有主要优化方向及结论。  
当前默认算法：**v1.5**（`starter/config.py` → `PRESETS["final"]`）。

## 评分公式

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

**采用门槛（v1.2 起）：** Hit@10 不得下降；TechnicalScore 必须严格高于上一采用版。

---

## 版本演进（已采用）

| 版本 | 核心改动 | Hit@10 | MRR | MTTC | Score |
|------|----------|--------|-----|------|-------|
| Baseline | 无状态 BM25，不提问 | 0.125 | 0.068 | 9.81 | 0.107 |
| v0.2 | 槽位 + 按类型提问 | 0.775* | 0.528 | 4.98 | 0.666 |
| v0.3 | 先问 `other` | 0.860 | 0.536 | 3.66 | 0.738 |
| v0.5 | Override 保留旧槽 | 0.915 | 0.530 | 3.16 | 0.773 |
| v0.7 | 精确短语 + 类目 AND | 0.965 | 0.667 | 2.66 | 0.850 |
| v0.9 | 剔除已展示商品 | 0.995 | 0.682 | 2.39 | 0.874 |
| v1 | 问空后再问一次 `other` | **1.000** | 0.695 | 2.35 | 0.882 |
| v1.1 | 长短语加分 + 类目必匹配 | 1.000 | 0.703 | 2.385 | 0.883 |
| v1.2 | 叶类目/放宽区分度/店铺/BM25 | 1.000 | 0.753 | 2.44 | 0.897 |
| v1.3 | 字段条目前缀 + Override 画像弱加权 | 1.000 | 0.756 | 2.44 | 0.898 |
| v1.4 | 首轮无强约束暂缓交卷 | 1.000 | 0.812 | 2.61 | 0.911 |
| **v1.5** | 约束未满 2 条再空一轮 + title BM25 6→4 | **1.000** | **0.825** | 2.64 | **0.915** |

\*v0.2 为 40 条子集。

详细迭代故事见 [`VERSION_HISTORY.md`](VERSION_HISTORY.md)。

---

## 实验轮次索引

| 轮次 | 脚本 | 报告 | 基线 | 结论 |
|------|------|------|------|------|
| v1.2 排序消融 | `run_v3_rank_experiments.py` | `VERSION_HISTORY.md` §v1.2 | v1.1 | 采用 leaf/relaxed/store/bm25 |
| v1.3 检索/提问/画像 | `run_v4_*.py` | `OPTIMIZATION_REPORT_V1_3.md` | v1.2 | 采用 entry_prefix + profile 弱加权 |
| v1.4 三方向 | `run_v5_direction_experiments.py` | `OPTIMIZATION_REPORT_V1_4.md` | v1.3 | 采用 delay_generic_first |
| v1.5 延迟 + BM25 | `run_v6_delay_bm25_experiments.py` | `OPTIMIZATION_REPORT_V1_5.md` | v1.4 | 采用 delay_until_n_constraints=2 + title↓ |
| v7 自适应收窄 | `run_v7_adaptive_ask_experiments.py` | `OPTIMIZATION_REPORT_ADAPTIVE_ASK.md` | v1.5 | **不采用** |
| v8 画像×分支 | `run_v8_profile_branch_experiments.py` | `OPTIMIZATION_REPORT_PROFILE_BRANCH.md` | v1.5 | **不采用** |

本地 JSON 日志在 `runs/`（gitignore），完整数值表已写入各报告 Markdown。

---

## 按主题：尝试过的方法与结果

### A. 提问策略

| 方法 | 开关 / 模式 | Hit@10 | Score | vs 当时基线 | 结论 |
|------|-------------|--------|-------|-------------|------|
| 固定 typed 顺序 | `ask_mode=typed` | — | — | 低于 other_first | 不采用 |
| **先问 other** | `ask_mode=other_first` | 1.000 | 0.882+ | + | **采用（v0.3 起）** |
| 问空后再 other | v1 规则 | 1.000 | 0.882 | + | **采用** |
| feature 优先 | `ask_mode=feature_first` | 0.995 | 0.887 | -0.010 | 不采用 |
| 跳过已覆盖属性 | `skip_covered_attrs` | 1.000 | 0.890 | -0.008 | 不采用 |
| 动态 typed（熵） | `dynamic_typed_ask` | 0.995 | 0.887–0.903 | 负 | 不采用 |
| 自适应收窄 | `ask_mode=adaptive_narrow` | 0.990–1.000 | 0.881–0.904 | -0.010~ | 不采用 |
| 画像×分支 | `ask_mode=profile_branch` | 0.990–0.995 | 0.903–0.909 | -0.006~ | 不采用 |
| Override 后重置提问 | `override_reset_asked` | 1.000 | 0.896 | -0.001 | 不采用 |
| 连续第二次 other | `eager_second_other` | 0.995 | 0.892 | miss | 不采用 |

### B. 延迟交卷（用轮次换 MRR）

| 方法 | 开关 | Hit@10 | Score | 结论 |
|------|------|--------|-------|------|
| **首轮无强约束暂缓** | `delay_generic_first` | 1.000 | 0.911 | **采用（v1.4）** |
| **约束 <2 再空一轮** | `delay_until_n_constraints=2`, `delay_max_empty=2` | 1.000 | 0.915 | **采用（v1.5）** |
| 等到 distinctive | `delay_until_distinctive`, max 2 | 1.000 | 0.909 | 不采用 |
| 等到 distinctive, max 3 | 同上 max 3 | 0.995 | 0.916 | miss，不采用 |
| 重排分差不确定 | `delay_uncertain` | 1.000 | 0.907–0.909 | 不采用 |
| 约束 <3 | `delay_until_n_constraints=3` | 1.000 | 0.906 | 不采用 |

### C. 检索与重排

| 方法 | 开关 | 结论 |
|------|------|------|
| 精确短语子串召回 | v0.7 | **采用** |
| 类目 AND 查询 | v0.7 | **采用** |
| 剔除已展示 ASIN | `exclude_shown` | **采用（v0.9）** |
| 长短语精确命中大加分 | `distinctive_exact_bonus` | **采用（v1.1）** |
| 类目必匹配扣分 | `category_must_match` | **采用（v1.1）** |
| 叶类目加分 | `leaf_category_boost` | **采用（v1.2）** |
| 放宽 distinctive | `relaxed_distinctive` | **采用（v1.2）** |
| 店铺匹配 | `store_match_boost` | **采用（v1.2）** |
| BM25 系数 0.04 | `bm25_coef=0.04` | **采用（v1.2）** |
| title BM25 6→4 | `bm25_field_weights[0]=4` | **采用（v1.5）** |
| 字段条目前缀 | `entry_prefix_weight=1.1` | **采用（v1.3）** |
| punct 归一化 | `punct_normalize` | 伤分，不采用 |
| generic 降权 | `generic_match_dampen` | 不采用 |
| 扩大 retrieve_k | 150 | 无增益 |
| RRF 多路融合 | v1.3 实验 | 不采用 |
| IDF coverage | v1.3 实验 | 不采用 |
| Jaccard 相似度重排 | v1.4 实验 | 不采用 |
| 锚点条目重叠 | v1.4 实验 | 无变化 |

### D. 用户画像

| 方法 | 开关 | 结论 |
|------|------|------|
| tags 进 BM25 检索 | 早期 v0.6 前 | **不采用**（噪声） |
| 评分/评论数加权 | `profile_boost` | **采用** |
| 画像 tag 弱加权 | `profile_tag_weight=0.03` | **采用（v1.3，Override 后）** |
| 画像引导提问 | `ask_mode=profile_branch` | **不采用（v8）** |
| 全局 profile 加权网格 | `run_v4_profile_experiments.py` | 弱于条件化方案 |

---

## 未采用方向的设计教训

1. **熵高 ≠ 模拟器会给有用答案**：brand/color 在候选池分散，但 Boundary 下 typed 常空转（v7/v8）。
2. **画像 tag ≠ 本会话 intent**：历史偏好不能可靠映射到本轮该问什么（v8）。
3. **候选池每轮重洗牌**：不是单调缩小的 facet 导航；只改提问顺序无法真正「收窄搜索空间」。
4. **Override / Boundary 对提问顺序敏感**：固定 `other → material → other` 比动态选择更稳。
5. **延迟超过 2 轮空列表易 miss**：评测锁 first Top-10 appearance。

---

## 复现命令

```bash
python -m evaluator.local_evaluator                    # 当前默认 v1.5
python run_v3_rank_experiments.py                      # v1.2 消融
python run_v4_experiments.py                           # v1.3
python run_v4_entry_experiments.py
python run_v4_profile_experiments.py
python run_v4_conditional_experiments.py
python run_v5_direction_experiments.py                   # v1.4
python run_v6_delay_bm25_experiments.py                  # v1.5
python run_v7_adaptive_ask_experiments.py                # v7
python run_v8_profile_branch_experiments.py              # v8
```

实验性提问模式（不改默认）：`AGENT_ASK_MODE=profile_branch python -m evaluator.local_evaluator`
