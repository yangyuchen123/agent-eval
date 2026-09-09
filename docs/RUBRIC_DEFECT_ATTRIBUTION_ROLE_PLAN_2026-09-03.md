# Rubric Defect Attribution Role

日期：2026-09-03  
状态：MVP 已实现；只做诊断和人工复核排序，不做自动修复。

## 1. 目的

将 Gold 与 generated rubric 的统计、分类和稳定性结果，转化为可审计的 defect candidate：

```text
Rubric Set / Criterion / Execution Result
→ Defect Attribution
→ Human Review
```

本角色不自动宣布 rubric 错误，不修改 Gold，不修改 task、trajectory 或 B Judge。

## 2. 三层缺陷模型

### Set-level

- `coverage`：generated capability set 相对 Gold 存在缺口；仅是 coverage proxy。
- `overreach`：generated capability 不在 Gold 中；Gold 未出现不是错误证明，必须复核 task support。
- `granularity`：compound 比例或 capability 重复明显偏离 Gold。

### Criterion-level

- `coverage`：单条 criterion 可能没有覆盖被要求的 concern；第一版由 set-level/人工 alignment 辅助，不自动断言。
- `overreach`：criterion 的 grounding/capability 缺少当前 task 支持的迹象；只产生候选。
- `granularity`：compound 或子要求过多，建议检查拆分、合并及 parent-child duplication。
- `boundary`：negative/absence 语义缺失，或模糊词没有 boundary/anchor。
- `evidence`：criterion 要求的证据源可能无法支持判断；需要独立证据审计，不从 Judge disagreement 直接推断。

### Execution-level

- `measurement`：重复调用出现 binary flip，或调用有 `incomplete_evidence`/`judge_error`；这首先是执行/测量信号，不是 rubric defect。
- `evidence`：调用级证据状态异常；必须与 criterion-level defect 分开。

本阶段不在运行前推断 `discrimination`。区分力依赖多个实际运行输出，不能从 task/rubric 分类直接决定。

## 3. 每条 finding 的字段

```json
{
  "level": "set|criterion|execution",
  "condition": "A|C|D",
  "defect_type": "coverage|overreach|granularity|boundary|evidence|measurement",
  "severity": "low|medium|high",
  "criterion_id": "...",
  "evidence": [],
  "repairability": "local|set_level|evaluation_input|review",
  "recommended_repair": "...",
  "confidence": "high|medium|low",
  "status": "candidate"
}
```

`recommended_repair` 只表示下一步人工处理动作：

```text
coverage → review/add/rewrite
overreach → review task support before drop
granularity → split/merge/remove parent-child duplication
boundary → clarify boundary/anchor/absence semantics
evidence → inspect evidence source or evaluation input
measurement → separate call-level failure before rubric repair
```

## 4. 统计输入边界

允许使用：

- Gold/A/C/D rubric classification；
- generated rubric text and subrequirements；
- distribution audit；
- 已有 stability/status output，仅用于 execution-level finding。

禁止使用 defect attribution 反向修改：

- Gold label；
- task/trajectory；
- B Judge implementation；
- 已有生成 rubric；
- 生产 protocol。

结果必须解释为候选缺陷，而不是自动标签。

## 5. 当前 GDPval pilot 产物

```text
src/agenteval/rubric_defects.py
tools/analyze_rubric_defects.py
run/gdpval-capability-pilot-20260902/rubric_defect_attribution/
├── rubric_defect_attribution.json
├── rubric_defect_attribution.jsonl
└── RUBRIC_DEFECT_ATTRIBUTION_REPORT.md
```

该分析使用当前 56 Gold、17 A、18 C、18 D 分类结果，并将 `agents-spy-type-annotations` 的已有 5-repeat B stability 仅作为 execution-level 补充。
