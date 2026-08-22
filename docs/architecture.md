# Architecture: evaluation core → meta-evaluation

This project is an **evaluation infrastructure**, not an agent framework.
The boundary is deliberate:

```
             Agent Improvement System        ← OUT OF SCOPE (consumer layer)
                      │
              Feedback / Repair Loop
                      │
             ┌────────▼────────┐
             │   AgentEval     │   ← THIS PROJECT
             │  Evaluation Core│
             └───────┬─────────┘
        ┌────────────┼────────────┐
        │            │            │
   Rubric        History      Skills
   Engine        Store        Evaluator
```

## Why agent iteration stays out

Agent self-iteration ("use evaluation to improve the agent") is a control
system that can sit on *any* evaluator (SWE-bench, human preference,
safety). Mixing it into the evaluation framework would pull in benchmark,
judge, database *and* agent-framework concerns at once. It belongs in a
separate repo that depends on AgentEval:

```
agent-improvement/
    └── loop:  agent.revise( feedback( AgentEval.evaluate(...) ) )
```

## What belongs here (by phase)

| Phase | Layer | Question answered | Status |
| --- | --- | --- | --- |
| 1 | Rubric as data | How are evaluation standards defined & versioned? | ✅ done |
| 2 | Evaluation history | What score, which rubric version, when? | ✅ done |
| 3 | Rubric analysis | Which questions discriminate? Which judges disagree? | planned |
| 4 | Rubric optimization | LLM proposes rubric edits, human approves | planned |

Naming: we say **rubric optimization** (calibration), not "self-evolving"
— no over-promising.

## Layer 1 — Rubric as data (current)

* `src/agenteval/rubrics.py` — `Rubric`, `RubricQuestion`, `RubricStore`
  (versioned JSON, load/save/validate), plus the evidence-matching utils.
* `src/agenteval/skills/rubric.py` — `FineGrainedRubric` base class:
  analyze/verify two-stage, discrete ladder, verbatim evidence with
  anti-fabrication, weighted aggregation. A new rubric skill is a JSON
  file + a ~15-line subclass.
* `examples/swebench/rubrics/patch_quality.json` — domain rubric (data,
  versioned), decoupled from framework code.

## Layer 2 — Evaluation history (done)

`src/agenteval/history.py` — append-only JSONL (no DB): `run_id, model_id,
case_id, skill_id, rubric_id, rubric_version, score, subscores, status,
judge, timestamp`. Runner writes it automatically; queries:
`by_skill / by_rubric / question_stats / rubric_question_report /
summary_by_skill` — exactly the input Phase 3 needs.

Sample discrimination report on the bundled data (3 records):
Q3_minimality std=0.20 (best discriminator), Q1/Q2/Q8/Q10 std=0
(candidates for revision in Phase 3).

## Layer 3 — Rubric analysis (planned)

Per-question statistics across runs and models:
* discrimination — variance across agents; questions where everyone scores
  the same carry no signal;
* consistency — judge self-consistency (repeat scoring std), judge↔rule
  agreement (κ/ρ), judge-model sensitivity;
* reports (JSON + readable), human decides what to change.

## Layer 4 — Rubric optimization (planned)

LLM proposes rubric edits (reword anchors, split/merge questions, adjust
weights) from the analysis; a human approves; the new rubric version is
evaluated for agreement with the old one before adoption.
