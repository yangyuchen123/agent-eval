"""Run the pi agent on the SWE-bench instances and collect patches.

Pipeline per instance:
  1. clone the repo (--filter=blob:none) into work/<instance_id>
  2. checkout base_commit
  3. write problem_statement to a file
  4. node run_pi_agent.mjs <workdir> <problem_file>   (pi + deepseek-v4-flash)
  5. git diff → predictions.json: {instance_id: {model_patch: "..."}}

The agent runs on the HOST — it never enters the SWE-bench containers.
Containers are only used later for scoring (see skills.py / container.py).

Usage:
    python run_pi_agent.py                          # all instances
    python run_pi_agent.py --instance sympy__sympy-24443
    python run_pi_agent.py --keep-repo               # reuse existing workdirs
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))                       # examples/swebench
sys.path.insert(0, str(ROOT.parents[1] / "src"))    # framework

from cases import load_instances

ROOT = Path(__file__).resolve().parent
WORK_DIR = ROOT / "work"
OUT_PREDICTIONS = ROOT / "predictions.json"
NODE = os.environ.get("NODE_BIN", "node")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="drive pi agent on SWE-bench instances")
    p.add_argument("--instance", type=str, default=None,
                   help="only run this instance_id")
    p.add_argument("--keep-repo", action="store_true",
                   help="reuse an existing repo checkout (do not re-clone)")
    p.add_argument("--collect-only", action="store_true",
                   help="skip the agent; collect diffs from existing workdirs "
                        "(merge into predictions.json)")
    return p.parse_args()


def prepare_repo(inst: dict, keep: bool) -> Path:
    workdir = WORK_DIR / inst["instance_id"]
    if workdir.exists() and keep:
        print(f"[repo] reuse {workdir}")
        return workdir
    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    repo_url = f"https://github.com/{inst['repo']}.git"
    print(f"[repo] cloning {repo_url} (filter=blob:none) ...")
    subprocess.run(["git", "clone", "--filter=blob:none", repo_url, str(workdir)],
                   check=True, capture_output=True)
    print(f"[repo] checkout {inst['base_commit'][:12]}")
    subprocess.run(["git", "-C", str(workdir), "checkout", inst["base_commit"]],
                   check=True, capture_output=True)
    return workdir


def run_agent(workdir: Path, inst: dict) -> str:
    problem_file = workdir / "problem_statement.txt"
    problem_file.write_text(inst["problem_statement"], encoding="utf-8")
    print(f"[pi] solving {inst['instance_id']} ...")
    env = dict(os.environ)
    env["NODE_PATH"] = env.get("NODE_PATH", "") + os.pathsep + (
        "/home/administrator/.nvm/versions/node/v24.19.0/lib/node_modules")
    proc = subprocess.run(
        [NODE, str(ROOT / "run_pi_agent.mjs"), str(workdir), str(problem_file)],
        env=env)
    if proc.returncode != 0:
        print(f"[pi] agent exited {proc.returncode} for {inst['instance_id']}")
        return ""
    # collect diff — keep the raw output byte-for-byte (splitlines/join
    # would drop the trailing newline and corrupt the patch)
    diff = subprocess.run(
        ["git", "-C", str(workdir), "diff"],
        capture_output=True, text=True).stdout
    return diff


def main() -> None:
    args = parse_args()
    instances = load_instances()
    if args.instance:
        instances = [i for i in instances if i["instance_id"] == args.instance]
        if not instances:
            raise SystemExit(f"unknown instance: {args.instance}")

    # merge with existing predictions (each run may target a subset)
    predictions: dict[str, dict] = {}
    if OUT_PREDICTIONS.exists():
        try:
            predictions = json.loads(OUT_PREDICTIONS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            predictions = {}

    for inst in instances:
        if args.collect_only:
            workdir = WORK_DIR / inst["instance_id"]
            diff = subprocess.run(
                ["git", "-C", str(workdir), "diff"],
                capture_output=True, text=True).stdout
            predictions[inst["instance_id"]] = {"model_patch": diff}
            print(f"[collect] {inst['instance_id']}: {len(diff)} bytes")
            continue
        workdir = prepare_repo(inst, args.keep_repo)
        patch = run_agent(workdir, inst)
        predictions[inst["instance_id"]] = {"model_patch": patch}
        print(f"[pi] {inst['instance_id']}: patch {len(patch)} bytes")

    OUT_PREDICTIONS.write_text(
        json.dumps(predictions, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[done] predictions → {OUT_PREDICTIONS}")


if __name__ == "__main__":
    main()
