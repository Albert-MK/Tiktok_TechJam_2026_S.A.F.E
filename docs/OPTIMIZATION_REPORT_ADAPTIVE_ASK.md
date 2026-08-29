# 自适应收窄提问实验报告

日期：2026-08-29  
基线：v1.5（Score 0.914778，Hit@10=1.0）  
机器可读：`runs/v7_adaptive_ask_attempts.json`

## 1. 设计目标

让每一轮提问都基于**当前已知用户约束 + 当前候选商品分支**，选能最大程度**缩小有效搜索范围**的属性，而不是固定 `material → color → …` 顺序。

## 2. 算法（`ask_mode=adaptive_narrow`）

1. **第 1 问仍用 `other`**（历史实验证明收益最大）。
2. 用上一轮 `_retrieve()` 留下的 `_candidates`（重排后约 40 个）作为分支。
3. **硬过滤**：只保留已披露约束全部子串命中的商品 → `active` 分支。
4. 对每个未问 typed 属性，从商品 metadata 抽桶值（material/color/feature 条目/brand/…）。
5. 打分 = 归一化熵 × 覆盖率 × (1 + 淘汰潜力)；**选分最高**的属性。
6. 若该属性在 active 上只有 0/1 个桶 → 跳过（问了也缩不窄）。
7. 可选：`narrow_stop_candidates=15/20` 时分支够小就停止提问。

保留 v1.4/v1.5 的延迟交卷规则（除非 `*_no_delay` 变体）。

## 3. 官方 200 条结果

| 方法 | Hit@10 | MRR | MTTC | Score | Δ vs v1.5 |
|---|---:|---:|---:|---:|---:|
| **v1.5 复测** | **1.000** | **0.825** | 2.640 | **0.915** | — |
| adaptive_narrow | 0.995 | 0.804 | 2.715 | 0.904 | -0.010 |
| adaptive + stop≤15 | 1.000 | 0.790 | 2.705 | 0.903 | -0.012 |
| adaptive + stop≤20 | 1.000 | 0.792 | 2.710 | 0.903 | -0.011 |
| adaptive 无硬过滤 | 0.995 | 0.804 | 2.715 | 0.904 | -0.010 |
| v1.5 + dynamic_typed | 0.995 | 0.796 | 2.680 | 0.903 | -0.012 |
| adaptive 无 delay | 0.990 | 0.720 | 2.500 | 0.881 | -0.034 |

**结论：不采用。** 所有自适应变体均低于 v1.5。

## 4. 失败原因分析

### 4.1 熵高 ≠ 模拟器会给有用答案

`public_0131`（Boundary）：

- v1.5：T2 问 `material` → 空回答但触发 delay → T3 问 `other` 拿到长句 → **rank 1**
- adaptive：T2 在候选上 **brand 熵最高** → 问 brand → 用户「没偏好」→ 白烧一轮 → T3 才 other → **rank 9**

候选池里 brand/color 分散，但 Boundary 协议下 typed 问往往空转；**分散的是竞品差异，不是用户可披露的有效维度**。

### 4.2 属性桶与模拟器约束不对齐

- material 桶 = 正则抓第一个材质词；模拟器可能给 `100% Polyester; Imported`（classify 为 material + feature）。
- feature 桶 = 第一条 features 条目前 24 字符；大量商品条目不同，熵很高，但用户回答常仍是泛词。
- 问 `feature` 时模拟器返回的句子和桶定义不一致 → **估计的“收窄”在真实对话里不成立**。

### 4.3 空回答时没有刹车

`public_0064`（Intent Override，**唯一 miss**）：

- T2 adaptive 问 **feature**（非 v1.5 的 material）；目标当时 rank 1 但 Override 未生效**不计分**
- T3–T10 连续问 material/color/use_case/…，用户全部「无偏好」，**10 轮问尽仍未在 Override 后命中**

固定顺序至少 T3 会再问 `other` 吐出信息；自适应在熵排序下**不会在空 streak 后回到 other**，Override 窗口被 typed 空转吃光。

### 4.4 候选池 ≠ 单调缩小的搜索空间

`_candidates` 是**本轮 BM25+重排**的结果，每加一条约束会整体重洗牌，不是在上轮集合上做子集过滤。  
硬过滤 `active` 对泛词约束几乎不过滤（polyester/imported 人人都命中），**active 大小几乎不变**，熵估计基于「本轮谁排前面」而非「语义上还剩多少可能目标」。

### 4.5 与 delay / shown 的交互

延迟交卷 + adaptive 提问顺序变化 → 目标进入 Top-10 的轮次和 `shown` 排除轨迹都变；8 条会话 Hit 不变但 rank 变差（如 `public_0131` rank 1→9）。

## 5. 若要改进方向（未实现）

1. 空回答 ≥1 后**强制回 other**，不要继续熵排序 typed。
2. 熵只在与模拟器 `classify_constraint` 对齐、且 Boundary 场景**跳过** brand/budget 等空转属性。
3. 用** distinctive 约束**过滤 active，泛词不参与过滤计数。
4. Intent Override 窗口内优先 `other` / 少问 typed。
5. 真正单调收窄需要**检索层**硬过滤（must-match 约束），不能只改提问顺序。

## 6. 复现

```bash
python run_v7_adaptive_ask_experiments.py
```
