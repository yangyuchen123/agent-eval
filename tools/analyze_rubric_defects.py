#!/usr/bin/env python3
"""Run the reusable rubric defect attribution analysis."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenteval.rubric_defects import analyze, load_jsonl, render_report

p = argparse.ArgumentParser()
p.add_argument("--classification", required=True)
p.add_argument("--generated-a")
p.add_argument("--generated-c")
p.add_argument("--generated-d")
p.add_argument("--stability")
p.add_argument("--out", required=True)
a = p.parse_args()
generated = {k: v for k, v in {"A": a.generated_a, "C": a.generated_c, "D": a.generated_d}.items() if v}
result = analyze(load_jsonl(a.classification), generated_files=generated, stability_file=a.stability)
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
(out / "rubric_defect_attribution.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(out / "rubric_defect_attribution.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in result["findings"]) + "\n", encoding="utf-8")
(out / "RUBRIC_DEFECT_ATTRIBUTION_REPORT.md").write_text(render_report(result) + "\n", encoding="utf-8")
print(out / "rubric_defect_attribution.json")
print(out / "rubric_defect_attribution.jsonl")
print(out / "RUBRIC_DEFECT_ATTRIBUTION_REPORT.md")
