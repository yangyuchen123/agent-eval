# AgentEval interfaces — evaluation as a service

This document defines every interface of AgentEval: what it **consumes**
(evaluation sets, agent artifacts), what it **exposes** (CLI), and what it
**emits** (history, evidence, reports, manifests). External agent runtimes
only need §1-2; consumers of results need §3-4.

```
        INPUTS                          AgentEval                        OUTPUTS
┌────────────────────┐    ┌──────────────────────────────────┐   ┌────────────────────┐
│ 评测集 (evaluation  │    │ evaluate_*.py (case packages)     │   │ history.jsonl      │
│   sets)            │───►│   → run_eval(plan → skills)       │──►│ evidence/*.json    │
│  agent 产物 (JSON)  │    │ agenteval analyze / migrate / verify│  │ summary.json       │
└────────────────────┘    └──────────────────────────────────┘   │ run_manifest.json  │
                                                                │ LEADERBOARD.md     │
                                                                └────────────────────┘
```

---

## 1. 输入接口 — 评测集(evaluation sets)

### 1.1 GDPVal:`cases.json`

```json
{
  "cases": [
    {
      "task_id": "83d10b06-26d1-4636-a32c-23f92c57f30b",
      "sector": "Professional, Scientific, and Technical Services",
      "occupation": "Accountants and Auditors",
      "prompt": "You are an auditor and as part of an audit engagement...",
      "deliverable_files": ["deliverable_files/2837f.../Sample v2.xlsx"],
      "rubric_items": [
        {
          "score": 2,
          "criterion": "The workbook contains a worksheet named exactly 'Sample Size Calculation'",
          "required": null,
          "rubric_item_id": "c4313210-...",
          "author_type": null,
          "tags": null,
          "read_only": null,
          "form_content": null
        }
      ]
    }
  ]
}
```

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `task_id` | str | 唯一 ID,也是产物 JSON 的 key |
| `sector` / `occupation` | str | 元数据(capability_report 用) |
| `prompt` | str | 给 agent 的专业任务描述 |
| `deliverable_files` | list[str] | 要求的交付物文件路径 |
| `rubric_items[]` | list | 人类 rubric 条目:每个 `{score, criterion, ...}` |
| `rubric_items[].score` | number | **权重**:正=加分项,负=惩罚项,0=不计分 |
| `rubric_items[].criterion` | str | 判定标准(逐条成为 judge 的问题) |

加载:`cases.py::load_tasks()` → `task_to_case()` → `Case`。

### 1.2 SWE-bench:`instances.json`

```json
{
  "instances": [
    {
      "instance_id": "sympy__sympy-23950",
      "repo": "sympy/sympy",
      "base_commit": "88664e6e0b78...",
      "patch": "diff --git a/sympy/sets/contains.py ...",
      "test_patch": "diff --git a/sympy/sets/tests/test_contains.py ...",
      "problem_statement": "...",
      "hints_text": null,
      "FAIL_TO_PASS": ["sympy/sets/tests/test_contains.py::test_as_set"],
      "PASS_TO_PASS": ["sympy/sets/tests/test_contains.py::test_contains_basic"],
      "environment_setup_commit": "...",
      "notes": "optional: environment quirks (e.g. tests removed)"
    }
  ]
}
```

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `instance_id` | str | 唯一 ID,产物 JSON 的 key |
| `repo` / `base_commit` | str | 容器镜像构建用(git clone + checkout) |
| `patch` | str | gold 参考 patch(`--predictions gold` 时用) |
| `test_patch` | str | 评测测试的 diff(镜像构建时应用) |
| `FAIL_TO_PASS` | list[str] | **完整 pytest node id**(必须 resolve 过,`resolve_test_ids.py`) |
| `PASS_TO_PASS` | list[str] | 完整 node id;环境性失败的测试应剔除并记 `notes` |
| `notes` | str? | 可选:数据修正记录 |

**重要**:`FAIL_TO_PASS`/`PASS_TO_PASS` 必须是**完整 node id**
(`file.py::Class::test[param]`)。HF 的短测试名要用
`resolve_test_ids.py` 解析(仓库 grep `def <name>`,不能假设同文件)。
打分时容器会按文件 `--collect-only`,**收集不到的 ID 自动剔除**
(记录在 evidence 的 `ids_dropped`),F2P 全部收集不到 = `no_f2p_collected`
(不算通过,防空转)。

### 1.3 agent 产物(输入契约)

见 [`AGENT_CONTRACT.md`](AGENT_CONTRACT.md) —— 两种 JSON 格式:
SWE-bench `{instance_id: {model_patch}}`、GDPVal `{task_id: text}`。

---

## 2. 执行接口(CLI)

### 2.1 GDPVal 评测

```bash
python examples/gdpval/evaluate_gdpval.py \
    --outputs outputs_pi.json \      # 必填: {task_id: agent_text}
    --run-root run/pi \              # 输出目录(默认 run/gdpval)
    --no-judge \                     # 跳过 LLM judge(只跑规则 skill)
    --agent-name pi --agent-version v1   # 写入 run_manifest
```

产出:`run_root/history.jsonl`、`run_root/evidence/*.json`、
`run_root/summary.json`、`run_root/run_manifest.json`、`LEADERBOARD.md`。
GDPVal 总分 = Σ满足项的权重和(可 >1),summary 显示 `score/max_possible`。

### 2.2 SWE-bench 评测

```bash
python examples/swebench/evaluate_predictions.py \
    --predictions predictions.json \   # 或 'gold'(用 bundled 参考 patch)
    --run-root run/pi \
    --workers 1 \
    --agent-name pi --agent-version v1
```

流程:确保容器镜像 → 应用 patch → **两阶段测试**:① 按文件
`--collect-only` 过滤过期 ID → ② 只跑能收集的 → 解析 F2P/P2P →
resolved = F2P 全过 + P2P 无回归。每个 case 还会跑 `patch_quality`
(LLM rubric 诊断,不影响 resolved)。

---

## 3. 输出接口(数据 schema)

### 3.1 `history.jsonl`(EvalRecord,append-only)

每行一条记录:

```json
{
  "schema_version": "agenteval.record.v1",
  "run_id": "run-20260822T135252-03801a",
  "model_id": "outputs_pi",
  "case_id": "f84ea6ac-8f9f-...",
  "skill_id": "gdpval_judge_f84ea6ac",
  "score": 57.0,
  "subscores": {"I00": 1, "I04": 0, ...},
  "status": "ok",
  "rubric_id": "gdpval_f84ea6ac",
  "rubric_version": "1.0.0",
  "evaluator_version": "1",
  "judge": "deepseek-v4-flash",
  "judge_temperature": 0.0,
  "timestamp": "2026-08-22T..."
}
```

| 字段 | 含义 |
| --- | --- |
| `score` | skill 聚合分(SWE 是 [0,1];GDPVal 是绝对权重和,可 >1) |
| `subscores` | 逐问题分数(诊断/迁移的原料) |
| `rubric_id` + `rubric_version` | 数据版本(evaluator_version 是 prompt 设计版本,两者分离) |

### 3.2 `evidence/<case_id>.json`(逐 case 完整证据树)

```json
{
  "schema_version": "agenteval.evidence.v1",
  "case_id": "...",
  "case": {"schema_version": "...", "case_id": "...", "task": "...",
           "expected": {...}, "metadata": {...}},
  "output": "agent 的原始产物",
  "plan": {"case_id": "...", "selected_skills": [...], "skipped_skills": [...]},
  "skill_results": {
    "gdpval_judge_...": {
      "schema_version": "agenteval.skill_result.v1",
      "skill_id": "...", "status": "ok", "score": 57.0,
      "subscores": {...}, "reasons": {...},
      "evidence": {"per_question": {...}, "fabricated_evidence_rejected": [...]},
      "diagnostics": {"analyze_stage": {...}, "judge": {...}}
    }
  }
}
```

审计用途:plan(为什么选这些 skill)、subscores+reasons(每题判定依据)、
evidence(引用)、diagnostics(analyze 阶段 + judge 模型/版本)。

### 3.3 `summary.json`

```json
{
  "schema_version": "agenteval.report.v1",
  "model_id": "outputs_pi",
  "aggregator": "weighted_case_score",
  "summary": {"n_cases": 3, "n_scored": 3, "mean_case_score": ..., "skills": {...}},
  "cases": [{"case_id": "...", "score": ..., "skills": {...}}]
}
```

### 3.4 `run_manifest.json`(可复现性)

```json
{
  "schema_version": "agenteval.run_manifest.v1",
  "run_id": "...",
  "agent": {"name": "pi", "version": "v1"},
  "environment": {"date_utc": "...", "machine": "...", "platform": "...", "python": "..."},
  "benchmarks": ["gdpval"],
  "evaluator_snapshot": {
    "rubric_versions": {"gdpval_f84ea6ac": ["1.0.0"]},
    "judge_models": ["deepseek-v4-flash"],
    "evaluator_versions": ["1"]
  }
}
```

回答工业问题:**这份报告在什么条件下产生?**

---

## 4. 分析接口(agenteval CLI)

```bash
# 4.1 rubric 诊断:每题区分度/天花板/噪声 → keep/ceiling/floor/noisy
agenteval analyze \
    --history run/pi/history.jsonl --history run/gold/history.jsonl \
    --rubric patch_quality \
    --judge-skill patch_quality --rule-skill test_resolution   # judge↔rule 一致
    [--json report.json]

# 4.2 版本迁移:v1 结论能否被 v2 继承(排序保持 ρ/τ + 漂移分类)
agenteval migrate --history ... --skill patch_quality \
    --old-version v1 --new-version v2 [--json report.json]

# 4.3 验证 run 完整性
agenteval verify --cases instances.json --run-root run/pi
```

分析输出全部是 JSON(可管道化)+ markdown 渲染。

---

## 5. 框架编程接口(给新 benchmark 包作者)

一个案例包 = 4 件事(全部解耦,框架零领域知识):

```python
# 1. 数据:cases.json / instances.json(见 §1)
# 2. 加载:load_cases() -> list[Case]
# 3. Skills:build_registry() -> SkillRegistry
#    - RuleSkill(确定性:容器测试/规则检查)
#    - FineGrainedRubric 子类(LLM judge:声明 Rubric 数据即可)
#      注意证据策略:patch 类领域 require_verbatim_evidence=True(默认);
#      内容类领域(GDPVal)设 False(judge 引用是语义摘要)
# 4. 路由:build_router(registry) -> Router
#    - 静态 skill 组合 → RuleRouter(case 包内写死)
#    - 异构领域 → LLMRouter(镜像 HarnessEval-W 原版)
# 5. 入口:evaluate_*.py 吃产物 JSON → run_eval → 报告
```

`Case` 构造契约:

```python
Case(case_id=..., task=...,        # prompt(喂给 judge/agent)
     expected={...},               # 裁判标准(rubric items / 测试 ID)
     context={"task": ...},        # 领域数据(技能 evaluate 时读)
     metadata={"occupation": ...}) # 元数据(报告/capability 用)
```

---

## 6. 参考文件

| 文档 | 内容 |
| --- | --- |
| [`AGENT_CONTRACT.md`](AGENT_CONTRACT.md) | agent 产物 JSON 格式(runtime 的输入边界) |
| [`DESIGN_MEMORY.md`](DESIGN_MEMORY.md) | 模块地图、设计意图、踩坑史 |
| [`architecture.md`](architecture.md) | 四层架构、继承关系 |


## 7. Runtime adapter interface

AgentEval 通过 `EvalSample` 统一 Harbor、AgentOctagon 和 JSON 导出产物。
AgentOctagon 的数据库/attempt 适配、`octagon-score`、`octagon-eval`、
纯 LLM judge 和混合评分见 [`RUNTIME_ADAPTERS.md`](RUNTIME_ADAPTERS.md)。

最小 runtime adapter 接口：

```python
class RuntimeAdapter(Protocol):
    name: str

    def iter_samples(self) -> Sequence[EvalSample]:
        ...
```

评分模式不是 runtime 的属性，而是 AgentEval 的 skill 配置：

```text
RuleSkill  → 确定性评分
LLMSkill   → LLM-as-judge
二者同时选择 → 混合评分
```
