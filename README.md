# AgentEval

> **项目定位**:[HarnessEval-W](https://github.com/mirros-lab/HarnessEval-W) 的二开(两天)——
> 继承其 agentified evaluation / evidence-tree 思想,重构为通用评测框架。
> 继承/重构/新增的边界见 [`docs/DESIGN_MEMORY.md`](docs/DESIGN_MEMORY.md) §1.5。

> **接口文档**:[`docs/INTERFACES.md`](docs/INTERFACES.md) —— 评测集/产物/CLI/数据 schema,
> 外部 agent runtime 只读 §1-2。
> **项目职责(2026-08 更新)**:AgentEval 是评测编排壳：消费由 `eval-system` 收集的 agent
> runtime 产物，动态组织 case-specific rubric 和 skills，调用 deterministic scorer 或独立
> Judge，并生成评分报告。它不运行 agent、不收集 runtime、不实现 evidence retrieval 或 judge
> policy。三层系统边界见 [`docs/SYSTEM_BOUNDARIES.md`](docs/SYSTEM_BOUNDARIES.md)；runtime 适配见
> [`docs/RUNTIME_ADAPTERS.md`](docs/RUNTIME_ADAPTERS.md)。
>
> **恢复上下文**:先读 [`docs/DESIGN_MEMORY.md`](docs/DESIGN_MEMORY.md) —— 模块地图、设计意图、关键决策的「为什么」、踩坑史,一站式记忆恢复。


**Agentified evaluation framework for LLM agents**: skill routing, evidence trees, auditable scoring.

Evaluation becomes an *agent system*: for each case a router decides which
evaluation skills apply (with reasons), each skill answers its question
against the agent output, and every step — plan, sub-scores, reasons,
judge prompts, raw model output — is saved as an inspectable **evidence
tree**. This is the "harness" paradigm from the LLM ecosystem applied to
agent evaluation.

> Mechanism lineage: the agentified-evaluation idea (case-grounded skill
> routing → sub-agent reasoning → validated aggregation) is adapted from
> [HarnessEval-W](https://github.com/MirroS-Lab/HarnessEval-W)
> (Apache-2.0), which evaluates video world models. AgentEval keeps the
> mechanism but is **domain-agnostic**: it knows nothing about any agent
> task.

## Why this design

| Problem with naive agent eval | AgentEval's answer |
| --- | --- |
| One fixed rubric misses case-specific aspects | **Router** picks skills per case, with reasons |
| Scores without justification can't be audited | **Evidence tree**: every score links sub-scores + reasons |
| Rule metrics are free but rigid; judges are general but noisy | **Both coexist**: RuleSkills + LLMSkills plug in side by side |
| Re-evaluating after fixing a skill wastes API calls | **Digest caching**: results keyed by (skill impl, case, output) |

## Concepts

```
Case        — one evaluation instance: task + expected + context (domain-supplied)
Skill       — one evaluation question: RuleSkill (deterministic) or LLMSkill (judge model)
Registry    — where a case package registers its skills
Router      — RuleRouter (deterministic) or LLMRouter (agent) → Plan
Plan        — selected/skipped skills for a case, each with a reason
Evidence    — plan + per-skill results for one case (auditable)
Report      — summary, per-skill means, leaderboard (JSON/CSV/MD)
```

## System boundary

```text
eval-system  →  AgentEval  →  Agent Judge
运行/采集       适配/组织/聚合       证据/判断
```

- `eval-system`: 运行 agent，收集各 runtime 的 attempt 和 runtrace。
- `AgentEval`: 读取产物，动态组织 skills/rubrics，调用 scorer/Judge，生成报告。
- `Agent Judge`: 独立的 evidence retrieval、evidence chain 和 LLM/rule judgment 系统。

完整边界见 [`docs/SYSTEM_BOUNDARIES.md`](docs/SYSTEM_BOUNDARIES.md)。
Judge 的独立架构、PydanticAI subagent、EvidenceProvider、claim/evidence chain 和迁移计划见
[`docs/JUDGE_ARCHITECTURE.md`](docs/JUDGE_ARCHITECTURE.md)。

Runtime evidence 的问题、解决方案、验证结果和未解决事项见 [`docs/RUNTIME_EVIDENCE_ISSUES.md`](docs/RUNTIME_EVIDENCE_ISSUES.md)。

当前实现审查、EvidenceCatalog 修改点和真实 trace 验证见 [`docs/RUNTIME_EVIDENCE_IMPLEMENTATION_REVIEW.md`](docs/RUNTIME_EVIDENCE_IMPLEMENTATION_REVIEW.md)。

AgentEval 侧的独立 Judge 接口位于 `src/agenteval/judge.py`：

```text
JudgeRequest → JudgeClient.evaluate() → JudgeResponse → SkillResult
```

Judge 的 evidence catalog、检索工具、证据链和 judge policy 不属于该接口的实现。

## Install

```bash
pip install -e .            # framework only; no runtime dependencies
pip install -e ".[test]"    # + pytest
```

## Quick start (with the bundled demo)

```bash
# 1. generate demo cases + fake agent outputs
python examples/demo/gen_demo.py

# 2. evaluate a "good" agent
PYTHONPATH=src:examples/demo agenteval eval \
    --cases examples/demo/data/cases.json \
    --outputs examples/demo/data/outputs_good.json \
    --case-package agent_demo \
    --run-root run/good --plan-root run/plans --model-id good-agent

# 3. evaluate a "bad" agent into a separate run
PYTHONPATH=src:examples/demo agenteval eval \
    --cases examples/demo/data/cases.json \
    --outputs examples/demo/data/outputs_bad.json \
    --case-package agent_demo \
    --run-root run/bad --model-id bad-agent
```

Run outputs:

```
run/<model-id>/
├── summary.json          # overall + per-skill scores
├── leaderboard.csv
├── LEADERBOARD.md
├── evidence/<case_id>.json   # auditable evidence trees
└── metric_cache/…            # digest-keyed skill results (reused on re-runs)
```

## AgentOctagon quick start

AgentEval 支持对由 `eval-system` 收集完成的 AgentOctagon attempt 进行评分。AgentEval
不负责启动 run；运行和采集由 `eval-system` 完成：

```bash
# 已有 attempt：确定性环境 scorer
.venv/bin/agenteval octagon-score \
    --data-root /home/yang/agent-octagon/data \
    --env-root /home/yang/agent-octagon-envs \
    --env agent-workspace-smoke-test \
    --attempt-id <attempt_id> \
    --run-root run/octagon-deterministic

# 纯 LLM-as-judge（不要求 scorer.py）
.venv/bin/agenteval octagon-score \
    --data-root /home/yang/agent-octagon/data \
    --env-root /home/yang/agent-octagon-envs \
    --env <env_name> --attempt-id <attempt_id> \
    --judge-only \
    --judge-base-url http://localhost:8000/v1 \
    --judge-model <judge_model> \
    --judge-rubric-file rubrics/<env_name>.txt \
    --run-root run/octagon-judge

# 运行 agent、收集 attempt 和保存 runtime trace：由 eval-system 负责。
# AgentEval 只读取已经完成的 attempt，然后执行 octagon-score。
# 例如：
# eval-system run ... --output /path/to/attempt
# .venv/bin/agenteval octagon-score ... --attempt-id <attempt_id>
```

确定性评分和独立 Judge 可以通过 `--deterministic-weight` 与 `--judge-weight`
混合。AgentEval 只负责构造 JudgeRequest 并消费 JudgeResponse；证据查询、证据链和
judge policy 属于独立 Judge 项目。运行 agent、收集 attempt 和保存 runtime trace 属于
`eval-system`。

详细的三层边界、runtime contract、评分模式和结果文件见
[`docs/SYSTEM_BOUNDARIES.md`](docs/SYSTEM_BOUNDARIES.md) 与
[`docs/RUNTIME_ADAPTERS.md`](docs/RUNTIME_ADAPTERS.md)。

## Writing your own case package (cases stay decoupled)

The framework never imports domain code. A case package is any Python
module exposing:

```python
def build_registry() -> SkillRegistry: ...   # register your skills
def build_router(registry) -> Router: ...    # rule or LLM routing
SKILL_WEIGHTS = {...}                        # optional, for aggregation
```

Example (`examples/demo/agent_demo.py`): three skills —
`task_success` (rule, core), `format_check` (rule, observation),
`quality_judge` (LLM, diagnostic).

### Rule skill

```python
from agenteval import RuleSkill, SkillResult
from agenteval.protocols import Case

class TaskSuccess(RuleSkill):
    skill_id = "task_success"
    role = "core"
    question = "Does the output contain the exact expected answer?"
    definition_version = "my.domain.task_success.v1"

    def evaluate(self, case: Case, output: str) -> SkillResult:
        ok = output.strip() == case.expected["answer"]
        return SkillResult(skill_id=self.skill_id, status="ok",
                           score=1.0 if ok else 0.0,
                           subscores={"exact_match": 1.0 if ok else 0.0},
                           reasons={"exact_match": "ok" if ok else "mismatch"})
```

### LLM judge skill

```python
from agenteval import LLMBackend, LLMSkill, SkillResult

class QualityJudge(LLMSkill):
    skill_id = "quality_judge"
    role = "diagnostic"
    question = "Is the response clear and correct beyond exact matching?"
    definition_version = "my.domain.quality.v1"
    judge_system = "You are a strict judge. Return JSON only."

    def messages(self, case, output): ...     # build the judge prompt
    def parse(self, parsed, case): ...        # parsed JSON → SkillResult
```

### Routing

* **RuleRouter** — deterministic selection (use when applicability is known):

```python
from agenteval import Plan, RuleRouter

def route(case, catalog):
    return Plan(case_id=case.case_id,
                selected_skills=({"skill_id": "task_success", "role": "core",
                                  "reason": "answers must match", "parameters": {}},),
                skipped_skills=())

router = RuleRouter(route)
```

* **LLMRouter** — an agent reads the case + catalog and returns selected /
  skipped skills **with case-grounded reasons** (mirrors HarnessEval's
  planner). Requires an `LLMBackend` (OpenAI-compatible, urllib only):

```python
from agenteval import LLMBackend, LLMRouter

backend = LLMBackend(base_url="http://localhost:8000/v1",
                     model="Qwen/Qwen2.5-72B-Instruct", api_key="EMPTY")
router = LLMRouter(backend)
```

Plans are validated before use: unknown/duplicate skills and invalid roles
are rejected; a plan must contain ≥1 core skill and (if the catalog has
any) ≥1 observation skill.

## Caching & invalidation

Skill results are keyed by a digest of: skill definition version +
**skill implementation bytecode** + judge backend config + case + output +
parameters. Consequences:

* Re-running unchanged inputs costs nothing (LLM calls skipped).
* Changing a skill's code invalidates its cache even if you forget to bump
  `definition_version`.
* Plans are cached separately under `--plan-root` (shared across models,
  so every model faces the same routing — like HarnessEval).

## Tests

```bash
python -m pytest tests/ -q        # no LLM / network required
```

## Roadmap

- [ ] Judge reliability analysis (self-consistency, judge↔rule agreement)
      as a first-class `agenteval.analysis` module
- [ ] `agenteval verify` for completeness checks of existing runs (partially
      present in CLI)
- [ ] Streaming evidence viewer (evidence tree → HTML)

## License

Apache-2.0. The agentified-evaluation mechanism is adapted from
HarnessEval-W (Apache-2.0); see NOTICE.

## Bundled third-party data

The `examples/` packages bundle **evaluation data from third parties**, which
is separate from the framework license:

* `examples/swebench/instances.json` — 2 instances from
  [`princeton-nlp/SWE-bench_Verified`](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
  (SWE-bench, MIT). See `examples/swebench/README.md`.
* `examples/gdpval/cases.json` — 3 tasks from
  [`openai/gdpval`](https://huggingface.co/datasets/openai/gdpval)
  (no license declared on the HF card as of 2026-08; research/demo use only).
  See `examples/gdpval/README.md`.

Data produced by *running* this system (run outputs, scores, evidence,
history) belongs to the user and is not covered by any open-source grant.

## Rubric as data (Phase 1 of rubric optimization)

Rubrics are **versioned, serializable artifacts** (`Rubric` / `RubricStore`
in `src/agenteval/rubrics.py`), not code. `FineGrainedRubric`
(`src/agenteval/skills/rubric.py`) is the reusable base class that turns a
question list into a full HarnessEval-style skill: analyze/verify
two-stage, discrete score ladder, verbatim-evidence anti-fabrication,
weighted aggregation.

SWE-bench's rubric lives at `examples/swebench/rubrics/patch_quality.json`
— a domain data file, independent of framework code. Adding a new rubric
skill = writing a JSON file + a 15-line subclass:

```python
class MyRubricSkill(FineGrainedRubric):
    skill_id = "my_quality"
    role = "diagnostic"
    question = "..."
    rubric_path = Path(__file__).parent / "rubrics" / "my_quality.json"
```

Why data (not code): Phase 2 (evaluation history records which rubric
version produced a score) and Phase 3 (per-question variance / judge
disagreement analysis → rubric optimization) need rubrics that can be
stored, versioned, compared and regenerated. Agent iteration/repair loops
are intentionally **out of scope** — they are a separate consumer layer
(see the layered design in `docs/architecture.md`).

## Evaluation history (Phase 2)

Every run now appends `history.jsonl` (run_root/history.jsonl): one JSONL
record per (case, skill) with `run_id, model_id, skill_id, rubric_id,
rubric_version, score, subscores, judge, timestamp`. Rules skills record
rubric=None; LLM rubric skills carry their version and judge model, so
history can answer "which rubric version produced which score, by which
judge". Queries: `by_skill / by_rubric / question_stats /
rubric_question_report / summary_by_skill`.

The bundled data already shows the Phase-3 signal: Q3_minimality has the
highest std (0.20 — the dimension that actually separates gold from pi),
while Q1/Q2/Q8/Q10 are constant across agents (low discrimination →
revision candidates).

## Rubric diagnostics (Phase 3.1)

```bash
agenteval analyze --history run/gold/history.jsonl --history run/pi/history.jsonl \
                  --rubric patch_quality [--json report.json]
```

Per question: n / mean / std / entropy / **discrimination =
corr(question, total)** / distribution, plus a rule-based verdict:

| verdict | meaning |
| --- | --- |
| `keep` | spreads AND tracks the overall score — carries signal |
| `ceiling` / `floor` | everyone maxes/fails — no discrimination |
| `noisy` | spreads but weak or **negative** corr — anchors may be inverted |
| `insufficient_data` | < 3 records |

Low variance alone is ambiguous (everyone is good vs rubric too easy vs
judge leniency); correlation with the total score disambiguates. History
records now also carry `evaluator_version` (prompt-design version,
independent from `rubric_version`) and `judge_temperature`, so prompt
changes never contaminate historical data.

## Judge reliability (Phase 3.2)

```bash
agenteval analyze --history run/gold/history.jsonl --history run/pi/history.jsonl \
                  --rubric patch_quality \
                  --judge-skill patch_quality --rule-skill test_resolution
```

Pairs the LLM judge's score with the rule-based skill's verdict per case
and reports **Cohen's κ**(thresholded pass/fail, chance-corrected) and
**Spearman ρ**(raw-score ranking):

| κ | meaning |
| --- | --- |
| ≥ 0.6 | judge and rule agree beyond chance — judge is usable |
| 0.3–0.6 | weak agreement |
| < 0.3 | unreliable — judge has systematic bias |

Demonstrated: a judge that always passes scores κ=0.0 (chance) even
though plain agreement looks high; a reliable judge scores κ=1.0. When
every case passes (no failure samples) κ is undefined — the report says
so rather than inventing a number.

## Rubric version migration (Phase 3.3)

```bash
agenteval migrate --history run/gold/history.jsonl --history run/pi/history.jsonl \
                  --skill patch_quality --old-version 2.0.0 --new-version 3.0.0
```

Benchmarks fail not because scores are wrong but because **v1 and v2
scores are not comparable**. This report answers "can conclusions from
v1 be inherited by v2?":

* **Ranking preservation** — Spearman ρ + Kendall τ (the primary signal;
  absolute drift is expected, ordering flips are the danger)
* **Score drift** — means + per-case deltas; `systematic` (all same sign,
  e.g. rubric got more lenient) vs `mixed` (evaluation logic changed)
* **Question changes** — removed / added / shared between versions
* **Large disagreements** — cases where |Δ| exceeds a threshold

`RubricQuestion.lineage` (ancestor question ids across versions) is part
of the data model, ready for the future proposer.

**Gate**: automatic rubric generation (Layer 4) starts only at ≥50 cases,
≥3 agents, ≥2 rubric versions — below that, LLM-proposed rubrics learn noise.

## Two evaluation regimes, one infrastructure

| | SWE-bench | GDPVal |
| --- | --- | --- |
| agent input | problem statement | professional prompt |
| agent output | patch | deliverable file (as text today) |
| oracle | container tests | human rubric items |
| judge | rule (docker) + LLM rubric | LLM rubric (per-task, dynamic) |
| difficulty | correctness | quality |

The `Skill` / `FineGrainedRubric` abstraction is not coding-patch specific —
GDPVal's rubric is built *per task from the task's own data* (dynamic
rubric) and reuses all framework mechanics (two-stage, discrete ladder,
evidence checks, history, diagnostics).

## Capability layer (cross-benchmark axis)

`RubricQuestion.capabilities` tags what latent capability a question
measures. `capability_report(records, question_capabilities)` aggregates
history by capability across benchmarks:

```bash
# capability report: SWE gold + GDPVal demo history
python - <<'EOF'
from agenteval import HistoryStore, capability_report, render_capability_report
from agenteval.rubrics import RubricStore
records = HistoryStore.load_many(["examples/swebench/run/gold/history.jsonl",
                                  "examples/gdpval/run/demo/history.jsonl"])
q2c = {}
r = RubricStore("examples/swebench/rubrics").load("patch_quality")
q2c["patch_quality"] = {q.id: q.capabilities for q in r.questions}
print(render_capability_report(capability_report(records, q2c)))

## Two evaluation regimes, one infrastructure

| | SWE-bench | GDPVal |
| --- | --- | --- |
| agent input | problem statement | professional prompt |
| agent output | patch | deliverable file (as text today) |
| oracle | container tests | human rubric items |
| judge | rule (docker) + LLM rubric | LLM rubric (per-task, dynamic) |
| difficulty | correctness | quality |

The `Skill` / `FineGrainedRubric` abstraction is not coding-patch specific —
GDPVal's rubric is built *per task from the task's own data* (dynamic
rubric) and reuses all framework mechanics (two-stage, discrete ladder,
evidence checks, history, diagnostics).

## Capability layer (cross-benchmark axis)

`RubricQuestion.capabilities` tags what latent capability a question
measures. `capability_report(records, question_capabilities)` aggregates
history by capability across benchmarks — answering "which capabilities
regressed?" (industrial view) instead of "what did one benchmark score?"
SWE capabilities are hand-annotated in the rubric JSON; GDPVal tags are
inferred from criterion keywords.

## Run manifest + capability taxonomy (Phase 3.5)

Every run writes `run_manifest.json` next to `history.jsonl`:

```json
{
  "run_id": "run-20260822T...",
  "agent": {"name": "pi", "version": "0.1"},
  "environment": {"date_utc": "...", "machine": "...", "platform": "...", "python": "..."},
  "benchmarks": ["gdpval"],
  "evaluator_snapshot": {
    "rubric_versions": {"gdpval_83d10b06": ["1.0.0"], ...},
    "judge_models": ["deepseek-v4-flash"],
    "evaluator_versions": ["1"]
  }
}
```

Answers "under what conditions was this report produced?" — the
reproducibility guarantee for cross-benchmark runs. Pass
`--agent-name/--agent-version/--benchmark` via CLI or the benchmark
scripts.

Capability tags now have a schema: `CapabilityStore` loads a taxonomy
JSON (`id`, `description`, `parent`) and validates question tags against
it. Default taxonomy: `software_engineering → code_reasoning /
code_quality / ...` and `document_production → format_compliance /
numerical_accuracy / ...`. Hierarchy rollup is deferred until more data
exists.

## Human preference → case-specific rubric

AgentEval 也支持把人类偏好案例泛化为具体 case rubric：

```text
Preference examples → MetaRubric → Case Rubric → LLM judge
```

```bash
agenteval rubric-induce \
    --examples preferences/examples.jsonl \
    --output rubrics/human_preference.json \
    --base-url http://localhost:8000/v1 \
    --model <planner-model>

agenteval rubric-instantiate \
    --meta-rubric rubrics/human_preference.json \
    --case cases/example.json \
    --output rubrics/example.generated.json \
    --base-url http://localhost:8000/v1 \
    --model <planner-model>
```

人类偏好案例记录候选答案之间的选择和理由；`MetaRubric` 保存跨 case 的
偏好原则；生成的 `Rubric` 针对当前 case 具体化问题、anchors、权重和证据来源。
生成结果带有 preference/rubric provenance，不能把 Planner 的临时文本当作
不可审计的评分标准。详见 [`docs/RUNTIME_ADAPTERS.md`](docs/RUNTIME_ADAPTERS.md)。

### Octagon judge 使用偏好泛化 rubric

对已有的 `MetaRubric`：

```bash
agenteval octagon-score \
  --data-root /path/to/octagon-data \
  --env-root /path/to/agent-octagon-envs \
  --judge-base-url "$JUDGE_BASE_URL" \
  --judge-model "$JUDGE_MODEL" \
  --meta-rubric rubrics/human_preference.json \
  --generate-rubric
```

若只提供 `--preference-examples`，系统会先归纳 meta-rubric，再针对每个 case 生成
具体 rubric。生成的 rubric 和其来源会写入每个 attempt 的 evidence；它不会被
Planner 直接当作最终分数，最终分数仍由 LLM judge 按 case rubric 产生。
