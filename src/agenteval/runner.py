"""Evaluation runner: plan → execute skills → collect evidence tree.

Pipeline per case:
    router.route(case)            # cached by (router, case) input digest
      → for each selected skill:
            skill.evaluate(...)   # cached by (skill def, case, output, params)
      → CaseEvidence (plan + per-skill results) written as JSON

All results are keyed by content digests, so re-running with unchanged
inputs costs nothing (LLM judge calls are skipped on cache hits).
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .history import EvalRecord, HistoryStore, record_from_evidence
from .io import atomic_write_json, read_json, value_digest
from .manifest import build_manifest, write_manifest
from .planner import Router
from .protocols import Case, CaseEvidence, Plan, SkillResult
from .skills.registry import SkillRegistry

CACHE_SCHEMA = "agenteval.cache.v1"


@dataclass
class RunConfig:
    router: Router
    registry: SkillRegistry
    run_root: Path
    plan_root: Path | None = None       # shared plan cache (case-level routing)
    workers: int = 1                    # >1 requires thread-safe skills
    refresh: bool = False
    run_id: str = ""                   # history grouping key (auto if empty)
    model_id: str = "unknown"          # recorded in history
    history_path: Path | None = None    # default: <run_root>/history.jsonl
    agent_name: str = "unknown"        # recorded in run manifest
    agent_version: str = ""
    benchmarks: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        self.run_root = Path(self.run_root)
        self.plan_root = Path(self.plan_root) if self.plan_root else None
        if not self.run_id:
            from .history import new_run_id
            self.run_id = new_run_id()
        if self.history_path is None:
            self.history_path = self.run_root / "history.jsonl"


@dataclass
class RunReport:
    evidence: dict[str, CaseEvidence] = field(default_factory=dict)
    cache_stats: dict[str, int] = field(default_factory=dict)
    failures: list[dict[str, Any]] = field(default_factory=list)


# ------------------------------------------------------------ plans ------

def _plan_digest(case: Case, router: Router) -> str:
    # include the router's implementation fingerprint so changing the
    # routing logic (e.g. adding a diagnostic skill) invalidates plan caches
    impl_digest = None
    func = getattr(router, "func", None)
    code = getattr(func, "__code__", None)
    if code is not None:
        impl_digest = hashlib.sha256(code.co_code).hexdigest()[:12]
    return value_digest({"router": type(router).__name__,
                         "router_impl": impl_digest,
                         "case": case.to_dict()})


def plan_path(config: RunConfig, case: Case) -> Path | None:
    if config.plan_root is None:
        return None
    return config.plan_root / f"{case.case_id}.plan.json"


def load_plan(config: RunConfig, case: Case) -> Plan | None:
    path = plan_path(config, case)
    if path is None or not path.is_file() or config.refresh:
        return None
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    if (data.get("schema_version") != "agenteval.skill_plan.v1"
            or data.get("case_id") != case.case_id
            or data.get("input_digest") != _plan_digest(case, config.router)):
        return None
    return Plan(
        case_id=case.case_id,
        selected_skills=tuple(data["selected_skills"]),
        skipped_skills=tuple(data["skipped_skills"]),
        routing_mode=data.get("routing_mode", "rule"),
        planner=data.get("planner", {}),
    )


def save_plan(config: RunConfig, case: Case, plan: Plan) -> None:
    path = plan_path(config, case)
    if path is None:
        return
    data = plan.to_dict()
    data["input_digest"] = _plan_digest(case, config.router)
    atomic_write_json(path, data)


# --------------------------------------------------------- results -------

def _result_cache_path(config: RunConfig, case: Case, skill_id: str,
                       digest: str) -> Path:
    return (config.run_root / "metric_cache" / "skills" / skill_id
            / f"{case.case_id}.{digest}.json")


def _skill_impl_digest(skill: Any) -> str:
    """Fingerprint of a skill's executable code (evaluate/messages/parse).

    This makes cached results invalidate when a skill's implementation
    changes, even if `definition_version` was not bumped."""
    methods = ["evaluate", "messages", "parse"]
    h = hashlib.sha256()
    for name in methods:
        fn = getattr(skill, name, None)
        code = getattr(fn, "__code__", None)
        if code is not None:
            h.update(name.encode())
            h.update(code.co_code)
    return h.hexdigest()[:12]


def _result_input_digest(config: RunConfig, case: Case, skill_id: str,
                         output: str, parameters: Mapping[str, Any]) -> str:
    skill = config.registry.get(skill_id)
    identity = {
        "skill_id": skill_id,
        "definition_version": getattr(skill, "definition_version", "agenteval.skill.base"),
        "impl_digest": _skill_impl_digest(skill),
        "backend_digest": getattr(getattr(skill, "backend", None), "config_digest", None),
        "case": case.to_dict(),
        "output": output,
        "parameters": parameters,
    }
    return value_digest(identity)


def load_result(path: Path, expected_digest: str) -> SkillResult | None:
    if not path.is_file():
        return None
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    if (data.get("schema_version") != "agenteval.skill_result.v1"
            or data.get("input_digest") != expected_digest):
        return None
    return SkillResult(
        skill_id=data["skill_id"],
        status=data["status"],
        score=data.get("score"),
        subscores=data.get("subscores", {}),
        reasons=data.get("reasons", {}),
        evidence=data.get("evidence", {}),
        diagnostics=data.get("diagnostics", {}),
    )


def save_result(path: Path, result: SkillResult, input_digest: str) -> None:
    data = result.to_dict()
    data["input_digest"] = input_digest
    atomic_write_json(path, data)


# ------------------------------------------------------------ runner -----

def _run_skill(config: RunConfig, case: Case, output: str,
               item: dict[str, Any]) -> tuple[str, SkillResult, bool]:
    skill_id = item["skill_id"]
    digest = _result_input_digest(config, case, skill_id, output,
                                  item.get("parameters", {}))
    path = _result_cache_path(config, case, skill_id, digest)
    cached = load_result(path, digest)
    if cached is not None:
        return skill_id, cached, True
    skill = config.registry.get(skill_id)
    skill.prepare(case, output)
    result = skill.evaluate(case, output)
    save_result(path, result, digest)
    return skill_id, result, False


def evaluate_one(config: RunConfig, case: Case, output: str) -> tuple[CaseEvidence, int]:
    plan = load_plan(config, case)
    if plan is None:
        plan = config.router.route(case, config.registry.catalog())
        save_plan(config, case, plan)

    results: dict[str, SkillResult] = {}
    hits = 0
    if config.workers > 1:
        with ThreadPoolExecutor(max_workers=config.workers) as pool:
            futures = {pool.submit(_run_skill, config, case, output, item):
                       item for item in plan.selected_skills}
            for future in as_completed(futures):
                try:
                    skill_id, result, hit = future.result()
                except Exception as exc:  # noqa: BLE001
                    item = futures[future]
                    results[item["skill_id"]] = SkillResult(
                        skill_id=item["skill_id"], status="error", score=None,
                        diagnostics={"error": repr(exc)})
                    continue
                results[skill_id] = result
                hits += hit
    else:
        for item in plan.selected_skills:
            try:
                skill_id, result, hit = _run_skill(config, case, output, item)
            except Exception as exc:  # noqa: BLE001 - one skill failing
                skill_id = item["skill_id"]
                result = SkillResult(skill_id=skill_id, status="error",
                                     score=None, diagnostics={"error": repr(exc)})
                hit = False
            results[skill_id] = result
            hits += hit

    evidence = CaseEvidence(
        case_id=case.case_id,
        case=case.to_dict(),
        output=output,
        plan=plan,
        skill_results=results,
    )
    return evidence, hits


def run_eval(
    config: RunConfig,
    cases: Iterable[Case],
    outputs: Mapping[str, str],
    *,
    on_case: Callable[[str], None] | None = None,
) -> RunReport:
    report = RunReport()
    history: list[EvalRecord] = []
    for case in cases:
        output = outputs.get(case.case_id, "")
        if not output and case.case_id not in outputs:
            report.failures.append({"case_id": case.case_id,
                                    "error": "no agent output provided"})
            continue
        try:
            evidence, hits = evaluate_one(config, case, output)
        except Exception as exc:  # noqa: BLE001
            report.failures.append({"case_id": case.case_id, "error": repr(exc)})
            continue
        report.evidence[case.case_id] = evidence
        report.cache_stats.setdefault("plan_hits", 0)
        report.cache_stats["skill_hits"] = report.cache_stats.get("skill_hits", 0) + hits
        history.extend(record_from_evidence(
            evidence, run_id=config.run_id, model_id=config.model_id))
        if on_case is not None:
            on_case(case.case_id)

    if history:
        store = HistoryStore(config.history_path)
        store.append(history)
        report.cache_stats["history_records"] = len(history)
        # run-level manifest: under what conditions was this report produced?
        manifest = build_manifest(
            config.run_id, HistoryStore(config.history_path),
            agent_name=config.agent_name, agent_version=config.agent_version,
            benchmarks=config.benchmarks)
        write_manifest(config.run_root, manifest)
        report.cache_stats["manifest_written"] = 1
    return report


def write_evidence(run_root: Path, report: RunReport) -> Path:
    root = run_root / "evidence"
    for case_id, evidence in report.evidence.items():
        atomic_write_json(root / f"{case_id}.json", evidence.to_dict())
    return root
