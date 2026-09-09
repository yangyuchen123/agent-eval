import inspect

from agentjudge.agents import build_joint_question_agent
from agentjudge.service import JointQuestionJudgeService


def test_production_joint_b_does_not_register_tools_by_default():
    source = inspect.getsource(build_joint_question_agent)
    assert "enable_tools: bool = False" in source
    assert "if enable_tools:" in source
    assert source.index("if enable_tools:") < source.index("search_evidence")


def test_joint_service_prompt_forbids_tools():
    source = inspect.getsource(JointQuestionJudgeService.evaluate)
    assert "Do not call tools" in source
    assert "enable_joint_tools" in source


def test_one_shot_b_uses_compact_output_schema():
    source = inspect.getsource(build_joint_question_agent)
    assert "CompactJointJudgment" in source
