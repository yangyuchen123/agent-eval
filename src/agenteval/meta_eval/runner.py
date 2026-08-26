"""Replayable meta-evaluation runner independent of normal benchmark scoring."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Protocol
import json

from .gold import GoldJudgment
from .metrics import retrieval_metrics, score_summary, stability_metrics
from .perturbations import EvidenceSnapshot, record_id
from .taxonomy import FailureCode, classify_failure


@dataclass(frozen=True)
class MetaCase:
    case_id: str
    question_id: str
    case: dict[str, Any]
    question: dict[str, Any]
    rubric: dict[str, Any]
    agent_output: str = ""
    evidence: EvidenceSnapshot = field(default_factory=lambda: EvidenceSnapshot.from_records([]))
    gold: GoldJudgment | None = None
    trace_digest: str | None = None
    artifact_digest: str | None = None
    judge_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgmentObservation:
    run_id: str
    case_id: str
    question_id: str
    judge_mode: str
    perturbation: str
    perturbation_seed: int | None
    score: float | None
    status: str
    evidence_refs: list[str]
    findings: list[dict[str, Any]]
    provenance: dict[str, Any]
    latency_ms: float | None = None
    token_usage: dict[str, Any] | None = None
    cost: float | None = None
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JudgeCallable(Protocol):
    def __call__(self, case: MetaCase, snapshot: EvidenceSnapshot) -> Mapping[str, Any]: ...


class MetaEvalRunner:
    """Run repeated and perturbation experiments with frozen inputs."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)

    def run(
        self,
        cases: list[MetaCase],
        judges: Mapping[str, JudgeCallable],
        *,
        repeats: int = 1,
        perturbations: list[tuple[str, Callable[[EvidenceSnapshot, int], EvidenceSnapshot]]] | None = None,
        seed: int = 0,
    ) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        perturbations = perturbations or [("none", lambda snapshot, _seed: snapshot)]
        run_id = sha256(json.dumps({
            "seed": seed,
            "repeats": repeats,
            "cases": [{"case_id": c.case_id, "question_id": c.question_id,
                       "snapshot_digest": c.evidence.snapshot_digest,
                       "judge_config": c.judge_config} for c in cases],
            "judges": list(judges),
            "perturbations": [name for name, _ in perturbations],
        }, sort_keys=True, default=str).encode()).hexdigest()[:16]
        manifest = {"run_id": run_id, "seed": seed, "repeats": repeats, "judge_modes": list(judges), "case_count": len(cases), "perturbations": [name for name, _ in perturbations]}
        (self.output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        observations: list[JudgmentObservation] = []
        groups: dict[str, list[dict[str, Any]]] = {}
        for case in cases:
            for mode, judge in judges.items():
                for perturbation_name, transform in perturbations:
                    for repeat in range(repeats):
                        perturb_seed = seed + repeat
                        snapshot = transform(case.evidence, perturb_seed)
                        started = perf_counter()
                        try:
                            raw = dict(judge(case, snapshot))
                            error = None
                        except Exception as exc:  # preserve failed experiments
                            raw = {"score": None, "status": "judge_error", "evidence_refs": [], "findings": [], "provenance": {"error": repr(exc)}}
                            error = repr(exc)
                        latency = (perf_counter() - started) * 1000
                        key = f"{case.case_id}|{case.question_id}|{mode}|{perturbation_name}"
                        prior = groups.setdefault(key, [])
                        failures = classify_failure(case.gold, raw, available_evidence_ids=[record_id(r) for r in snapshot.records], repeated_judgments=prior)
                        anchor_scores = _question_anchor_scores(case.question)
                        raw_score = raw.get("score")
                        if (anchor_scores and raw_score is not None
                                and not any(abs(float(raw_score) - score) <= 1e-9 for score in anchor_scores)):
                            failures.append(FailureCode.RUBRIC_ANCHOR_FAILURE)
                        if error:
                            failures.append(FailureCode.UNCLASSIFIED)
                        provenance = dict(raw.get("provenance") or {})
                        provenance["meta_eval"] = {"snapshot_digest": snapshot.snapshot_digest, "trace_digest": case.trace_digest, "artifact_digest": case.artifact_digest, "judge_config": case.judge_config, "perturbation_seed": perturb_seed}
                        obs = JudgmentObservation(run_id, case.case_id, case.question_id, mode, perturbation_name, perturb_seed, raw.get("score"), str(raw.get("status", "unknown")), [str(x) for x in raw.get("evidence_refs", [])], [dict(x) for x in raw.get("findings", []) if isinstance(x, Mapping)], provenance, latency, raw.get("token_usage"), raw.get("cost"), [f.value for f in dict.fromkeys(failures)])
                        observations.append(obs)
                        prior.append(obs.to_dict())
        self._write_jsonl("judgments.jsonl", observations)
        failures = [item.to_dict() for item in observations if item.failures]
        (self.output_dir / "failures.jsonl").write_text("".join(json.dumps(item, ensure_ascii=False) + "\n" for item in failures), encoding="utf-8")
        metrics = self._aggregate(observations, cases)
        (self.output_dir / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
        from .report import write_report
        write_report(self.output_dir, {"manifest": manifest, "metrics": metrics})
        return {"manifest": manifest, "metrics": metrics, "observations": [o.to_dict() for o in observations]}

    def _aggregate(self, observations: list[JudgmentObservation], cases: list[MetaCase]) -> dict[str, Any]:
        gold_by_key = {(c.case_id, c.question_id): c.gold for c in cases}
        result: dict[str, Any] = {
            "observation_count": len(observations),
            "by_group": {},
            "by_case_aggregate": {},
            "failure_counts": {},
        }
        grouped: dict[str, list[JudgmentObservation]] = {}
        for item in observations:
            grouped.setdefault(f"{item.case_id}|{item.question_id}|{item.judge_mode}|{item.perturbation}", []).append(item)
            for failure in item.failures:
                result["failure_counts"][failure] = result["failure_counts"].get(failure, 0) + 1
        for key, items in grouped.items():
            gold = gold_by_key.get((items[0].case_id, items[0].question_id))
            scores = [x.score for x in items if x.score is not None]
            group = {
                "n": len(items),
                "stability": stability_metrics([x.to_dict() for x in items]),
                "latency_ms": _mean([x.latency_ms for x in items]),
                "token_usage": _usage_summary([x.token_usage for x in items]),
                "cost": _cost_summary([x.cost for x in items]),
                "gold": gold.to_dict() if gold else None,
            }
            if gold:
                group["retrieval"] = retrieval_metrics(gold.required_evidence_refs, [ref for x in items for ref in x.evidence_refs], [record_id(r) for c in cases if c.case_id == items[0].case_id for r in c.evidence.records])
            result["by_group"][key] = group
        result["by_case_aggregate"] = _case_aggregate_metrics(observations, cases)
        return result

    def _write_jsonl(self, name: str, values: list[JudgmentObservation]) -> None:
        with (self.output_dir / name).open("w", encoding="utf-8") as handle:
            for value in values:
                handle.write(json.dumps(value.to_dict(), ensure_ascii=False) + "\n")


def _question_anchor_scores(question: Mapping[str, Any]) -> list[float]:
    return [
        float(anchor["score"])
        for anchor in (question.get("score_anchors") or [])
        if isinstance(anchor, Mapping) and anchor.get("score") is not None
    ]


def _case_aggregate_metrics(
    observations: list[JudgmentObservation], cases: list[MetaCase]
) -> dict[str, Any]:
    question_meta: dict[tuple[str, str], float] = {}
    expected: dict[str, set[str]] = {}
    for case in cases:
        weight = float(case.question.get("weight", 1.0))
        question_meta[(case.case_id, case.question_id)] = weight
        expected.setdefault(case.case_id, set()).add(case.question_id)
    grouped: dict[tuple[str, str, str], list[JudgmentObservation]] = {}
    for item in observations:
        grouped.setdefault(
            (item.case_id, item.judge_mode, item.perturbation), []
        ).append(item)
    result: dict[str, Any] = {}
    for (case_id, mode, perturbation), items in grouped.items():
        by_seed: dict[int | None, list[JudgmentObservation]] = {}
        for item in items:
            by_seed.setdefault(item.perturbation_seed, []).append(item)
        repeats: list[dict[str, Any]] = []
        for seed, seed_items in sorted(by_seed.items(), key=lambda pair: (pair[0] is None, pair[0])):
            scores = {item.question_id: item.score for item in seed_items}
            required = expected.get(case_id, set())
            complete = required.issubset(scores) and all(scores[qid] is not None for qid in required)
            aggregate = None
            if complete:
                weighted = [
                    (float(scores[qid]), question_meta[(case_id, qid)])
                    for qid in required if question_meta[(case_id, qid)] > 0
                ]
                if weighted:
                    aggregate = round(
                        sum(value * weight for value, weight in weighted)
                        / sum(weight for _, weight in weighted), 6
                    )
            repeats.append({
                "perturbation_seed": seed,
                "score": aggregate,
                "complete": complete,
                "subscores": {qid: scores.get(qid) for qid in sorted(required)},
            })
        aggregate_scores = [item["score"] for item in repeats if item["score"] is not None]
        result[f"{case_id}|{mode}|{perturbation}"] = {
            "question_ids": sorted(expected.get(case_id, set())),
            "repeat_aggregates": repeats,
            "score": score_summary(aggregate_scores),
            "exact_aggregate_agreement": (
                len(set(aggregate_scores)) == 1 if aggregate_scores else None
            ),
        }
    return result


def _mean(values: list[float | None]) -> float | None:
    values = [x for x in values if x is not None]
    return sum(values) / len(values) if values else None


def _usage_summary(values: list[dict[str, Any] | None]) -> dict[str, Any]:
    available = [value for value in values if value]
    keys = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens", "requests", "tool_calls")
    return {
        "available": len(available),
        **{f"total_{key}": sum(float(value.get(key, 0) or 0) for value in available) if available else None for key in keys},
        **{f"mean_{key}": _mean([float(value.get(key, 0) or 0) for value in available]) for key in keys},
    }


def _cost_summary(values: list[float | None]) -> dict[str, Any]:
    available = [float(value) for value in values if value is not None]
    return {"available": len(available), "total": sum(available) if available else None,
            "mean": _mean(available)}
