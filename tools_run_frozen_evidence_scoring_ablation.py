"""Run scoring-only 5×4×3 frozen-evidence anchor representation ablation."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentjudge.http_service import load_project_dotenv
from agentjudge.scoring import FrozenEvidenceScoringService
from agenteval.meta_eval import build_resolution_rubric

ROOT = Path(__file__).resolve().parent
BUNDLE_DIR = ROOT / "meta_eval/frozen_evidence_scoring_v1"
DEFAULT_OUTPUT = ROOT / "run/meta_eval/frozen-evidence-scoring-ablation-v1"
CONDITIONS = {
    "A_5_qualitative": (5, "qualitative"),
    "B_5_continuum": (5, "continuum"),
    "C_6_qualitative": (6, "qualitative"),
    "D_6_continuum": (6, "continuum"),
}


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def build_model() -> Any:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    key = os.environ.get("JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("JUDGE_API_KEY/OPENAI_API_KEY is not set")
    return OpenAIChatModel(
        os.environ.get("JUDGE_MODEL", "gpt-5.6-luna"),
        provider=OpenAIProvider(base_url=os.environ.get("JUDGE_BASE_URL"), api_key=key),
    )


def load_bundles() -> list[tuple[dict[str, Any], str]]:
    result = []
    for path in sorted(BUNDLE_DIR.glob("att_*.json")):
        bundle = json.loads(path.read_text(encoding="utf-8"))
        result.append((bundle, canonical_digest(bundle)))
    if len(result) != 5:
        raise SystemExit(f"expected 5 frozen bundles, found {len(result)}")
    return result


def question_for(levels: int, style: str, question_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    questions, rubric = build_resolution_rubric(levels, style=style)
    matches = [dict(q) for q in questions if str(q.get("id")) == question_id]
    if len(matches) != 1:
        raise ValueError(f"question {question_id!r} not found exactly once")
    return matches[0], rubric


async def main_async() -> None:
    load_project_dotenv()
    output = Path(os.environ.get("META_EVAL_OUTPUT", str(DEFAULT_OUTPUT)))
    repeats = int(os.environ.get("FROZEN_SCORING_REPEATS", "3"))
    if repeats < 1:
        raise SystemExit("FROZEN_SCORING_REPEATS must be positive")
    bundles = load_bundles()
    model = build_model()
    model_name = os.environ.get("JUDGE_MODEL", "gpt-5.6-luna")
    output.mkdir(parents=True, exist_ok=True)
    judgments_path = output / "judgments.jsonl"
    existing: set[tuple[str, str, int]] = set()
    if judgments_path.exists():
        for line in judgments_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                item = json.loads(line)
                existing.add((item["case_id"], item["condition"], int(item["repeat"])))

    condition_meta: dict[str, Any] = {}
    for name, (levels, style) in CONDITIONS.items():
        question, rubric = question_for(levels, style, "observed_failure_handling")
        condition_meta[name] = {
            "levels": levels,
            "style": style,
            "rubric_version": rubric["version"],
            "anchor_digest": canonical_digest(question["score_anchors"]),
            "declared_score_anchors": question["score_anchors"],
        }

    manifest = {
        "schema_version": "agenteval.frozen_evidence_scoring_ablation.v1",
        "experiment_id": output.name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": model_name,
        "base_url_configured": bool(os.environ.get("JUDGE_BASE_URL")),
        "api_key_recorded": False,
        "repeats": repeats,
        "expected_observations": len(bundles) * len(CONDITIONS) * repeats,
        "bundle_dir": str(BUNDLE_DIR.relative_to(ROOT)),
        "bundles": {bundle["case_id"]: digest for bundle, digest in bundles},
        "conditions": condition_meta,
        "controls": {
            "same_frozen_bundle_across_conditions": True,
            "no_evidence_tools": True,
            "no_gold_in_prompt": True,
            "only_anchor_ladder_varies": True,
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    completed = len(existing)
    total = manifest["expected_observations"]
    for bundle, bundle_digest in bundles:
        case_id = str(bundle["case_id"])
        question_id = str(bundle["question_id"])
        for condition, (levels, style) in CONDITIONS.items():
            question, rubric = question_for(levels, style, question_id)
            for repeat in range(repeats):
                key = (case_id, condition, repeat)
                if key in existing:
                    continue
                service = FrozenEvidenceScoringService(model)
                started = time.perf_counter()
                decision = await service.evaluate(question=question, bundle=bundle)
                latency_ms = (time.perf_counter() - started) * 1000
                row = {
                    "schema_version": "agenteval.frozen_scoring_observation.v1",
                    "case_id": case_id,
                    "question_id": question_id,
                    "condition": condition,
                    "levels": levels,
                    "style": style,
                    "repeat": repeat,
                    "bundle_digest": bundle_digest,
                    "rubric_version": rubric["version"],
                    "anchor_digest": canonical_digest(question["score_anchors"]),
                    "declared_score_anchors": question["score_anchors"],
                    **decision.model_dump(),
                    "latency_ms": latency_ms,
                    "token_usage": service.last_usage,
                    "provenance": service.last_provenance,
                    "model": model_name,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                with judgments_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                completed += 1
                print(f"[{completed}/{total}] {case_id} {condition} repeat={repeat} score={decision.score}", flush=True)

    observations = [json.loads(x) for x in judgments_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    keys = {(x["case_id"], x["condition"], int(x["repeat"])) for x in observations}
    if len(keys) != total:
        raise SystemExit(f"incomplete or duplicate output: unique={len(keys)} expected={total}")
    digests_by_case: dict[str, set[str]] = {}
    for row in observations:
        digests_by_case.setdefault(row["case_id"], set()).add(row["bundle_digest"])
    if any(len(values) != 1 for values in digests_by_case.values()):
        raise SystemExit(f"bundle digest changed across conditions: {digests_by_case}")
    print(json.dumps({"output": str(output), "observations": len(observations), "bundle_digest_control": True}, indent=2))


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
