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
| 3.1 | Rubric diagnostics | Which questions discriminate? (variance/entropy/corr) | ✅ done |
| 3.2 | Judge reliability | Self-consistency, judge↔rule agreement | planned |
| 3.3 | Rubric version migration | Ranking consistency across rubric versions | planned |
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

## Layer 3.1 — Rubric diagnostics (done)

`src/agenteval/analysis.py` + `agenteval analyze` CLI:
* variance / entropy / difficulty / distribution per question;
* **discrimination** = corr(question, total) — an IRT-style item-quality
  proxy. Low variance is ambiguous (everyone good / rubric too easy /
  judge leniency); correlation with the overall score disambiguates;
* rule-based verdicts: `ceiling` (everyone maxes), `floor`, `noisy`
  (weak or negative corr — anchors may be inverted), `keep`, `insufficient_data`.

Human reads the report and decides; no automatic rubric generation yet.

## Layer 3.2/3.3 — judge reliability & version migration (planned)

* 3.2: judge self-consistency (repeated scoring std), judge↔rule agreement
  (κ/ρ), pairwise preference validation (human prefers A, judge agrees?).
* 3.3: when a rubric version changes, compare ranking consistency before
  adopting the new version (evaluator_version in history makes this safe).

## Layer 4 — Rubric optimization (planned)

LLM proposes rubric edits (reword anchors, split/merge questions, adjust
weights) from the analysis; a human approves; the new rubric version is
evaluated for agreement with the old one before adoption.
