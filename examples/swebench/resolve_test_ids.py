"""Resolve SWE-bench_Verified short test names to full pytest IDs.

The HF parquet stores FAIL_TO_PASS / PASS_TO_PASS as short names (e.g.
``test_contains_basic``). pytest needs full IDs like
``sympy/sets/tests/test_contains.py::test_contains_basic``. Resolution:

1. if the name already contains ``::`` and a file path, keep it;
2. else locate ``def <name>`` in the checked-out repo (work/<instance_id>)
   with grep and prepend the file path.

Run after repos are cloned (``run_pi_agent.py --keep-repo`` or a manual
clone at base_commit). This is a one-time data-prep tool; instances.json
is the committed source of truth afterwards.

Usage:
    python resolve_test_ids.py [--instances instances.json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from cases import load_instances  # noqa: E402


def resolve(instance: dict, repo_root: Path) -> tuple[list[str], list[str]]:
    """Return (resolved F2P, resolved P2P)."""
    out = []
    for name in list(instance.get("FAIL_TO_PASS") or []) + \
                list(instance.get("PASS_TO_PASS") or []):
        full = _resolve_one(name, instance, repo_root)
        if full:
            out.append(full)
    f2p = out[:len(instance.get("FAIL_TO_PASS") or [])]
    p2p = out[len(f2p):]
    return f2p, p2p


def _resolve_one(name: str, instance: dict, repo_root: Path) -> str | None:
    # filter dataset noise: pytest progress junk, empty names
    if not name or name.startswith("[") or "]" in name and not name.endswith("]"):
        if not name or "::" not in name:
            return None
    # already full: file.py::... where the file part is a repo-relative path
    if "::" in name and name.split("::")[0].endswith(".py") and "/" in name:
        return name
    # strip parametrize suffix for the grep lookup
    bare = name.split("[")[0].rsplit("::", 1)[-1]
    if not bare:
        print(f"  !! empty test name {name!r} (dropping)", file=sys.stderr)
        return None
    proc = subprocess.run(
        ["grep", "-rl", f"def {bare}", str(repo_root)],
        capture_output=True, text=True)
    if proc.returncode == 0:
        rel = Path(proc.stdout.splitlines()[0]).relative_to(repo_root)
        return f"{rel.as_posix()}::{bare}"
    print(f"  !! cannot locate {name!r} in {repo_root.name} "
          f"(keeping short name)", file=sys.stderr)
    return name


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--instances", default=str(ROOT / "instances.json"))
    args = p.parse_args()

    path = Path(args.instances)
    data = json.loads(path.read_text(encoding="utf-8"))
    for inst in data["instances"]:
        repo_root = ROOT / "work" / inst["instance_id"]
        if not (repo_root / ".git").is_dir():
            print(f"skip {inst['instance_id']} (repo not cloned)")
            continue
        f2p, p2p = resolve(inst, repo_root)
        if f2p != inst.get("FAIL_TO_PASS") or p2p != inst.get("PASS_TO_PASS"):
            print(f"{inst['instance_id']}:")
            print(f"  F2P -> {f2p}")
            print(f"  P2P -> {p2p}")
            inst["FAIL_TO_PASS"] = f2p
            inst["PASS_TO_PASS"] = p2p
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                    encoding="utf-8")
    print("written", path)


if __name__ == "__main__":
    main()
