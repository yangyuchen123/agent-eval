"""Runtime-neutral orchestration for independent multi-question judging."""
from __future__ import annotations

from pathlib import Path

from .adapters.contracts import EvalSample
from .judge import JudgeClient, MultiQuestionJudgeSkill
from .planner import RuleRouter
from .protocols import Plan
from .report import build_report, write_report_artifacts
from .runner import RunConfig, run_eval, write_evidence
from .score import dataset_summary, weighted_case_score
from .skills.registry import SkillRegistry


def score_runtime_samples(
    samples: list[EvalSample], *, client: JudgeClient, rubric, run_root: str | Path,
    model_id: str = "independent-judge", plan_root: str | Path | None = None,
):
    skill = MultiQuestionJudgeSkill(
        client, rubric, skill_id="runtime_multi_question_judge", role="core")
    registry = SkillRegistry()
    registry.register(skill)

    def route(case, catalog):
        return Plan(
            case_id=case.case_id,
            selected_skills=({
                "skill_id": skill.skill_id,
                "role": "core",
                "reason": "independent Judge evaluates the frozen rubric questions",
                "parameters": {},
            },),
            skipped_skills=(),
            routing_mode="rule",
            planner={"backend": "independent-agent-judge"},
        )

    agent_names = sorted({sample.agent.name for sample in samples})
    agent_versions = sorted({sample.agent.version or "" for sample in samples})
    config = RunConfig(
        router=RuleRouter(route), registry=registry, run_root=Path(run_root),
        plan_root=Path(plan_root) if plan_root else None, model_id=model_id,
        agent_name=agent_names[0] if len(agent_names) == 1 else "multiple",
        agent_version=agent_versions[0] if len(agent_versions) == 1 else "",
        benchmarks=tuple(sorted({s.backend for s in samples})),
    )
    cases = [sample.to_case() for sample in samples]
    outputs = {sample.sample_id: sample.output for sample in samples}
    report = run_eval(config, cases, outputs)
    write_evidence(config.run_root, report)
    weights = {skill.skill_id: 1.0}
    case_scores = {
        case_id: weighted_case_score(evidence, weights)
        for case_id, evidence in report.evidence.items()
    }
    summary = dataset_summary(list(report.evidence.values()), case_scores, weights)
    final = build_report(
        list(report.evidence.values()), case_scores, summary,
        model_id=model_id, aggregator_name="independent_multi_question_weighted_mean")
    artifacts = write_report_artifacts(config.run_root, final)
    return report, artifacts
