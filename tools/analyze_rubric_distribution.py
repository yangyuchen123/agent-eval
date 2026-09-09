#!/usr/bin/env python3
"""Run the reusable rubric distribution audit on a classification JSONL."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenteval.rubric_distribution import load_jsonl, write_outputs

p = argparse.ArgumentParser()
p.add_argument("--classification", required=True)
p.add_argument("--out", required=True)
p.add_argument("--top-n", type=int, default=10)
args = p.parse_args()
paths = write_outputs(load_jsonl(args.classification), args.out, top_n=args.top_n)
for k, path in paths.items():
    print(f"{k}: {path}")
