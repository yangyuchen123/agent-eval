# Agent artifact contract — how runtime outputs enter AgentEval

AgentEval 的核心不实现 agent loop，也不依赖某个 runtime。它消费 runtime
产物并执行评测。对于 AgentOctagon，`octagon-eval` 可以通过公开 HTTP API
创建/等待 run，但仍由 AgentOctagon 负责真正的 agent 执行；对于 Harbor，
可以通过 JSON 导出或实现 `RuntimeAdapter` 接入。

评测核心的输入边界仍然是 runtime 产物：runtime 负责运行，AgentEval
负责将产物规范化、运行 RuleSkill/LLMSkill、保存 evidence 和生成报告。

```
agent runtime (OUTSIDE this repo)          AgentEval (this repo)
┌──────────────────────────────┐           ┌──────────────────────────────┐
│ produces artifacts:          │  JSON     │ evaluate_*.py 吃入产物       │
│  - SWE-bench: patch (diff)   │ ────────► │  → run_eval(plan → skills)   │
│  - GDPVal: deliverable text  │           │  → history / evidence / 报告  │
└──────────────────────────────┘           │  → analyze / migrate / cap.  │
                                           └──────────────────────────────┘
```

## Artifact file formats (the input contract)

### SWE-bench: `predictions.json`

```json
{
  "sympy__sympy-23950": { "model_patch": "diff --git a/...\n..." },
  "sympy__sympy-24443": { "model_patch": "..." }
}
```

* key = `instance_id` (must exist in `instances.json`)
* value = object with `model_patch` (the agent's diff, byte-exact —
  a missing trailing newline breaks `git apply`; the harness adds it back)
* special value `gold` as `--predictions` uses the bundled reference patches

```bash
python examples/swebench/evaluate_predictions.py \
    --predictions predictions.json --run-root run/pi \
    --agent-name pi --agent-version v1
```

### GDPVal: `outputs_<agent>.json`

```json
{
  "83d10b06-26d1-4636-a32c-23f92c57f30b": "I created 'Sample v2.xlsx'...",
  "f84ea6ac-8f9f-428c-b96c-d0884e30f7c7": "Research scan covering..."
}
```

* key = `task_id` (must exist in `cases.json`)
* value = the agent's deliverable **as text** (content report or
  file-generation description; a sandbox executor can be plugged in later)

```bash
python examples/gdpval/evaluate_gdpval.py \
    --outputs outputs_pi.json --run-root run/pi \
    --agent-name pi --agent-version v1
```

## Runtime ownership

Runtime remains outside the AgentEval core. The adapter layer is intentionally
read-only for persisted runs and only the AgentOctagon HTTP client performs
transport-level run orchestration. It does not import or reimplement the
AgentOctagon runner.

## Where the legacy example runtime used to live (removed)

* `examples/swebench/run_pi_agent.{py,mjs}` — drove pi (pi SDK +
  deepseek-v4-flash) on the host to produce patches
* `examples/gdpval/run_pi_gdpval.{py,mjs}` — drove pi on GDPVal tasks
* `work/` checkouts, `node_modules/`

All removed. If you need to regenerate artifacts, drive the agent from
*outside* this repo and write the JSON per the formats above.

## Why the split

* evaluation must be **provider-agnostic** — the same predictions can be
  scored, analyzed and migrated no matter which agent/model produced them;
* agent runtimes are heavy (SDK, auth, network, model calls, long
  generation times, instability) — none of that belongs in an evaluation
  framework;
* the *output* of the runtime is the only interface, and it is just JSON.
