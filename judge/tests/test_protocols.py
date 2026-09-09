from agentjudge.protocols import (
    JointMultiRubricProtocol,
    OriginalIndependentRubricProtocol,
    SharedEvidenceIndependentScoreProtocol,
    SharedEvidenceJointProtocol,
    build_protocol,
    protocol_names,
)


def test_frozen_protocol_registry_has_four_named_conditions():
    assert set(protocol_names()) == {"A", "B", "C", "D"}
    assert isinstance(build_protocol("A", object()), OriginalIndependentRubricProtocol)
    assert isinstance(build_protocol("B", object()), JointMultiRubricProtocol)
    assert isinstance(build_protocol("C", object()), SharedEvidenceJointProtocol)
    assert isinstance(build_protocol("D", object()), SharedEvidenceIndependentScoreProtocol)
