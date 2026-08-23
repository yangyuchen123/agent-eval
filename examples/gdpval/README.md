# GDPVal case package — real professional deliverable tasks

Evaluate agents on 3 real GDPVal tasks (from `openai/gdpval`, 220 tasks /
9 sectors / 44 occupations). Each task asks the agent to produce a
professional *deliverable file* (Excel / Word / PDF) meeting a human-written
rubric.

```
agent (host)                        GDPVal judge
┌──────────────────────────┐        ┌─────────────────────────────────────┐
│ reads the professional    │  text  │ GDPValJudgeSkill (per-task rubric): │
│ prompt (audit, research,  │ ─────► │  each human rubric item → question  │
│ budget...)               │        │  judge scores 0/1 per item          │
│ produces deliverable      │        │  total = Σ satisfied item scores    │
└──────────────────────────┘        │  (negative items = penalties)        │
                                    └─────────────────────────────────────┘
```

## The 3 bundled cases

| case | occupation | deliverable | rubric items |
| --- | --- | --- | --- |
| `83d10b06…` | Accountants and Auditors | Excel (Sample v2.xlsx) | 38 |
| `f84ea6ac…` | Administrative Services Managers | Word (research scan) | 30 |
| `99ac6944…` | Audio and Video Technicians | PDF (IEM budget) | 52 |

Data is decoupled: `cases.json` holds prompt + rubric items + deliverable
names for all 3 tasks. Add more by re-exporting from the HF dataset — no
code changes.

## Data provenance & license

`cases.json` bundles 3 tasks re-exported from
[`openai/gdpval`](https://huggingface.co/datasets/openai/gdpval)
(GDPval, OpenAI). As of 2026-08 the HF dataset card does **not** declare a
license; the bundled subset is provided for **research / demo use only**.
Redistributing it beyond this repo, and any commercial use, is your
responsibility to clear with the dataset owner. The framework code in this
repo is licensed separately under Apache-2.0 (see repo `NOTICE`).

## Skills

* **`GDPValJudgeSkill`** (core, LLM) — a `FineGrainedRubric` built *per
  task* from its rubric items: each criterion becomes a 0/1 question,
  weight = the item's score. Aggregation is a **weighted sum** (GDPVal
  total; negative weights are penalties). Judge config: DeepSeek by
  default, `AGENTEVAL_JUDGE_BASE_URL/MODEL` to override (same as swebench
  package). Evidence quotes must appear verbatim in the output.
* **`artifact_presence`** (observation, rule) — does the output claim the
  required deliverable file name?

## Usage

```bash
# outputs_demo.json: case_id → agent output text (deliverable report or
# file-generation code)
python evaluate_gdpval.py --outputs outputs_demo.json --run-root run/demo
# rule-checks only (no LLM spend):
python evaluate_gdpval.py --outputs outputs_demo.json --no-judge
```

Scores are **rubric totals** (Σ satisfied item scores / max possible),
which can exceed 1.0 — the report shows `score / max_possible` per case.

## Note on the judge contract

GDPVal's real judge reads the actual deliverable *files*; this package
scores the agent's **text output** against the rubric (a sandbox executor
can be plugged in later). The `FineGrainedRubric` mechanics — two-stage
analyze/verify, discrete scores, verbatim-evidence checks — carry over
unchanged. One real-world find: judge prompts must not contain concrete
key examples (`{"Q1": ...}`), because DeepSeek copies the shape and
renames your questions to match the example.
