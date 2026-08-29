# 画像 × 分支精细化提问实验报告（v8）

日期：2026-08-29  
基线：v1.5（Score 0.914778，Hit@10=1.0）  
机器可读（本地）：`runs/v8_profile_branch_attempts.json`  
复现脚本：`run_v8_profile_branch_experiments.py`

## 1. 设计目标

在 v7 纯熵自适应失败的基础上，尝试更精细的提问策略：

1. 用 `user_profile.preference_tags` 推断用户更可能回答哪些维度；
2. 在当前候选商品分支上估算属性 split 分数；
3. 对 brand/budget/category 等低产出维度降权；
4. typed 空答后强制回到 `other`；
5. 用 **distinctive 约束**（非泛词）估算有效搜索分支。

实验开关：`ask_mode=profile_branch`（**未写入默认 final 预设**）。

## 2. 算法（`ask_mode=profile_branch`）

1. **第 1 问仍用 `other`**。
2. 构建 active 分支：`_candidates` 经 distinctive 约束硬过滤（泛词如 `polyester`/`imported` 不参与）。
3. 对每个未问 typed 属性打分：

   ```text
   score = branch_split(attr, active) × yield_prior(attr) × (1 + profile_prior(attr))
   ```

   - `branch_split`：归一化熵 × 覆盖率 × 淘汰潜力（同 v7 `_narrow_ask_score`）；
   - `profile_prior`：`preference_tags` 映射到 ask_attribute 的对齐度（见 `TAG_TO_ASK_PRIOR`）；
   - `yield_prior`：brand/budget/category 默认 ×0.25。

4. 选 score 最高且 >0 的属性；若无合适问题，回退 v1.5 固定顺序。
5. typed 空答且 `other` 还可再问 → **强制 `other`**（比 v1.5 更宽的空答刹车）。

## 3. 官方 200 条结果

| 方法 | Hit@10 | MRR | MTTC | Score | Δ vs v1.5 | 结论 |
|---|---:|---:|---:|---:|---:|---|
| **v1.5 复测** | **1.000** | **0.825** | 2.640 | **0.915** | — | 基线 |
| profile_branch | 0.990 | 0.808 | 2.660 | 0.904 | -0.011 | 拒绝 |
| profile_branch + skip_covered | 0.990 | 0.808 | 2.660 | 0.904 | -0.011 | 拒绝 |
| profile_branch + stop≤15 | 0.990 | 0.808 | 2.660 | 0.904 | -0.011 | 拒绝 |
| profile_branch + 全约束过滤 | 0.995 | 0.814 | 2.655 | 0.909 | -0.006 | 拒绝 |
| profile_branch + 无 brand 降权 | 0.990 | 0.803 | 2.675 | 0.903 | -0.012 | 拒绝 |

**结论：不采用。** 所有变体均低于 v1.5，且出现 Hit 下降。

## 4. 退化会话（v1.5 命中，profile_branch miss）

| 会话 | 场景 | 分析 |
|------|------|------|
| `public_0064` | Intent Override | 画像引导优先问 feature/style 等 typed，Override 窗口内连续空转，未及时回到 `other` |
| `public_0187` | Boundary | 画像对齐的属性与 Boundary「第一个 typed 必空」协议冲突，打乱 v1.5 的 `material → other` 节奏 |

Browsing 子集 MRR 从 0.791 降至 0.759（Hit 仍 1.0，但 rank 普遍变差）。

## 5. 失败原因

1. **画像 tag ≠ 本会话 hidden intent**：`preference_tags=["fit","durability"]` 只表示历史偏好，不代表本轮约束类型。
2. **分支 split 区分度不足**：distinctive 过滤后 active 仍约 30–40 个，split 分数难以稳定选出「模拟器会给答案」的维度。
3. **v1.5 固定顺序已被协议调优**：`material` 作为第一个 typed + 空答后回 `other`，在 Boundary/Buying 上比动态选择更稳。
4. **brand 降权有帮助但不够**：去掉降权反而更差（Score 0.903）。

## 6. 与 v7 的关系

v7（`adaptive_narrow`）失败主因是「熵高 ≠ 用户可披露」；v8 加了画像先验和低产出降权，但仍无法改变 typed 选择与模拟器协议不对齐的问题。详见 `docs/OPTIMIZATION_REPORT_ADAPTIVE_ASK.md`。

## 7. 复现

```bash
python run_v8_profile_branch_experiments.py
python runs/trace_profile_branch.py   # 对比 miss 会话
```
