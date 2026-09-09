"""Shared CLI for a single RRD optimization job."""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
from ..backends import LLMBackend
from ..io import value_digest
from .adapter import from_rrd_rubrics, to_rrd_rubrics
from .decomposer import decompose_with_backend
from .evaluator import evaluate_with_backend, materialize_responses
from .initial_generator import generate_initial_with_backend
from .models import CalibrationResponse, OptimizationConfig
from .optimizer import RRDRubricOptimizer


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_rubrics(path: Path):
    data = load_json(path)
    if isinstance(data, dict):
        data = data.get("criteria") or data.get("rubrics") or data
    if not isinstance(data, list):
        raise SystemExit("rubrics input must be a JSON list or an object with criteria/rubrics")
    return data


def load_responses(path: Path):
    data = load_json(path)
    if isinstance(data, dict): data = data.get("responses") or data
    if not isinstance(data, list): raise SystemExit("responses input must be a JSON list")
    return data


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.strip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    _load_dotenv()
    p = argparse.ArgumentParser(description="RRD response-driven rubric optimizer")
    p.add_argument("--task-id", required=True)
    p.add_argument("--task-file", required=True)
    p.add_argument("--rubrics")
    p.add_argument("--initial-generate", action="store_true", help="standalone RRD initial proposal from task + calibration responses")
    p.add_argument("--responses", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--base-url", default=os.getenv("GENERATOR_BASE_URL") or os.getenv("JUDGE_BASE_URL"))
    p.add_argument("--model", default=os.getenv("GENERATOR_MODEL") or os.getenv("JUDGE_MODEL"))
    p.add_argument("--api-key", default=os.getenv("GENERATOR_API_KEY") or os.getenv("JUDGE_API_KEY") or os.getenv("OPENAI_API_KEY"))
    p.add_argument("--wire-api", default=os.getenv("GENERATOR_WIRE_API", "chat"))
    p.add_argument("--backend", choices=["pydantic_ai", "urllib"], default="pydantic_ai", help="LLM execution backend; default pydantic_ai uses typed output validation. urllib is a compatibility fallback only.")
    p.add_argument("--cache", help="JSONL cache for successful typed calls")
    p.add_argument("--call-log", help="JSONL per-call success/error log")
    p.add_argument("--response-batch-size", type=int, default=5, help="Responses per evaluator call with pydantic_ai")
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--timeout", type=float, default=300.0)
    p.add_argument("--config", help="JSON config overrides")
    p.add_argument("--require-artifact", action="store_true", help="Judge artifact summaries; missing artifacts score 0")
    p.add_argument("--include-runtrace", action="store_true", help="Optional process evidence; off by default, including GDPval")
    p.add_argument("--no-agent-prose", action="store_true", help="Do not include final_agent_response in evaluator/decomposer prompts")
    p.add_argument("--broadness-groups", default="", help="Comma-separated quality groups counted by broadness; empty counts all")
    p.add_argument("--evaluate-only", action="store_true", help="Score the supplied rubrics only; do not decompose")
    p.add_argument("--repeats", type=int, default=1, help="With --evaluate-only, repeat the matrix this many times without process cache")
    args = p.parse_args()
    task = Path(args.task_file).read_text(encoding="utf-8")
    raw_responses = load_responses(Path(args.responses))
    raw_rubrics = load_rubrics(Path(args.rubrics)) if args.rubrics else None
    responses = [CalibrationResponse.from_mapping(x, i) for i, x in enumerate(raw_responses)]
    if not args.base_url or not args.model: raise SystemExit("--base-url and --model (or GENERATOR_* env vars) are required")
    if args.backend == "pydantic_ai":
        from .pydantic_backend import PydanticAIBackend
        out_path = Path(args.out)
        cache_path = args.cache or str(out_path.with_name(f"rrd_cache_{out_path.stem}.jsonl"))
        call_log_path = args.call_log or str(out_path.with_name(f"rrd_calls_{out_path.stem}.jsonl"))
        backend = PydanticAIBackend(base_url=args.base_url, model=args.model, api_key=args.api_key,
                                    timeout=args.timeout, retries=1, temperature=0.0,
                                    max_tokens=args.max_tokens,
                                    cache_path=None if args.evaluate_only and args.repeats > 1 else cache_path,
                                    call_log_path=call_log_path,
                                    response_batch_size=args.response_batch_size,
                                    thinking=False)
    else:
        backend = LLMBackend(base_url=args.base_url, model=args.model, api_key=args.api_key,
                             wire_api=args.wire_api, temperature=0.0, max_tokens=args.max_tokens,
                             timeout=args.timeout, retries=1, json_mode=True)
    config = OptimizationConfig()
    if args.config:
        values = load_json(Path(args.config))
        for key, value in values.items():
            if hasattr(config, key):
                setattr(config, key, tuple(value) if key == "broadness_quality_groups" and isinstance(value, list) else value)
    if args.require_artifact:
        config.require_artifact = True
    if args.include_runtrace:
        config.include_runtrace = True
    if args.no_agent_prose:
        config.include_agent_prose = False
    if args.broadness_groups.strip():
        config.broadness_quality_groups = tuple(x.strip() for x in args.broadness_groups.split(",") if x.strip())
    if hasattr(backend, "response_batch_size"):
        backend.response_batch_size = int(config.response_batch_size)
    responses = materialize_responses(responses, config)
    generation_meta = None
    if args.initial_generate:
        rubrics, generation_meta = generate_initial_with_backend(backend, task, responses, config)
    elif raw_rubrics is not None:
        rubrics = to_rrd_rubrics(raw_rubrics)
    else:
        raise SystemExit("provide --rubrics or use --initial-generate")
    if args.evaluate_only:
        from .evaluator import evaluate_with_backend, metrics_from_matrix
        from .metrics import flip_metrics_from_repeats, rubric_set_metrics
        repeats = max(1, int(args.repeats))
        matrices = []
        metas = []
        metric_rows = []
        for i in range(repeats):
            if hasattr(backend, "_cache"):
                backend._cache.clear()
            matrix, meta = evaluate_with_backend(backend, task, rubrics, responses, config)
            metrics = metrics_from_matrix(matrix, responses, config)
            matrices.append(matrix)
            metas.append(meta)
            metric_rows.append({"repeat": i + 1, "set_metrics": rubric_set_metrics(metrics),
                                "broad_candidates": [r.rubric_id for r in rubrics if metrics[r.rubric_id].broad_candidate],
                                "matrix": matrix, "metrics": {k: v.to_dict() for k, v in metrics.items()}})
            print(f"evaluate-only repeat={i+1}/{repeats} broad={sum(metrics[r.rubric_id].broad_candidate for r in rubrics)}/{len(rubrics)}", flush=True)
        present_ids = [x.response_id for x in responses if (not config.require_artifact) or x.artifact_status == "present"]
        flip = flip_metrics_from_repeats(matrices, rubric_ids=[r.rubric_id for r in rubrics], response_ids=[x.response_id for x in responses])
        present_flip = flip_metrics_from_repeats(matrices, rubric_ids=[r.rubric_id for r in rubrics], response_ids=present_ids) if present_ids else {}
        broad_flags = []
        for row in metric_rows:
            flags = {rid: rid in set(row["broad_candidates"]) for rid in [r.rubric_id for r in rubrics]}
            broad_flags.append(flags)
        rubric_broad_flip = []
        for r in rubrics:
            flags = [bool(f[r.rubric_id]) for f in broad_flags]
            rubric_broad_flip.append({"rubric_id": r.rubric_id, "broad_flags": flags, "flip": len(set(flags)) > 1})
        set_broad_rates = [row["set_metrics"]["broad_candidate_rate"] for row in metric_rows]
        payload = {
            "schema_version": "agenteval.rrd_evaluate_only.v1",
            "task_id": args.task_id,
            "repeat_count": repeats,
            "rubric_count": len(rubrics),
            "repeats": metric_rows,
            "flip": flip,
            "present_artifact_flip": present_flip,
            "broad_label_flip_count": sum(x["flip"] for x in rubric_broad_flip),
            "broad_label_flip_rate": sum(x["flip"] for x in rubric_broad_flip) / (len(rubric_broad_flip) or 1),
            "broad_rate_by_repeat": set_broad_rates,
            "broad_flags": rubric_broad_flip,
            "evaluator_metadata": metas,
        }
        payload["manifest"] = {
            "schema_version": "agenteval.rrd_manifest.v1",
            "mode": "evaluate_only",
            "task_id": args.task_id,
            "task_digest": value_digest(task),
            "initial_rubric_digest": value_digest([r.to_dict() for r in rubrics]),
            "calibration_response_digest": value_digest([x.__dict__ for x in responses]),
            "calibration_response_ids": [x.response_id for x in responses],
            "artifact_status": {x.response_id: x.artifact_status for x in responses},
            "include_runtrace": config.include_runtrace,
            "require_artifact": config.require_artifact,
            "broadness_quality_groups": list(config.broadness_quality_groups) if config.broadness_quality_groups else None,
            "backend": args.backend,
            "thinking": False if args.backend == "pydantic_ai" else None,
            "cache_disabled": bool(args.evaluate_only and args.repeats > 1),
            "model": args.model,
            "config": config.to_dict(),
        }
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(out)
        return 0
    optimizer = RRDRubricOptimizer(
        lambda t, r, s: evaluate_with_backend(backend, t, r, s, config),
        lambda t, c, s, m: decompose_with_backend(backend, t, c, s, m, config),
        config,
    )
    result = optimizer.optimize(args.task_id, task, rubrics, responses)
    originals = {x.rubric_id: x.to_dict() for x in rubrics}
    payload = result.to_dict(); payload["optimized_agent_eval_criteria"] = from_rrd_rubrics(result.optimized_rubrics, originals)
    payload["manifest"] = {
        "schema_version": "agenteval.rrd_manifest.v1",
        "task_id": args.task_id,
        "task_digest": value_digest(task),
        "initial_rubric_digest": value_digest([r.to_dict() for r in rubrics]),
        "calibration_response_digest": value_digest([x.__dict__ for x in responses]),
        "calibration_response_ids": [x.response_id for x in responses],
        "artifact_status": {x.response_id: x.artifact_status for x in responses},
        "include_runtrace": config.include_runtrace,
        "require_artifact": config.require_artifact,
        "broadness_quality_groups": list(config.broadness_quality_groups) if config.broadness_quality_groups else None,
        "backend": args.backend,
        "thinking": False if args.backend == "pydantic_ai" else None,
        "model": args.model,
        "timeout": args.timeout,
        "response_batch_size": args.response_batch_size,
        "cache_path": str(getattr(backend, "cache_path", "") or "") or None,
        "call_log_path": str(getattr(backend, "call_log_path", "") or "") or None,
        "backend_config_digest": backend.config_digest,
        "config": config.to_dict(),
        "initial_generation": generation_meta,
    }
    out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trace = out.with_name(f"optimization_trace_{out.stem}.jsonl"); trace.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in result.trace) + "\n", encoding="utf-8")
    rounds_dir = out.with_name(f"rounds_{out.stem}"); rounds_dir.mkdir(parents=True, exist_ok=True)
    for snap in result.round_snapshots:
        name = f"round_{snap['iteration']:02d}_{snap['phase']}.json"
        (rounds_dir / name).write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (rounds_dir / "index.json").write_text(json.dumps([
        {k: snap.get(k) for k in ("iteration", "phase", "stop_reason", "rubric_count", "broad_count", "broad_candidates", "set_metrics", "split_parents") if k in snap or True}
        for snap in result.round_snapshots
    ], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out); print(trace); print(rounds_dir)
    return 0

if __name__ == "__main__": raise SystemExit(main())
