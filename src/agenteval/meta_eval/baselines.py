"""Explicit baseline mode wrappers used by meta-evaluation experiments.

The wrappers do not alter the production AgentEval path. They make the
comparison contract explicit; each caller supplies the actual judge function
for its environment.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .perturbations import EvidenceSnapshot
from .runner import MetaCase

JudgeFn = Callable[[MetaCase, EvidenceSnapshot], Mapping[str, Any]]


def agentic_evidence_judge(judge: JudgeFn) -> JudgeFn:
    """Current autonomous EvidenceProvider-backed Judge."""
    return judge


def static_retrieval_judge(judge: JudgeFn, selector: Callable[[EvidenceSnapshot], EvidenceSnapshot]) -> JudgeFn:
    """Run a Judge against a fixed, pre-selected snapshot.

    The supplied judge must not expose additional retrieval tools. This module
    only defines the experiment boundary; it cannot enforce the external
    service's tool policy.
    """
    def run(case: MetaCase, snapshot: EvidenceSnapshot) -> Mapping[str, Any]:
        return judge(case, selector(snapshot))
    return run


def full_trace_judge(judge: JudgeFn) -> JudgeFn:
    """Full-trace baseline boundary.

    The caller is responsible for constructing a prompt/input that contains
    the full trace. No full-trace prompt is silently synthesized here.
    """
    return judge
