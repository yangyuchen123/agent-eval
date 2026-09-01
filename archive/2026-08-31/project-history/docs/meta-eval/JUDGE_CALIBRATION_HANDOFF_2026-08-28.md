# Judge 黄金数据校准交接（2026-08-28）

## 目标

把“人工黄金数据 → Judge 观测结果 → 校准诊断”固定成一个可复现、不会把旧
Judge/Octagon 分数伪装成 Gold 的交接点。该交接点只做 Judge calibration，不
发布 rubric，也不改变 AgentEval 正式评分。

## 本次使用的数据

- 人工 Gold：`run/meta_eval/failure-handling-blind-v1/gold/`
- Gold manifest：`run/meta_eval/failure-handling-blind-v1/gold-manifest.json`
- Judge 观测：`run/meta_eval/failure-handling-anchor-v2-v5/5-levels/judgments.jsonl`
- 选择条件：`question_id=observed_failure_handling`、`judge_mode=agentic_evidence`、
  `perturbation=none`
- Gold 数量：30 条，覆盖 8 个显式/非显式失败分层，20 条 applicable、10 条
  not-applicable；Gold 分布为 0.0×2、0.5×8、1.0×20。

Gold 由人工依据冻结 runtime evidence 标注；Octagon score/status 只保留为诊断
上下文，不能作为标签来源。

## 生成命令

```bash
cd /home/yang/agent-eval
./.venv/bin/python tools_validate_failure_gold.py \
  --gold-dir run/meta_eval/failure-handling-blind-v1/gold

./.venv/bin/python tools_prepare_judge_calibration.py
```

输出：

```text
run/meta_eval/judge-calibration/failure-handling-v1/
├── manifest.json          # 输入 hash、过滤条件、覆盖率、总体/逐 case 诊断
└── calibration.jsonl      # 每条 Judge observation 与人工 Gold 的可追溯 join
```

## 当前校准结果

本次已有的 Judge 观测是 **5-level 实验**，而 Gold 是按冻结 v3 的 `0 / 0.5 / 1`
语义审阅的。因此下面的数字是“发现 rubric/anchor 不一致的诊断”，不是 5-level
协议的最终准确率：

- 90 条 observation，30 个 Gold case，Gold 覆盖率 30/30；
- score exact rate：`0.5111`；
- status exact rate：`0.7556`；
- score MAE：`0.2079`；
- 最大绝对误差：`1.0`。

高误差 case 已按 case 写入 `manifest.json`。其中典型问题包括：observer-side
capture failure 被当成 Agent failure、明确 ignored failure 被判为高分、成功恢复
被压到低 anchor，以及 partial recovery 在 5-level ladder 下与旧 v3 数值 Gold
不兼容。后续比较必须使用同一 rubric/anchor policy；如果改变 ladder，应提供
`expected_score_by_policy` 的人工 adjudication，而不能直接复用旧数值。

## 对闭环的意义

此处完成的是闭环的第一个可靠闸门：

```text
human Gold + frozen evidence
        ↓
validated calibration bundle
        ↓
Judge error / status / coverage diagnostics
        ↓
低分：检查 rubric、score、题目难度、runtime evidence
高分：检查 rubric 是否过宽、题目是否过简单
        ↓
进入后续 rubric-evolution / benchmark knowledge memory
```

`tools_prepare_judge_calibration.py` 会报告 missing/unmatched observations，不会
静默丢弃；也不会自动把任何诊断结论写回 benchagent 知识库。知识库写回应在
人工确认“是题目问题 / Rubric 问题 / Judge 问题 / infrastructure 问题”后进行，
并携带本 manifest 的输入 hash。

## 下一步协议

1. 用冻结 v3 rubric 对 30 个 case 运行同条件 Judge（或补齐已有 v3 观测），先
   得到可直接与 Gold 比较的基线。
2. 把 `manifest.json` 中高误差和跨 repeat 不稳定 case 放入人工复核队列，明确
   错误归因：Judge retrieval、claim、score anchor、rubric 边界、题目设计或
   runtime/infrastructure。
3. 只有人工确认后的归因才生成一条 iteration record，再同步到 benchagent
   knowledge base；记录必须与初始 Gold 分开，标记为 `iteration_feedback`。
4. 在此基础上才推进“低分/高分 → 题目难度与 rubric 检查 → benchmark 修改”的
   下一段回环。
