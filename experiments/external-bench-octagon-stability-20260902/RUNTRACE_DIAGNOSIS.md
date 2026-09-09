# Runtrace diagnosis: environment vs. agent capability

## Scope

Analyzed the 36 attempt records from the 4-task × 3-repeat stability run, including:

- `conversation.jsonl`
- `events.jsonl`
- `trace.jsonl` where present
- `skill_workspace` artifact trees
- AgentOctagon `attempts` and `scores` tables in `data/octagon.db`

Diagnostic extraction is in:

- `runtrace_diagnostics.tsv`
- `runtrace_diagnostics.json`

## High-level conclusion

The observed score variance cannot currently be interpreted as pure agent capability. There are three major confounders:

1. **Benchmark adaptation/data bug**: AgencyBench Code scenario 2 and scenario 3 are byte-for-byte identical at the source description level, but were labeled as two different tasks with different, arbitrary expected-artifact lists.
2. **Runner deadline/recovery confound**: 9 of 36 attempts have `agent_timeout`, 9 have `agent_total_timeout`, and several attempts received a score after an execution timeout or recovery path. This affects all three agents, especially long-running coding tasks.
3. **Interaction/tooling confound**: Blade asked for user input on a fully specified task twice; AgentOctagon has no automatic response in this run, so those attempts became `interrupted` with no artifacts.

Consequently, only a small part of DEVAI 52's result is evidence of an agent capability difference. The AgencyBench 2/3 and DEVAI 54 results are substantially confounded by task/scorer/runner behavior.

## 1. AgencyBench 2 — repo-review

### Trace evidence

- Claude repeat 1 immediately records:
  `unrecognized_model` during `generate_session_title`, although the trace also contains 2,597 events and 191 workspace files. This is a provider/adapter environment issue, not a task-solving failure.
- Codex repeat 1 performs extensive dependency installation and Chroma/SentenceTransformers experiments, then ends with `timeout after 900s`; it has 213 workspace files and 201 command events.
- Blade repeat 1 performs 19 Bash and 11 Write operations and creates 11 files, then ends in `agent_total_timeout` during restart recovery.
- In repeat 2 Claude and Blade both complete with score 100; Codex times out and scores 40.
- In repeat 3 Blade completes with score 100; Claude scores 8 after timeout; Codex scores 40.

### Adaptation/scorer defect

The adapted task declares only `README.md` as the expected artifact. The original scenario is a repository modification task requiring documentation, a Qdrant integration, Chroma compatibility changes, CI/dependency changes, and tests. The supplied material is under `source/`, while agents often clone/work in `repo/` or `autogen/`.

The scorer therefore gives:

- `task_completion=0` if root-level `README.md` is absent, even when the agent has implemented the requested repository changes;
- `artifact_quality=100` for syntax-parsing many unrelated Python files;
- `validation_evidence=100` for generic occurrences of words such as `test`, `check`, or `report`.

### Diagnosis

**Primary cause: environment/adaptation/scorer problem.**

There is some agent-level execution variance (Codex's long dependency installation and timeout), but the 8/40/100 scores do not measure the original task reliably. This task should not be used for a capability ranking until its expected artifacts and scorer are rewritten against the actual requirements.

## 2. AgencyBench 3 — event-generator

### Trace evidence

The task prompt hash is exactly the same as AgencyBench 2 in every repeat:

```text
sha256:a23ff0a9e3f070b6eabc6f615c9ed50861c3def76a9cad8eedb66a4333b0e5b8
```

The source description JSON for AgencyBench Code scenario 2 and scenario 3 also has the same SHA-256:

```text
76a7220f93572838eb5d64b6bfe7b8738f753cfc34c33900f46f345552d0554a
```

They are not two distinct scenarios. Scenario 3 was accidentally duplicated from scenario 2.

The expected artifacts for scenario 3 (`subtask1_generator.py`, `domain`) do not correspond to the duplicated prompt, which asks for the Qdrant/Chroma/repository task. All three agents consequently converge around score 40, with one Codex repeat at 15.

### Diagnosis

**Definitive environment/data-construction failure.**

The apparent lack of discrimination is not evidence that the agents have equal capability. This task must be discarded and regenerated from a genuinely distinct AgencyBench scenario before any further comparison.

## 3. DEVAI 52 — qlora

### Trace/artifact evidence

- Claude repeat 1 creates a complete QLoRA repository clone, `src/env.py`, `src/data_loader.py`, scripts, and MMLU data; 306 workspace files.
- Codex repeat 1 creates a virtual environment with 1,202 files and performs extensive setup; this is consistent with over-expansion/inefficient execution, not a missing environment.
- Blade repeat 1 reaches execution deadline with zero workspace files.
- Claude repeat 2/3 creates the requested offline/mock artifacts and receives 85/92.
- Codex receives 85, then 40 after a `gave_up`/timeout repeat, then 85.
- Blade receives 62/70 on completed repeats, with one execution-deadline timeout.

### Environment confounders

The original DEVAI task asks for a real 7B LLaMA fine-tune, upstream GitHub repository, dataset download, and model output. The Octagon adaptation explicitly permits an offline/mock fallback, but the task still contains a high-cost and potentially GPU/network-dependent workflow. The 900-second execution deadline is not well matched to cloning, dependency installation, dataset preparation, model setup, and training.

AgentOctagon also records timeout-family errors on attempts that later have `completed` status and a score, e.g.:

- Claude: `completed` + `timeout after 900s`
- Codex: `completed` + `agent_timeout`
- Blade: `completed` + `agent_total_timeout`

That means completion status and score are not independent of runner recovery behavior.

### Diagnosis

**Mixed, but mostly confounded.**

There is credible evidence of a systematic artifact difference—Claude consistently produces the requested offline/mock deliverables, while Blade is lower and once produces nothing. However, Codex's 40-point repeat and Blade's timeout are strongly affected by the deadline and setup strategy. The safest conclusion is:

> DEVAI 52 shows a plausible Claude-over-Blade implementation advantage, but the current runtrace does not establish a clean model capability effect. It also measures planning efficiency, dependency handling, and timeout robustness.

## 4. DEVAI 54 — OpenAI response analyzer

### Trace evidence

- Claude completes all three repeats with the four expected files and score 100 each time.
- Codex completes all three repeats with expected files; one repeat ends with `agent_timeout` but still has all four expected files and score 100/100/62 across the repeats.
- Blade completes one repeat with all files and score 100. In two repeats the first substantive interaction is `AskUserQuestion`; the task is already fully specified, but no user answer is supplied. Those attempts end with `blade_session_waiting_for_input` and zero workspace files.
- The Blade trace for the interrupted repeat contains only a few operations: `Read`, `Bash`, and `AskUserQuestion`.

### Diagnosis

**The two Blade failures are an interaction-policy confound, not evidence of coding inability.**

The decision to ask an unnecessary clarification is agent behavior, but the fact that the run cannot answer or auto-close that question is an AgentOctagon/HITL protocol limitation. The 100/100/100 Claude result and the completed Codex/Blade artifacts show that the task itself is solvable in the environment.

The task also has a scorer ceiling: successful implementations receive 100 even if the implementation details differ materially. The single Codex 62 is therefore an execution/path outlier, not a stable capability distinction.

## Quantitative attribution of observed failures

Across 36 attempts:

- 17 `completed`
- 16 `gave_up`
- 2 `interrupted`
- 1 `timeout`

Execution/recovery error families:

- 9 `agent_timeout`
- 9 `agent_total_timeout`
- 5 `timeout after 900s`
- 2 `blade_session_waiting_for_input`
- 1 Claude provider `unrecognized_model`
- 1 persistent `execution_deadline_exceeded`

These counts alone show that a large portion of variance is generated by the execution substrate and protocol, not just by final artifact quality.

## Final classification

| Task | Environment/adaptation issue | Agent behavior issue | Capability conclusion |
|---|---|---|---|
| AgencyBench 2 | **High**: wrong expected artifact/scorer; provider and timeout confounds | Medium: Codex/others overrun | Cannot rank agents |
| AgencyBench 3 | **Certain**: duplicate source/prompt and wrong expected artifacts | Low | Invalid comparison; discard |
| DEVAI 52 | **High**: GPU/network/high-cost task under 900s; recovery timeout semantics | Medium–High: setup efficiency and fallback discipline differ | Plausible Claude > Blade, not cleanly identified |
| DEVAI 54 | Medium: no HITL response path; scorer ceiling | Medium: Blade asks unnecessary question; Codex has one timeout path | Solvability is demonstrated; capability gap not established |

## Recommended next experiment

1. Regenerate AgencyBench 2 and 3 from distinct source scenario JSONs.
2. Define expected artifacts from the actual original requirements, not a placeholder `README.md`/`subtask1_generator.py` list.
3. Add a task-level `max_execution_seconds` appropriate to the task or use an offline bounded version.
4. Disable or automatically answer unnecessary Blade clarification questions for fully specified tasks, or mark them as agent-policy failures separately from environment failure.
5. Replace the generic scorer with requirement-level checks and a non-ceiling score.
6. Re-run only DEVAI 52 and a corrected AgencyBench task after these changes; do not reuse the current scores as a baseline.
