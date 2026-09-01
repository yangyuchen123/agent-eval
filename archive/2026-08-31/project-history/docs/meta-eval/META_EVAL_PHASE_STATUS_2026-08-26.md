# Meta-Evaluation Phase Status — August 26, 2026

## Completed infrastructure

- GoldJudgment schema and human-only Gold policy;
- R1–R12 failure taxonomy;
- deterministic EvidenceSnapshot replay;
- order, reviewed distractor, removal, paraphrase and corrected synthetic length primitives;
- score/status/evidence/exact-claim stability metrics;
- token usage, latency and provider-cost provenance;
- AgentOctagon read-only discovery and score/attempt joins;
- 30 balanced Gold review packets across 30 environments;
- three real Judge modes:
  - Full-Trace Judge;
  - Static Retrieval Judge;
  - Agentic Evidence Judge.

## Completed real experiments

```text
real Judge calls: 77
six-case frozen Agentic batch: 18 calls
corrected two-case perturbation batch: 12 calls
first real three-mode comparison: 18 calls
other initial/exploratory Agentic calls: 11
discrete-anchor v2 five-question run: 15 calls
discrete-anchor v3 focused validation: 3 calls
```

The first three-mode result is documented in:

```text
docs/META_EVAL_THREE_MODE_RESULTS_2026-08-26.md
```

Key result: on two short traces, Agentic was more expensive and less score-stable
than both no-tool baselines. This is not an accuracy ranking because human Gold
is still unavailable, and the selected short traces do not exercise relation
navigation.

## Corrected diagnostic issue

R12 classification previously omitted the current repeat and had a float boundary
problem at a nominal score range of 0.1. The classifier and regression tests are
fixed. Existing three-mode judgments were deterministically reclassified without
changing any model output.

## Not yet completed

- human review of the 30 Gold packets;
- ≥30 real cases with real Judge outputs;
- human agreement and R1–R10 empirical rates;
- three-mode comparison on long/relational traces;
- Evidence Removal Sensitivity with human-approved required evidence;
- human-reviewed semantic distractors;
- rubric paraphrase runs;
- a controlled comparison with text-equivalent judging policy across modes.

## Next priority

The next highest-value step is not another generic short-trace batch. It is to
review a small first Gold tranche and select cases where the methods should differ:

```text
1. short direct trace where static/full should be sufficient;
2. long noisy trace where full context may dilute evidence;
3. multi-agent relation/handoff trace where navigation should help;
4. artifact-success/runtime-failure conflict;
5. key-evidence removal pair.
```

Until Gold exists, the report must continue to mark accuracy, evidence recall and
human agreement as unavailable.

## Discrete per-dimension anchor protocol

The first three-mode run showed that identical evidence refs can still produce
materially different continuous scores. v2 introduced five independent
QuestionJudge dimensions with observable `0 / 0.5 / 1` anchors and explicit
AgentEval aggregation. Its real experiment exposed one overlapping anchor.

The completed v2 protocol remains frozen for replay. New experiments use:

```text
generic-runtime-process-reliability@frozen-2026-08-26.discrete-anchors-v3
```

Historical bundled, v2 and v3 outputs remain versioned and must not be treated as
the same scoring protocol.

## Discrete-anchor v2 real result

A 15-call real Agentic experiment on `att_3f38a0fe1604` produced exact anchor
agreement on 4/5 dimensions. `observed_failure_handling` scored `0/0/1`, causing
the equal-weight aggregate to remain unstable at `0.3/0.3/0.5`. The decisive
records were found in all runs; the failure was an overlapping rubric boundary,
not searchability.

The completed v2 protocol is preserved for replay. The current v3 protocol
narrows failure handling to explicit agent-visible operation/check failure
signals and routes wrong outcomes and unsupported claims to their own dimensions.
Detailed audit: `docs/META_EVAL_DISCRETE_ANCHOR_RESULTS_2026-08-26.md`.


## v3 focused validation result

The corrected failure-handling anchor was run three times on the same smoke trace:

```text
v2: 0 / 0 / 1
v3: 1 / 1 / 1
```

The v3 group has exact anchor agreement, score std 0, no automatic failure label,
and evidence Jaccard 0.7672. This is a successful local correction, not yet a
general reliability claim.

## 11. v3 blind generalization preparation

v3 is frozen after the single-case focused experiment. A generic, offline,
human-review-first scanner now builds unseen failure-handling candidates from
AgentOctagon archives without running a Judge or treating Octagon score as Gold.

Current blind-set artifact:

```text
run/meta_eval/failure-handling-blind-v1/
```

Current selection properties:

```text
352 attempts scanned
16 packets selected
16 distinct environments
development attempt excluded
development environment excluded
Gold status: pending_human_review
```

The generated packet stores the task, trace digest, full evidence snapshot,
structured candidate signals, nearby evidence, later-success candidates, and
blank human fields for applicability/A-H stratum/anchor/evidence.

The real scan exposed and fixed a cross-runtime false-positive source: nested
assistant messages or code that merely mention failure words are no longer
classified as operation failures. Signals require structured runtime result or
lifecycle fields. Candidate labels are explicitly prefixed with `review_` and
must not be interpreted as Gold.

Therefore the current generalization conclusion remains:

```text
v3 is conceptually generic and free of case-specific IDs/strings,
but empirical human agreement on unseen cases is still unavailable.
```

## 12. Four-level anchor ablation

A versioned v4 rubric is prepared to isolate score-resolution effects without
changing Judge instructions or EvidenceCatalog behavior:

```text
v3: 0 / 0.5 / 1
v4: 0 / 1/3 / 2/3 / 1
```

The v4 descriptions split `partial` into `limited` and `substantial`. All other
question text and evidence policy are preserved. This is not yet a conclusion
about the preferred rubric. Real model calls are required to compare stability,
anchor agreement, and (after Gold review) error.

## 13. Three-level vs four-level anchor ablation

A real same-trace ablation was completed without changing Judge prompt or evidence
behavior:

```text
v3: 0 / 0.5 / 1
v4: 0 / 1/3 / 2/3 / 1
```

Each version ran the five independent questions three times on
`att_3f38a0fe1604` (30 external calls total). v3 aggregate scores were
`0.5 / 0.5 / 0.5` (`std=0`); v4 aggregate scores were
`0.533333 / 0.533333 / 0.6` (`std≈0.03849`). The v4
`required_action_execution` dimension varied between `1/3` and `2/3`, while
v3 remained at `0.5`. Thus, on this case, the extra level increased resolution
but did not reduce observed variance. Accuracy/bias remains unavailable without
human Gold. Full details:

```text
run/meta_eval/octagon-real/anchor-resolution-ablation-comparison.md
```

## 14. First human Gold tranche

The first blind failure-handling review set has now been manually labeled for the
frozen v3 question:

```text
run/meta_eval/failure-handling-blind-v1/gold/
run/meta_eval/failure-handling-blind-v1/gold-manifest.json
```

Coverage:

```text
16 judgments
7 applicable explicit-failure cases
9 not-applicable cases
2 expected score 0
14 expected score 1
0 expected score 0.5
```

The absence of `0.5` in this first tranche is a property of the selected sample,
not evidence that partial recovery is impossible. The Gold records preserve
`applicability`, formal A-H stratum, required/positive/negative evidence refs,
and notes. Octagon score/status are retained only as diagnostic metadata in the
review packet and were not used to assign Gold.

## 15. Two-level and five-level ablations prepared

To test the resolution/variance hypothesis under controlled conditions, two
additional versions are now available:

```text
2 levels: 0 / 1
3 levels: 0 / 0.5 / 1
4 levels: 0 / 1/3 / 2/3 / 1
5 levels: 0 / 0.25 / 0.5 / 0.75 / 1
```

The two- and five-level variants preserve v3 question text, evidence policy,
capabilities, weights, and Judge prompt path. They are experimental only. The
historical v2 name remains reserved for the earlier three-anchor replay and is
not reused for the two-level variant.

## 16. 2/3/4/5-level real ablation result

The controlled same-trace experiment is complete. The result is non-monotonic:

```text
2 levels: aggregate std=0
3 levels: aggregate std=0
4 levels: aggregate std≈0.03849
5 levels: aggregate std=0
```

The four-level condition alone oscillated on
`required_action_execution` (`1/3, 1/3, 2/3`). The five-level condition did not
oscillate in score, although its observed-failure evidence Jaccard was only
`0.111`, showing that score stability does not imply evidence-path stability.

Therefore the current evidence rejects the simple claim that more score levels
necessarily produce higher variance. More levels can create boundary ambiguity,
but variance is not monotonic in level count. Accuracy remains unavailable for
this case because it has no approved Gold judgment.

## 17. Gold-backed 2/3/4/5 comparison

The first Gold-backed comparison ran 64 real Judge calls: 16 reviewed cases,
`observed_failure_handling` only, one call per case per anchor condition.

Results:

```text
2 levels: strict accuracy 56.25%, MAE 0.4000
3 levels: strict accuracy 62.50%, MAE 0.2667
4 levels: strict accuracy 62.50%, MAE 0.2708
5 levels: strict accuracy 68.75%, MAE 0.2167
```

This tranche has 14 Gold score-1 cases, 2 score-0 cases, and no score-0.5 cases.
Therefore five levels look best for this one-shot tranche, but partial-recovery
accuracy and repeated-run stability remain unavailable. The result does not
support a monotonic level-count/variance law. Full report:

```text
run/meta_eval/octagon-real/anchor-resolution-gold-v1/GOLD_COMPARISON_REPORT.md
```

## 18. Gold diversity correction gate

The Gold tranche was expanded on 2026-08-26 with a first manually reviewed
partial-recovery case:

```text
att_f7830b42a3d8
observed_failure_handling = 0.5
B_explicit_failure_partial_recovery
```

The Gold set now contains 17 judgments:

```text
score 0.0:  2
score 0.5:  1
score 1.0: 14
```

This fixes the immediate absence of a middle anchor, but it does not yet make the
set balanced. The next data-collection gate is therefore **Gold diversity before
more Judge comparison runs**. New cases must be deliberately sampled across:

```text
explicit failure ignored                 → 0
partial or unresolved recovery           → 0.5
fully diagnosed and verified recovery    → 1
not applicable / warning / fallback      → applicability=no
wrong outcome without explicit failure   → applicability=no
artifact success vs runtime failure      → mixed evidence
runtime success vs incomplete artifact   → mixed evidence
```

Octagon score is allowed only as a discovery/filtering signal. It must not be used
as the Gold label. Each new Gold case must have direct runtime evidence, a human
stratum, required evidence refs, and an explicit missing-evidence explanation when
it is partial or unverified.

Before interpreting anchor-count accuracy, the target minimum is:

```text
≥ 8 partial-recovery cases
≥ 5 explicit-failure-ignored cases
≥ 5 fully-recovered cases
≥ 5 not-applicable / applicability-control cases
```

The exact counts may be adjusted after review, but a Gold set dominated by score 1
must not be used to claim that five-level anchors generalize. Gold files are
validated by:

```bash
python3 tools_validate_failure_gold.py
```

This tool validates references and schema only; it never infers or changes a human
label.

## 19. Gold diversity candidate set generated

To avoid continuing experiments on a score-1-dominated Gold set, a second blind
candidate set was generated after excluding all existing Gold attempt IDs:

```text
run/meta_eval/failure-handling-diversity-v3/
```

It contains 40 review packets from 39 environments. Candidate strata are
heuristics for human review, not labels. The set includes explicit failures with
later success candidates, unresolved recovery candidates, ignored-failure
candidates, warnings/fallbacks, observer-side failures, and semantic-failure
controls. The review protocol and minimum distribution gate are documented in:

```text
docs/META_EVAL_GOLD_DIVERSITY_PLAN_2026-08-26.md
```

No new Judge calls are run until this candidate set has been reviewed into a more
balanced Gold distribution.

## 20. First manual review of diversity candidates

Six candidates from `failure-handling-diversity-v3` were manually reviewed against
raw trace lines and added to the Gold manifest. The Gold set now has 30 judgments:

```text
score 0.0: 2
score 0.5: 8
score 1.0: 20
applicable: 20
not_applicable: 10
```

The review log is:

```text
docs/META_EVAL_GOLD_REVIEW_LOG_2026-08-26.md
```

This is a meaningful improvement over the previous 2/1/14 distribution, but it is
still below the planned partial-recovery and ignored-failure targets. No new
anchor-count comparison is run yet. The next manual-review pass must prioritize
additional `B_explicit_failure_partial_recovery` and `A_explicit_failure_ignored`
samples. The current set is still below both targets: 8/8 partial and 2/5 ignored.
