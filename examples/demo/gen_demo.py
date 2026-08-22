"""Generate demo case manifest + fake agent outputs.

    python examples/demo/gen_demo.py
    # writes examples/demo/data/cases.json and outputs_good.json / outputs_bad.json
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

ROOT = Path(__file__).resolve().parent / "data"


def main() -> None:
    rng = random.Random(7)
    cases = []
    for i in range(6):
        a, b = rng.randint(1, 99), rng.randint(1, 99)
        op = rng.choice(["+", "-", "*"])
        answer = {"+": a + b, "-": a - b, "*": a * b}[op]
        cases.append({
            "case_id": f"arith_{i:03d}",
            "task": f"计算 {a} {op} {b} = ?",
            "expected": {"answer": str(answer)},
            "metadata": {"op": op},
        })
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "cases.json").write_text(
        json.dumps({"cases": cases}, ensure_ascii=False, indent=2), encoding="utf-8")

    good = {c["case_id"]: f"ANSWER: {c['expected']['answer']}" for c in cases}
    bad = {c["case_id"]: f"我不知道,可能是 {int(c['expected']['answer']) + 1}"
           for c in cases}
    for name, data in (("outputs_good.json", good), ("outputs_bad.json", bad)):
        (ROOT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    print(f"demo data written to {ROOT}")


if __name__ == "__main__":
    main()
