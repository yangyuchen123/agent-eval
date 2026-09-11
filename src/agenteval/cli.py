"""Command-line interface.

    agenteval eval \
        --cases manifest.json \
        --outputs outputs.json \
        --case-package examples.demo \
        --run-root run/ \
        --model-id my-agent

`--case-package` is a Python module that exposes:

    def build_registry() -> SkillRegistry: ...
    def build_router(registry) -> Router: ...

The framework never imports domain code directly — cases/skills stay
decoupled.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import score as score_mod
from .backends import LLMBackend
from .adapters import (AgentOctagonAdapter, AgentOctagonRuntimeClient, HarborAdapter,
                        score_octagon_samples)
from .analysis import (judge_rule_agreement, migration_report,
                       render_diagnostics, render_migration,
                       rubric_diagnostics)
from .history import HistoryStore
from .preferences import PreferenceStore
from .rubric_planner import RubricPlanner
from .planner import Router
from .protocols import Case
from .judge import build_judge_client
from .rubric_generation import (build_global_profile, build_memory, choose_queries,
                                  generator_prompt, read_jsonl, retrieve,
                                  validate_generated)
from .adapters.forge_ir import IRRubricProjectionError, project_ir_rubric_file
from .rubrics import Rubric
from .runtime_judge import score_runtime_samples
from .report import build_report, evidence_tree_markdown, write_report_artifacts
from .runner import RunConfig, run_eval, write_evidence
from .skills.registry import SkillRegistry


def _write_cache_stats(run_root: str | Path, report: Any) -> Path:
    target = Path(run_root) / "cache_stats.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"schema_version":"agenteval.cache_stats.v1", **dict(report.cache_stats)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _load_case_package(name: str) -> Any:
    module = importlib.import_module(name)
    for fn in ("build_registry", "build_router"):
        if not hasattr(module, fn):
            raise SystemExit(
                f"case package {name!r} must define {fn}()")
    return module


def _load_cases(path: Path) -> list[Case]:
    data = json.loads(path.read_text(encoding="utf-8"))
    cases = data.get("cases") if isinstance(data, dict) else data
    if not isinstance(cases, list):
        raise SystemExit(f"manifest must contain a 'cases' array: {path}")
    parsed = [Case.from_dict(item) for item in cases]
    ids = [case.case_id for case in parsed]
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise SystemExit(f"cases contain duplicate case_id(s): {duplicates}")
    return parsed


def _load_outputs(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and all(isinstance(v, str) for v in data.values()):
        return data
    # support {"outputs": {"case_id": "text"}}
    if isinstance(data, dict) and isinstance(data.get("outputs"), dict):
        return {str(k): str(v) for k, v in data["outputs"].items()}
    raise SystemExit(f"outputs must be {{case_id: output_text}}: {path}")


def cmd_eval(args: argparse.Namespace) -> int:
    # Validate external inputs before importing the case package. This keeps
    # malformed/empty jobs from being reported as package failures.
    cases = _load_cases(Path(args.cases))
    outputs = _load_outputs(Path(args.outputs))
    if not cases:
        raise SystemExit("evaluation manifest contains zero cases")
    case_ids = {case.case_id for case in cases}
    output_ids = set(outputs)
    missing_outputs = sorted(case_ids - output_ids)
    extra_outputs = sorted(output_ids - case_ids)
    if missing_outputs or extra_outputs:
        details = []
        if missing_outputs:
            details.append(f"missing outputs: {missing_outputs}")
        if extra_outputs:
            details.append(f"unknown output ids: {extra_outputs}")
        raise SystemExit("cases/outputs id mismatch; " + "; ".join(details))
    pkg = _load_case_package(args.case_package)
    registry: SkillRegistry = pkg.build_registry()
    router: Router = pkg.build_router(registry)
    print(f"[agenteval] {len(cases)} cases, {len(registry)} skills, "
          f"router={type(router).__name__}")

    run_root = Path(args.run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    plan_root = Path(args.plan_root) if args.plan_root else None
    if plan_root:
        plan_root.mkdir(parents=True, exist_ok=True)
    config = RunConfig(router=router, registry=registry, run_root=run_root,
                       plan_root=plan_root, model_id=args.model_id,
                       workers=args.workers,
                       refresh=args.refresh,
                       agent_name=args.agent_name,
                       agent_version=args.agent_version,
                       benchmarks=tuple(args.benchmark))

    report = run_eval(config, cases, outputs,
                      on_case=lambda cid: print(f"  ✓ {cid}"))
    evidence_root = write_evidence(run_root, report)
    _write_cache_stats(run_root, report)
    print(f"[agenteval] scored {len(report.evidence)}/{len(cases)} cases, "
          f"failures={len(report.failures)}, skill_cache_hits={report.cache_stats.get('skill_hits', 0)}")
    for failure in report.failures:
        print(f"  ✗ {failure['case_id']}: {failure['error']}")

    # aggregation
    weights = getattr(pkg, "SKILL_WEIGHTS", None) or {}
    aggregator = getattr(pkg, "AGGREGATE", score_mod.weighted_case_score)
    case_scores = {
        cid: aggregator(evidence, weights)
        for cid, evidence in report.evidence.items()
    }
    summary = score_mod.dataset_summary(list(report.evidence.values()),
                                        case_scores, weights)
    final = build_report(list(report.evidence.values()), case_scores, summary,
                         model_id=args.model_id,
                         aggregator_name=getattr(aggregator, "__name__", "custom"))
    artifacts = write_report_artifacts(run_root, final)
    for kind, path in artifacts.items():
        print(f"  [{kind}] {path}")

    if report.failures:
        return 1

    if args.verbose:
        for cid, evidence in report.evidence.items():
            print(evidence_tree_markdown(evidence))
    return 0


def _octagon_judge_config(args: argparse.Namespace):
    model = getattr(args, "judge_model", None)
    wants_generated = bool(getattr(args, "generate_rubric", False) or getattr(args, "meta_rubric", None) or getattr(args, "preference_examples", None))
    if not model:
        if wants_generated:
            raise SystemExit("--judge-model is required when generated case rubrics are enabled")
        return None, "", None, None
    base_url = getattr(args, "judge_base_url", None)
    if not base_url:
        raise SystemExit("--judge-base-url is required when --judge-model is set")
    rubric = ""
    rubric_file = getattr(args, "judge_rubric_file", None)
    if rubric_file:
        rubric = Path(rubric_file).read_text(encoding="utf-8")
    backend = LLMBackend(
        base_url=base_url,
        model=model,
        api_key=getattr(args, "judge_api_key", None),
        wire_api=getattr(args, "judge_wire_api", "chat"),
        temperature=0.0,
        json_mode=True,
        extra_body={"reasoning": {"effort": args.judge_reasoning_effort}},
    )
    planner = None
    meta = None
    if wants_generated:
        meta_path = getattr(args, "meta_rubric", None)
        if meta_path:
            meta = PreferenceStore.load_meta(meta_path)
        else:
            examples_path = getattr(args, "preference_examples", None)
            if not examples_path:
                raise SystemExit("generated case rubrics require --meta-rubric or --preference-examples")
            examples = PreferenceStore(examples_path).load()
            planner = RubricPlanner(backend)
            meta = planner.infer_meta_rubric(examples, rubric_id=getattr(args, "meta_rubric_id", "human_preference"))
        planner = planner or RubricPlanner(backend)
        rubric = ""  # the generated, case-specific rubric is authoritative
    return backend, rubric, planner, meta


def cmd_octagon_eval(args: argparse.Namespace) -> int:
    """Compatibility: start one AgentOctagon run, then score its attempts."""
    print(
        "[agenteval] warning: octagon-eval is a compatibility command. "
        "Starting runs belongs to eval-system; prefer octagon-score on "
        "persisted attempts.",
        file=sys.stderr,
    )
    agents = args.agent or ["blade-agent"]
    models = None
    if args.models_json:
        try:
            parsed = json.loads(args.models_json)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--models-json must be a JSON object: {exc}") from exc
        if not isinstance(parsed, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in parsed.items()):
            raise SystemExit("--models-json must be a JSON object mapping agent to model")
        models = parsed
    client = AgentOctagonRuntimeClient(args.base_url, request_timeout=args.request_timeout)
    created = client.create_run(
        env_name=args.env, task_id=args.task_id, agents=agents, model=args.model,
        models=models, compare_mode=args.compare_mode,
        timeout_seconds=args.timeout_seconds,
    )
    print(f"[agenteval] started AgentOctagon run {created.run_id} ({args.env}/{args.task_id})")
    finished = client.wait_run(created.run_id, timeout=args.wait_timeout, poll_interval=args.poll_interval)
    print(f"[agenteval] AgentOctagon run {finished.run_id} status={finished.status}")

    adapter = AgentOctagonAdapter(
        args.data_root, run_id=finished.run_id, include_failed=args.include_failed
    )
    samples = adapter.iter_samples()
    if not samples:
        raise SystemExit(
            f"run {finished.run_id} finished but no attempts were found under {args.data_root}"
        )
    judge_backend, judge_rubric, rubric_planner, meta_rubric = _octagon_judge_config(args)
    report, artifacts = score_octagon_samples(
        samples, env_root=args.env_root, run_root=args.run_root,
        model_id=args.model or "agent-octagon", plan_root=args.plan_root,
        judge_backend=judge_backend, judge_rubric=judge_rubric,
        deterministic_weight=args.deterministic_weight, judge_weight=args.judge_weight,
        judge_only=args.judge_only,
        rubric_planner=rubric_planner, meta_rubric=meta_rubric,
    )
    print(f"[agenteval] octagon samples={len(samples)}, scored={len(report.evidence)}, failures={len(report.failures)}")
    for kind, path in artifacts.items():
        print(f"  [{kind}] {path}")
    return 1 if report.failures else 0


def cmd_octagon_score(args: argparse.Namespace) -> int:
    """Re-score existing AgentOctagon attempts through their env scorer."""
    adapter = AgentOctagonAdapter(
        args.data_root,
        attempt_ids=args.attempt_id or None,
        run_id=args.run_id,
        include_failed=args.include_failed,
    )
    samples = adapter.iter_samples()
    if args.env:
        samples = [
            sample for sample in samples
            if sample.environment.get("name") == args.env
        ]
    if not samples:
        raise SystemExit("no matching AgentOctagon attempts found")
    judge_backend, judge_rubric, rubric_planner, meta_rubric = _octagon_judge_config(args)
    report, artifacts = score_octagon_samples(
        samples,
        env_root=args.env_root,
        run_root=args.run_root,
        model_id=args.model_id,
        plan_root=args.plan_root,
        judge_backend=judge_backend, judge_rubric=judge_rubric,
        deterministic_weight=args.deterministic_weight, judge_weight=args.judge_weight,
        judge_only=args.judge_only,
        rubric_planner=rubric_planner, meta_rubric=meta_rubric,
    )
    print(f"[agenteval] octagon samples={len(samples)}, scored={len(report.evidence)}, failures={len(report.failures)}")
    for kind, path in artifacts.items():
        print(f"  [{kind}] {path}")
    return 1 if report.failures else 0



def cmd_harbor_score(args: argparse.Namespace) -> int:
    """Score persisted Harbor trials through the independent Judge service."""
    samples = HarborAdapter(args.trial_root, include_failed=args.include_failed).iter_samples()
    if not samples:
        raise SystemExit("no matching Harbor trials found")
    rubric = Rubric.from_dict(json.loads(Path(args.rubric).read_text(encoding="utf-8")))
    backend = (getattr(args, "judge_backend", None) or "http").strip().lower()
    try:
        client = build_judge_client(
            backend,
            judge_service_url=args.judge_service_url,
            judge_endpoint=args.judge_endpoint,
            judge_api_key=args.judge_api_key,
            judge_timeout=args.judge_timeout,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if backend == "stub":
        print("[agenteval] WARNING: --judge-backend stub is deterministic transport only; scores are not semantic judgments")
    report, artifacts = score_runtime_samples(
        samples, client=client, rubric=rubric, run_root=args.run_root,
        model_id=args.model_id, plan_root=args.plan_root,
        judge_backend=backend,
    )
    print(f"[agenteval] harbor samples={len(samples)}, scored={len(report.evidence)}, failures={len(report.failures)}, judge_backend={backend}")
    for kind, path in artifacts.items():
        print(f"  [{kind}] {path}")
    return 1 if report.failures else 0

def _planner_backend(args: argparse.Namespace) -> LLMBackend:
    if not args.base_url or not args.model:
        raise SystemExit("--base-url and --model are required")
    return LLMBackend(
        base_url=args.base_url, model=args.model, api_key=args.api_key,
        wire_api=args.wire_api, json_mode=True, temperature=0.0,
        extra_body={"reasoning": {"effort": args.reasoning_effort}},
    )


def cmd_project_ir_rubric(args: argparse.Namespace) -> int:
    try:
        rubric, target = project_ir_rubric_file(args.ir, args.output)
    except (OSError, json.JSONDecodeError, IRRubricProjectionError, ValueError) as exc:
        raise SystemExit(f"IR rubric projection failed: {exc}") from exc
    print(f"[agenteval] projected {rubric.rubric_id}@{rubric.version} ({len(rubric.questions)} questions)")
    if target is not None:
        print(f"  [rubric] {target}")
    return 0


def cmd_rubric_induce(args: argparse.Namespace) -> int:
    examples = PreferenceStore(args.examples).load()
    planner = RubricPlanner(_planner_backend(args))
    meta = planner.infer_meta_rubric(examples, rubric_id=args.rubric_id)
    PreferenceStore.save_meta(args.output, meta)
    print(f"[agenteval] inferred meta-rubric {meta.rubric_id}@{meta.version} from {len(examples)} examples")
    print(f"  [meta-rubric] {args.output}")
    return 0


def cmd_rubric_instantiate(args: argparse.Namespace) -> int:
    meta = PreferenceStore.load_meta(args.meta_rubric)
    raw = json.loads(Path(args.case).read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("case"), dict):
        raw = raw["case"]
    case = Case.from_dict(raw)
    planner = RubricPlanner(_planner_backend(args))
    rubric = planner.instantiate(meta, case, rubric_id=args.rubric_id)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(rubric.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[agenteval] instantiated case rubric {rubric.rubric_id}@{rubric.version}")
    print(f"  [rubric] {target}")
    return 0



def cmd_rubric_generation(args: argparse.Namespace) -> int:
    """Freeze RuVer human-rubric memory or create a retrieval review packet."""
    from .rubric_generation import digest

    dataset = Path(args.dataset)
    labels = Path(args.labels)
    output = Path(args.out)
    output.mkdir(parents=True, exist_ok=True)
    cases = read_jsonl(dataset)
    memory_path = output / "rubric_memory.jsonl"
    if args.phase == "memory":
        memory = build_memory(dataset, labels, args.source_root)
        memory_path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in memory) + "\n", encoding="utf-8")
        print(f"[rubric-generation] froze {len(memory)} task-level memory items: {memory_path}")
        return 0

    if args.phase == "prepare":
        if not memory_path.is_file():
            raise SystemExit(f"missing frozen memory: {memory_path}; run --phase memory first")
        memory = read_jsonl(memory_path)
        queries = choose_queries(cases, args.query_count, args.seed)
        heldout = {str(x["instance_id"]) for x in queries}
        usable_memory = [x for x in memory if str(x["task_id"]) not in heldout]
        retrieval_file = output / "retrieval_results.jsonl"
        retrieval_rows = {str(x["query_task_id"]): x for x in (read_jsonl(retrieval_file) if retrieval_file.is_file() else [])}
        if args.condition == "retrieved_human_rubric" and not heldout.issubset(set(retrieval_rows)):
            raise SystemExit("retrieved_human_rubric prepare requires retrieval results for exactly the selected query tasks")
        profile = build_global_profile(usable_memory)
        (output / "global_rubric_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rng = __import__("random").Random(args.seed)
        prompt_rows = []
        for case in queries:
            task_id = str(case["instance_id"])
            if args.condition == "retrieved_human_rubric":
                demos = []
                for item in retrieval_rows[task_id]["retrieved"]:
                    if str(item["retrieved_task_id"]) in heldout:
                        raise SystemExit(f"leakage detected in retrieved result for {task_id}")
                    found = next((m for m in usable_memory if str(m["task_id"]) == str(item["retrieved_task_id"])), None)
                    if found is None:
                        raise SystemExit(f"retrieved task missing from frozen memory: {item['retrieved_task_id']}")
                    demos.append(found)
            elif args.condition == "random_human_rubric":
                demos = rng.sample(usable_memory, min(args.top_k, len(usable_memory)))
            else:
                demos = []
            messages = generator_prompt(case, args.condition, demos, profile if args.condition == "global_profile" else None, args.generator_prompt_version)
            prompt_rows.append({"task_id": task_id, "condition": args.condition, "messages": messages, "input_digest": digest(messages), "demonstration_task_ids": [str(x["task_id"]) for x in demos], "excluded_task_ids": sorted(heldout), "generator_called": False})
        target = output / f"generator_inputs_{args.condition}.jsonl"
        target.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in prompt_rows) + "\n", encoding="utf-8")
        print(f"[rubric-generation] prepared {len(prompt_rows)} prompts: {target}")
        print("[rubric-generation] no model call was made")
        return 0

    if args.phase == "generate":
        if not memory_path.is_file():
            raise SystemExit(f"missing frozen memory: {memory_path}; run --phase memory first")
        memory = read_jsonl(memory_path)
        queries = choose_queries(cases, args.query_count, args.seed)
        heldout = {str(x["instance_id"]) for x in queries}
        usable_memory = [x for x in memory if str(x["task_id"]) not in heldout]
        retrieval_rows = {str(x["query_task_id"]): x for x in (read_jsonl(output / "retrieval_results.jsonl") if (output / "retrieval_results.jsonl").is_file() else [])}
        if args.condition == "retrieved_human_rubric" and not retrieval_rows:
            raise SystemExit("retrieval_results.jsonl is required for retrieved_human_rubric")
        profile = build_global_profile(usable_memory)
        if args.condition == "global_profile":
            (output / "global_rubric_profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        base_url = args.generator_base_url or os.getenv("JUDGE_BASE_URL")
        model = args.generator_model or os.getenv("JUDGE_MODEL")
        api_key = args.generator_api_key or os.getenv("JUDGE_API_KEY")
        if not base_url or not model:
            raise SystemExit("generator requires --generator-base-url/--generator-model or JUDGE_BASE_URL/JUDGE_MODEL")
        backend = LLMBackend(base_url=base_url, model=model, api_key=api_key, temperature=0.0, max_tokens=args.max_tokens, timeout=args.timeout, retries=1, json_mode=True)
        rows = []
        for case in queries:
            task_id = str(case["instance_id"])
            if args.condition == "retrieved_human_rubric":
                demos = []
                for item in retrieval_rows[task_id]["retrieved"]:
                    found = next((m for m in usable_memory if str(m["task_id"]) == str(item["retrieved_task_id"])), None)
                    if found:
                        demos.append(found)
            elif args.condition == "random_human_rubric":
                rng = __import__("random").Random(args.seed)
                demos = rng.sample(usable_memory, min(args.top_k, len(usable_memory)))
            else:
                demos = []
            try:
                response = backend.infer(generator_prompt(case, args.condition, demos, profile if args.condition == "global_profile" else None, args.generator_prompt_version))
                parsed = response["parsed"]
                validation = validate_generated(parsed.get("criteria") if isinstance(parsed, dict) else None, case)
                rows.append({"task_id": task_id, "condition": args.condition, "generated": parsed, "validation": validation, "provenance": {"model": model, "config_digest": backend.config_digest, "retrieved_task_ids": [x.get("task_id") for x in demos], "excluded_task_ids": sorted(heldout), "response_metadata": response.get("response_metadata", {})}})
            except Exception as exc:  # noqa: BLE001
                rows.append({"task_id": task_id, "condition": args.condition, "error": repr(exc), "provenance": {"model": model, "config_digest": backend.config_digest, "excluded_task_ids": sorted(heldout)}})
            print(f"[rubric-generation] {args.condition} {task_id}")
        target = output / f"generated_rubrics_{args.condition}.jsonl"
        target.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
        print(f"[rubric-generation] wrote {len(rows)} generated rubric records: {target}")
        return 0

    if not memory_path.is_file():
        raise SystemExit(f"missing frozen memory: {memory_path}; run --phase memory first")
    memory = read_jsonl(memory_path)
    queries = choose_queries(cases, args.query_count, args.seed)
    heldout = {str(x["instance_id"]) for x in queries}
    usable_memory = [x for x in memory if str(x["task_id"]) not in heldout]
    retrieval_path = output / "retrieval_results.jsonl"
    review_path = output / "retrieval_quality_review.jsonl"
    rows = []
    reviews = []
    for query in queries:
        retrieved = retrieve(query, usable_memory, top_k=args.top_k, excluded_task_ids=heldout)
        rows.append({"query_task_id": query["instance_id"], "retrieved": retrieved})
        reviews.append({
            "query_task_id": query["instance_id"],
            "top_k": [{"retrieved_task_id": x["retrieved_task_id"], "rank": x["rank"], "relevance": None, "notes": ""} for x in retrieved],
            "useful_at_5": None,
            "strongly_useful_at_5": None,
            "mean_relevance": None,
            "review_status": "pending_manual_review",
        })
    retrieval_path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
    review_path.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in reviews) + "\n", encoding="utf-8")
    manifest = {
        "schema_version": "agenteval.rubric_generation_manifest.v1",
        "experiment_id": args.experiment_id,
        "phase": "retrieval_quality_gate",
        "dataset": str(dataset),
        "labels": str(labels),
        "query_count": len(queries),
        "query_task_ids": sorted(heldout),
        "memory_task_count": len(usable_memory),
        "excluded_task_ids": sorted(heldout),
        "top_k": args.top_k,
        "seed": args.seed,
        "retrieval_method": "semantic+structured",
        "memory_digest": digest(memory),
        "retrieval_digest": digest(rows),
        "status": "pending_manual_review",
        "generation_started": False,
        "downstream_judge_started": False,
    }
    (output / "experiment_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[rubric-generation] wrote {len(queries)} query retrieval packet: {retrieval_path}")
    print(f"[rubric-generation] manual gate review: {review_path}")
    print("[rubric-generation] generation and B Judge were not run")
    return 0

def cmd_analyze(args: argparse.Namespace) -> int:
    """Rubric diagnostics over one or more history files."""
    records = HistoryStore.load_many(args.history)
    print(f"[analyze] {len(records)} history records from {len(args.history)} file(s)")
    for rubric_id in args.rubric:
        report = rubric_diagnostics(records, rubric_id, args.version)
        print("\n" + render_diagnostics(report))
        if args.json:
            out = Path(args.json)
            import json
            out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
            print(f"[saved] {out}")

    if args.judge_skill and args.rule_skill:
        agreement = judge_rule_agreement(records, args.judge_skill,
                                         args.rule_skill,
                                         judge_threshold=args.judge_threshold)
        print("\n" + render_agreement(agreement))
    return 0


def render_agreement(agreement: dict[str, Any]) -> str:
    c = agreement.get("confusion")
    lines = [
        f"# Judge↔rule agreement — {agreement.get('judge_skill')} vs "
        f"{agreement.get('rule_skill')}",
        f"paired cases: {agreement.get('n_paired')}",
        f"judge pass rate: {agreement.get('judge_pass_rate')}  "
        f"rule pass rate: {agreement.get('rule_pass_rate')}",
    ]
    if agreement.get("n_paired", 0) < 2:
        lines.append("insufficient paired cases for agreement stats")
        return "\n".join(lines)
    if agreement.get("cohen_kappa") is None:
        # κ undefined (e.g. both raters always pass) but ρ may still exist
        lines.append("κ undefined (rater marginals make p_exp = 1), "
                     f"Spearman ρ = {agreement.get('spearman_rho')}")
        lines.append(
            f"confusion: TP={c['tp']} FP={c['fp']} FN={c['fn']} TN={c['tn']}")
        return "\n".join(lines)
    lines.append(f"Cohen's κ = {agreement['cohen_kappa']}  "
                 f"Spearman ρ = {agreement['spearman_rho']}")
    lines.append(
        f"confusion: TP={c['tp']} FP={c['fp']} FN={c['fn']} TN={c['tn']}")
    kappa = agreement["cohen_kappa"]
    verdict = ("reliable (κ≥0.6)" if kappa >= 0.6 else
               "weak (0.3≤κ<0.6)" if kappa >= 0.3 else
               "unreliable (κ<0.3)")
    lines.append(f"verdict: {verdict}")
    return "\n".join(lines)


def cmd_migrate(args: argparse.Namespace) -> int:
    """Rubric version migration report (ranking preservation, drift)."""
    records = HistoryStore.load_many(args.history)
    print(f"[migrate] {len(records)} history records from {len(args.history)} file(s)")
    report = migration_report(records, args.skill, args.old_version,
                              args.new_version,
                              disagreement_threshold=args.threshold)
    print("\n" + render_migration(report))
    if args.json:
        import json
        out = Path(args.json)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"[saved] {out}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Check that an existing run has evidence + summary for every case."""
    manifest = json.loads(Path(args.cases).read_text(encoding="utf-8"))
    cases = manifest["cases"] if isinstance(manifest, dict) else manifest
    summary = json.loads((Path(args.run_root) / "summary.json").read_text(encoding="utf-8"))
    if not cases:
        print("[verify] FAIL — case manifest contains zero cases")
        return 1
    scored_rows = summary.get("cases", [])
    scored_ids = [row["case_id"] for row in scored_rows]
    scored = set(scored_ids)
    missing = [c["case_id"] for c in cases if c["case_id"] not in scored]
    duplicates = sorted({case_id for case_id in scored_ids if scored_ids.count(case_id) > 1})
    if missing or duplicates or summary.get("summary", {}).get("n_scored") != len(cases):
        if missing:
            print(f"[verify] MISSING {len(missing)} cases: {missing}")
        if duplicates:
            print(f"[verify] DUPLICATE scored case ids: {duplicates}")
        if summary.get("summary", {}).get("n_scored") != len(cases):
            print("[verify] SCORE COUNT MISMATCH")
        return 1
    print(f"[verify] OK — all {len(cases)} cases scored")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agenteval",
                                     description="Agentified evaluation for LLM agents")
    sub = parser.add_subparsers(dest="command", required=True)

    p_eval = sub.add_parser("eval", help="run an evaluation")
    p_eval.add_argument("--cases", required=True, help="case manifest JSON")
    p_eval.add_argument("--outputs", required=True,
                        help="JSON mapping case_id → agent output text")
    p_eval.add_argument("--case-package", required=True,
                        help="Python module exposing build_registry()/build_router()")
    p_eval.add_argument("--run-root", default="run", help="output directory")
    p_eval.add_argument("--plan-root", default=None,
                        help="shared plan cache directory (optional)")
    p_eval.add_argument("--model-id", default="unknown")
    p_eval.add_argument("--agent-name", default="unknown",
                        help="agent under evaluation (manifest)")
    p_eval.add_argument("--agent-version", default="")
    p_eval.add_argument("--benchmark", action="append", default=[],
                        help="benchmark tag for this run (repeatable)")
    p_eval.add_argument("--workers", type=int, default=1)
    p_eval.add_argument("--refresh", action="store_true",
                        help="ignore plan/results caches")
    p_eval.add_argument("--verbose", action="store_true",
                        help="dump per-case evidence trees")
    p_eval.set_defaults(func=cmd_eval)

    p_rg = sub.add_parser(
        "rubric-generation",
        help="freeze RuVer rubric memory or create a retrieval quality-gate packet",
    )
    p_rg.add_argument("--phase", choices=["memory", "retrieve", "prepare", "generate"], required=True)
    p_rg.add_argument("--dataset", required=True, help="RuVer AgenticCoding dataset JSONL")
    p_rg.add_argument("--labels", required=True, help="RuVer labels JSON")
    p_rg.add_argument("--out", required=True, help="versioned output directory")
    p_rg.add_argument("--source-root", default=None, help="RuVerBench repository root for provenance")
    p_rg.add_argument("--query-count", type=int, default=20)
    p_rg.add_argument("--top-k", type=int, default=5)
    p_rg.add_argument("--seed", type=int, default=20260901)
    p_rg.add_argument("--experiment-id", default="rubric-generation-retrieval-gate-20260901")
    p_rg.add_argument("--condition", choices=["task_only", "random_human_rubric", "retrieved_human_rubric", "global_profile"], default="task_only")
    p_rg.add_argument("--generator-base-url", default=None)
    p_rg.add_argument("--generator-model", default=None)
    p_rg.add_argument("--generator-api-key", default=None)
    p_rg.add_argument("--max-tokens", type=int, default=2048)
    p_rg.add_argument("--timeout", type=float, default=180.0)
    p_rg.add_argument("--generator-prompt-version", choices=["v1_functional_scope", "v2_ruver_scope_aligned", "v3_human_scope_explicit"], default="v1_functional_scope")
    p_rg.set_defaults(func=cmd_rubric_generation)

    def add_octagon_judge_args(parser):
        parser.add_argument("--judge-base-url", default=None,
                            help="OpenAI-compatible judge endpoint (required with --judge-model)")
        parser.add_argument("--judge-model", default=None,
                            help="enable LLM-as-judge overlay with this model")
        parser.add_argument("--judge-api-key", default=None)
        parser.add_argument("--judge-wire-api", default="chat",
                            choices=["chat", "chat_completions", "responses", "response"])
        parser.add_argument("--judge-rubric-file", default=None,
                            help="rubric text supplied to the judge")
        parser.add_argument("--judge-reasoning-effort", default="low",
                            help="OpenRouter-compatible reasoning effort (default: low)")
        parser.add_argument("--deterministic-weight", type=float, default=0.5)
        parser.add_argument("--judge-weight", type=float, default=0.5)
        parser.add_argument("--judge-only", action="store_true",
                            help="skip environment scorer and evaluate only with LLM judge")
        parser.add_argument("--preference-examples", default=None,
                            help="JSON/JSONL human preference examples used to induce a meta-rubric")
        parser.add_argument("--meta-rubric", default=None,
                            help="precomputed meta-rubric JSON; used to generate one rubric per case")
        parser.add_argument("--meta-rubric-id", default="human_preference")
        parser.add_argument("--generate-rubric", action="store_true",
                            help="generate a case-specific rubric from preferences before each judge call")

    p_octagon_eval = sub.add_parser(
        "octagon-eval",
        help="[compat] start an AgentOctagon run then score it; prefer eval-system + octagon-score",
    )
    p_octagon_eval.add_argument("--base-url", default="http://localhost:8100",
                               help="AgentOctagon HTTP API base URL")
    p_octagon_eval.add_argument("--data-root", required=True, help="same data root used by AgentOctagon")
    p_octagon_eval.add_argument("--env-root", required=True, help="agent-octagon-envs root")
    p_octagon_eval.add_argument("--env", required=True, help="environment name")
    p_octagon_eval.add_argument("--task-id", required=True, help="task id in the selected environment")
    p_octagon_eval.add_argument("--agent", action="append", default=[], help="agent name (repeatable)")
    p_octagon_eval.add_argument("--model", default=None, help="shared model name")
    p_octagon_eval.add_argument("--models-json", default=None, help="JSON object mapping agent names to models")
    p_octagon_eval.add_argument("--compare-mode", default="multi-agent")
    p_octagon_eval.add_argument("--timeout-seconds", type=int, default=None)
    p_octagon_eval.add_argument("--request-timeout", type=float, default=30.0)
    p_octagon_eval.add_argument("--wait-timeout", type=float, default=3600.0)
    p_octagon_eval.add_argument("--poll-interval", type=float, default=5.0)
    p_octagon_eval.add_argument("--include-failed", action="store_true")
    p_octagon_eval.add_argument("--run-root", default="run/octagon")
    p_octagon_eval.add_argument("--plan-root", default=None)
    add_octagon_judge_args(p_octagon_eval)
    p_octagon_eval.set_defaults(func=cmd_octagon_eval)

    p_octagon = sub.add_parser(
        "octagon-score",
        help="score existing AgentOctagon attempts with deterministic scorer and/or LLM judge",
    )
    p_octagon.add_argument("--data-root", required=True, help="AgentOctagon data root")
    p_octagon.add_argument("--env-root", required=True, help="agent-octagon-envs root")
    p_octagon.add_argument("--env", default=None, help="only score this environment name")
    p_octagon.add_argument("--attempt-id", action="append", default=[], help="attempt id (repeatable)")
    p_octagon.add_argument("--run-id", default=None, help="only attempts from this run")
    p_octagon.add_argument("--include-failed", action="store_true", help="include failed attempts")
    p_octagon.add_argument("--run-root", default="run/octagon", help="output directory")
    p_octagon.add_argument("--plan-root", default=None, help="shared plan cache directory")
    p_octagon.add_argument("--model-id", default="agent-octagon")
    add_octagon_judge_args(p_octagon)
    p_octagon.set_defaults(func=cmd_octagon_score)

    p_harbor = sub.add_parser(
        "harbor-score",
        help="score persisted Harbor trials through the independent Agent Judge",
    )
    p_harbor.add_argument("--trial-root", required=True, help="Harbor trial, job, or jobs root")
    p_harbor.add_argument("--rubric", required=True, help="versioned structured rubric JSON")
    p_harbor.add_argument(
        "--judge-backend", default="http", choices=["stub", "http"],
        help="Judge transport: http (independent Judge service) or stub (deterministic, no network)",
    )
    p_harbor.add_argument("--judge-service-url", default="http://127.0.0.1:8787")
    p_harbor.add_argument("--judge-endpoint", default="/v1/judge/evaluate")
    p_harbor.add_argument("--judge-api-key", default=None)
    p_harbor.add_argument("--judge-timeout", type=float, default=180.0)
    p_harbor.add_argument("--include-failed", action="store_true")
    p_harbor.add_argument("--run-root", default="run/harbor-judge")
    p_harbor.add_argument("--plan-root", default=None)
    p_harbor.add_argument("--model-id", default="independent-agent-judge")
    p_harbor.set_defaults(func=cmd_harbor_score)

    def add_planner_args(parser):
        parser.add_argument("--base-url", required=True)
        parser.add_argument("--model", required=True)
        parser.add_argument("--api-key", default=None)
        parser.add_argument("--wire-api", default="chat", choices=["chat", "chat_completions", "responses", "response"])
        parser.add_argument("--reasoning-effort", default="low")

    p_project = sub.add_parser(
        "project-ir-rubric",
        help="project a frozen Forge Environment IR rubric into agenteval.rubric.v1",
    )
    p_project.add_argument("--ir", required=True, help="frozen environment-ir.json")
    p_project.add_argument("--output", required=True, help="AgentEval rubric JSON output")
    p_project.set_defaults(func=cmd_project_ir_rubric)

    p_induce = sub.add_parser("rubric-induce", help="infer a meta-rubric from human preference examples")
    p_induce.add_argument("--examples", required=True, help="JSON/JSONL preference examples or directory")
    p_induce.add_argument("--output", required=True, help="meta-rubric JSON output")
    p_induce.add_argument("--rubric-id", default="human_preference")
    add_planner_args(p_induce)
    p_induce.set_defaults(func=cmd_rubric_induce)

    p_instantiate = sub.add_parser("rubric-instantiate", help="instantiate a case rubric from a meta-rubric")
    p_instantiate.add_argument("--meta-rubric", required=True)
    p_instantiate.add_argument("--case", required=True, help="Case JSON")
    p_instantiate.add_argument("--output", required=True, help="case rubric JSON output")
    p_instantiate.add_argument("--rubric-id", default=None)
    add_planner_args(p_instantiate)
    p_instantiate.set_defaults(func=cmd_rubric_instantiate)

    p_verify = sub.add_parser("verify", help="verify a completed run")
    p_verify.add_argument("--cases", required=True)
    p_verify.add_argument("--run-root", default="run")
    p_verify.set_defaults(func=cmd_verify)

    p_analyze = sub.add_parser(
        "analyze", help="rubric diagnostics over evaluation history")
    p_analyze.add_argument("--history", action="append", required=True,
                           help="history.jsonl path (repeatable; merged)")
    p_analyze.add_argument("--rubric", action="append", required=True,
                           help="rubric_id to diagnose (repeatable)")
    p_analyze.add_argument("--version", default=None,
                           help="pin rubric version (default: all)")
    p_analyze.add_argument("--json", default=None,
                           help="also write the report as JSON")
    p_analyze.add_argument("--judge-skill", default=None,
                           help="LLM skill id for judge↔rule agreement")
    p_analyze.add_argument("--rule-skill", default=None,
                           help="rule skill id for judge↔rule agreement")
    p_analyze.add_argument("--judge-threshold", type=float, default=0.5,
                           help="pass threshold for the judge score (default 0.5)")
    p_analyze.set_defaults(func=cmd_analyze)

    p_migrate = sub.add_parser(
        "migrate", help="rubric version migration report")
    p_migrate.add_argument("--history", action="append", required=True,
                           help="history.jsonl path (repeatable; merged)")
    p_migrate.add_argument("--skill", required=True)
    p_migrate.add_argument("--old-version", required=True)
    p_migrate.add_argument("--new-version", required=True)
    p_migrate.add_argument("--threshold", type=float, default=0.2,
                           help="large-disagreement |Δ| threshold")
    p_migrate.add_argument("--json", default=None,
                           help="also write the report as JSON")
    p_migrate.set_defaults(func=cmd_migrate)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(f"[agenteval] error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
