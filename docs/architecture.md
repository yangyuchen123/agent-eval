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
| 3.2 | Judge reliability | κ / ρ / self-consistency | ✅ done |
| 3.3 | Rubric version migration | Ranking preservation across versions | ✅ done |
| 3.4 | Capability layer | Cross-benchmark aggregation by latent capability | ✅ done |
| 3.5 | Run manifest + capability schema | Reproducibility: what produced this report? | ✅ done |
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

## Layer 3.2 — judge reliability (done)

`judge_rule_agreement` pairs, per case, the LLM judge score and the
rule-based skill score from history:
* **Cohen's κ** on thresholded pass/fail verdicts (chance-corrected);
* **Spearman ρ** on raw scores (ranking consistency).

Demonstrated: a reliable judge scores κ=1.0; a judge that always passes
scores κ=0.0 (chance level) — κ exposes systematic leniency that plain
accuracy hides. Boundary: with no failure samples (all cases pass), κ is
undefined (p_exp=1) — the report says so explicitly.

Self-consistency (repeated scoring std) needs multi-run data; the stub is
in place.

## Layer 3.3 — rubric version migration (done)

`agenteval migrate --history ... --skill patch_quality --old-version v1
--new-version v2`: pairs the same cases across two rubric versions and
answers **can v1 conclusions be inherited by v2?**

* ranking preservation: Spearman ρ + Kendall τ (the primary signal —
  absolute scores will drift, orderings matter);
* score drift: means + per-case deltas, `systematic` (all same sign)
  vs `mixed` (rubric logic changed) shift;
* question changes: removed/added/shared (from recorded subscores);
* large disagreements: cases with |Δ| over a threshold.

`RubricQuestion.lineage` (ancestor ids across versions) is in the data
model for the future proposer.

**Gate for Layer 4 (proposer)**: only start automatic rubric generation
with ≥50 cases, ≥3 agents, ≥2 rubric versions — below that, LLM-proposed
rubrics learn noise.

## Layer 3.4 — Capability layer (done)

`RubricQuestion.capabilities` (latent capability tags, e.g.
`numerical_accuracy`, `code_efficiency`) make cross-benchmark analysis
meaningful: SWE-bench Q3_minimality and GDPVal I17_formula_correctness
both tag `numerical_accuracy`, so `capability_report` answers
"which agent capabilities regressed?" instead of "what did this benchmark
score?". SWE rubric JSON carries hand-annotated tags; GDPVal tags are
inferred from criterion keywords (overridable per task).

**Future seams (recorded, not built yet):**
* *Artifact abstraction* — skill inputs today are text (`patch`/`report`);
  image/slide/repo/data-pipeline artifacts will need an `ArtifactSet`
  layer. The `evaluate(case, output)` boundary stays until then.
* *Capability rollup* — parent-capability aggregation over the taxonomy
  tree (child scores → parent) is deferred until more data exists; the
  taxonomy schema is in place (`agenteval.capabilities`).
* *JudgeContract* — DeepSeek copied the `{"Q1": ...}` example shape from
  the prompt and renamed questions to match (judge output contamination).
  A schema validator + repair layer independent of the prompt is the long-
  term fix; `parse` compensates today.

## Layer 4 — Rubric optimization (planned)

LLM proposes rubric edits (reword anchors, split/merge questions, adjust
weights) from the analysis; a human approves; the new rubric version is
evaluated for agreement with the old one before adoption.

## Layer 3.5 — Run manifest + capability schema (done)

* `src/agenteval/manifest.py` — `EvaluationRun`: run_id, agent (name/
  version), environment (date/machine/platform/python), benchmarks,
  evaluator_snapshot (rubric versions, judge models, evaluator versions
  seen in the run's history). `run_eval` writes `run_manifest.json`
  automatically; CLI `--agent-name/--agent-version/--benchmark`.
* `src/agenteval/capabilities.py` — `Capability` (id/description/parent)
  + `CapabilityStore` (taxonomy JSON load/validate/tree) + a default
  taxonomy (software_engineering → code_*; document_production → format/
  numerical/...). Question tags can now be validated against the
  ontology; hierarchy aggregation (rollup) is deferred (no automation
  until the data gate).

Industrial question answered: *under what conditions was this report
produced?* — every run is auditable (who/what/when/which rubric/judge).
