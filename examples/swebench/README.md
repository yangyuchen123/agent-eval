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

## 2. Run the real agent (pi + deepseek-v4-flash)

```bash
python run_pi_agent.py                        # all instances
python run_pi_agent.py --instance sympy__sympy-24443
# clones the repo, checks out base_commit, runs pi, saves predictions.json
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
