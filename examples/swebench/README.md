# SWE-bench case package — real agents, real containers

Evaluate **pi (the coding agent, backed by DeepSeek V4 Flash)** on two
lightweight SWE-bench_Verified instances, scored inside official-style
SWE-bench **docker containers**. This is the reference integration that
ties AgentEval to a real benchmark with a real agent.

```
pi agent (host)                         SWE-bench containers (scoring only)
┌──────────────────────────┐           ┌─────────────────────────────────┐
│ checkout repo@base_commit │  patch   │ sweb.eval.x86_64.<instance_id>  │
│ pi + deepseek-v4-flash    │ ───────► │   /testbed (repo + test_patch)   │
│ solves the issue          │          │   git apply model.patch          │
│ git diff → model_patch    │          │   pytest F2P + P2P              │
└──────────────────────────┘           └─────────────────────────────────┘
```

## Instances (bundled in `instances.json`)

| instance | repo | F2P | P2P | why |
| --- | --- | --- | --- | --- |
| `sympy__sympy-20916` | sympy | 1 | 1 | minimal, pure Python |
| `sympy__sympy-24443` | sympy | 1 | 1 | minimal, pure Python |

Data is **decoupled**: `instances.json` is plain JSON; add more instances
by re-exporting from the HF dataset (`princeton-nlp/SWE-bench_Verified`),
no code changes needed.

## Data provenance & license

`instances.json` bundles 2 instances re-exported from
[`princeton-nlp/SWE-bench_Verified`](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified)
(SWE-bench). SWE-bench is released under the
[MIT license](https://github.com/SWE-bench/SWE-bench); the bundled instances
are redistributed under those same MIT terms. The framework code in this repo
is licensed separately under Apache-2.0 (see repo `NOTICE`).

## 0. Prerequisites

* Docker daemon (Docker Desktop on Windows works; on Linux just `docker`)
* Node ≥ 20 + `@earendil-works/pi-coding-agent` (pi SDK)
* `~/.pi/agent/auth.json` with a `deepseek` key (already configured here)
* The `deepseek-v4-flash` model in `~/.pi/agent/models-store.json`

`container.py` auto-detects the docker binary (`AGENTEVAL_DOCKER`
overrides; on WSL it finds Docker Desktop's `docker.exe`).

## 1. Score the bundled gold patches (harness self-check)

```bash
python evaluate_predictions.py --predictions gold --run-root run/gold
# builds/pulls the 2 instance images (one-time), then grades
# expected: both resolved=True (gold patches must pass their own tests)
```

## 2. Provide agent artifacts (runtime is outside this repo)

The agent runtime is NOT part of this project (see docs/AGENT_CONTRACT.md).
Produce a `predictions.json` however you run your agent:

```json
{ "sympy__sympy-24443": { "model_patch": "diff --git a/..." } }
```

## 3. Score the agent's patches

```bash
python evaluate_predictions.py --predictions predictions.json --run-root run/pi
```

Outputs (AgentEval standard):

```
run/pi/
├── summary.json            # per-skill means + case scores
├── leaderboard.csv / LEADERBOARD.md
└── evidence/<case_id>.json # auditable evidence tree:
                            #   plan → patch_applies (git apply --check)
                            #        → test_resolution (F2P/P2P pytest results)
                            #        → patch_quality (LLM rubric, diagnostic)
```

## Skills

| skill | role | kind | what it measures | weight |
| --- | --- | --- | --- | --- |
| `patch_applies` | observation | rule | `git apply --check` | 0.0 |
| `test_resolution` | core | rule (docker) | F2P pass + P2P no regression → **resolved** | 1.0 |
| `patch_quality` | diagnostic | **LLM rubric** | 10-question fine-grained code review | 0.0 |

### `patch_quality` — variance-controlled LLM rubric

Designed after HarnessEval-W's paper to make judge scores stable and
auditable:

1. **analyze/verify separation** — stage 1 reads *only the issue* and
   extracts expected behavior + success criteria; stage 2 scores the patch
   against those criteria. The judge cannot retro-fit the standard to the
   patch.
2. **Fine-grained discrete questions** — 10 narrow questions (root cause,
   localization, minimality, edge cases, readability, style, regression
   risk, test alignment, clarity, judgeable), each scored on the discrete
   set {0, 0.25, 0.5, 0.75, 1} with per-anchor definitions — no free-form
   0-1 sliders.
3. **Mandatory verbatim evidence** — every question must quote exact patch
   text; `parse` rejects fabricated quotes (whitespace/diff-prefix tolerant
   substring check), recording them in `fabricated_evidence_rejected`.
4. **judgeable gate** — thin evidence caps the score at 0.5.

The gold patch is never shown to the judge (anti-leakage). Reasoning is
disabled via `extra_body` (fast + cheap). Judge config:

```bash
# default: deepseek-v4-flash, key from ~/.pi/agent/auth.json
# override for a local vLLM judge:
AGENTEVAL_JUDGE_BASE_URL=http://localhost:8000/v1 \
AGENTEVAL_JUDGE_MODEL=Qwen/Qwen2.5-72B-Instruct \
python evaluate_predictions.py --predictions predictions.json --run-root run/pi
```

## Container design (kept from SWE-bench)

* **Base image** `sweagent/swe-eval:latest` pulled from Docker Hub.
* **Instance images** `sweb.eval.x86_64.<instance_id>:latest` built once:
  `git clone --filter=blob:none <repo>` → checkout `base_commit` → apply
  `test_patch` → `pip install -e .` → `pip install pytest`.
* **Scoring**: `docker run --rm -i` → patch via **stdin** (no bind-mount
  path issues across Windows/WSL/Linux) → `git apply --check` + `git apply`
  → `pytest <F2P> <P2P>` → parse PASSED/FAILED.
* **Verdict**: resolved ⟺ every FAIL_TO_PASS passed and every
  PASS_TO_PASS still passed. If pytest never ran (`pytest_ran=False`) the
  case is NOT resolved (guards against environment mishaps masquerading
  as success).
* The agent **never enters the container** — only scoring does.

## Verified end-to-end (this machine)

| input | result |
| --- | --- |
| gold patch ×2 | resolved ✓ (2 passed each) |
| empty patch | apply_failed ✗ |
| unrelated patch | not resolved ✗ |
| code-breaking patch | fail with correct F2P failure ✓ |
| **pi + deepseek-v4-flash** on `sympy__sympy-24443` | **resolved ✓ (2 passed)** |
| gold patch quality (v1, 5 dims) | 0.88 |
| gold patch quality (v2, 10-question rubric) | 0.85-0.88 |
| pi patch quality (v2, 10-question rubric) | **0.725-0.775, std ≈ 0.01 over 3 runs** |

> Judge-variance control: the v1 rubric (5 broad 0-1 sliders) showed
> run-to-run std ≈ 0.05-0.07; the v2 rubric (analyze/verify separation +
> 10 discrete questions with anchors + verbatim evidence) brings it to
> **std ≈ 0.01** (0.725/0.75/0.775). Fabricated evidence quotes are
> rejected and recorded in `fabricated_evidence_rejected` — the audit
> trail shows exactly which quotes were trusted.

## Cache behavior

AgentEval's digest cache keys results by (skill impl, case, output), so:
* re-running the same predictions never re-runs docker (instant);
* changing a skill's code invalidates its results automatically;
* `run/gold` and `run/pi` are separate runs but share the instance images.

## Notes / gotchas

* **Patch trailing newline**: `git diff` output must be kept byte-for-byte
  (a `splitlines()`+`join()` roundtrip drops the final `\n` and `git apply`
  fails with "corrupt patch"). `container.py` defensively re-appends it.
* **Windows/WSL**: bind-mounting a WSL path into Docker Desktop creates a
  *directory* — patches are streamed via stdin instead.
* `work/` (repo checkouts) and `run/` are gitignored.
