# Agent artifact contract — how agent outputs enter AgentEval

AgentEval does **not** run agents. It consumes their artifacts. This
boundary is the whole point: the framework evaluates and analyzes, the
agent runtime lives elsewhere (a separate repo, CI, or any model provider).

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

## Where the runtime used to live (removed)

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
