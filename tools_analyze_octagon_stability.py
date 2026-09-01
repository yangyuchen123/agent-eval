#!/usr/bin/env python3
"""Compatibility wrapper; canonical script is in archive/2026-08-31/project-history/scripts/tools_analyze_octagon_stability.py."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parent / "archive/2026-08-31/project-history/scripts/tools_analyze_octagon_stability.py"), run_name="__main__")
