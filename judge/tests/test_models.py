from agentjudge import EvidenceRecord, InMemoryEvidenceProvider
from agentjudge.models import EvidenceQuery, QuestionJudgment


def test_evidence_provider_preserves_provenance_and_queries():
    records = [EvidenceRecord(
        evidence_id="trace.jsonl:1",
        source="trace.jsonl",
        kind="tool_call",
        evidence_class="direct_runtime_event",
        claim_strength="direct",
        tool_call_id="call-1",
        content={"arguments": {"description": "security review"}},
    )]
    provider = InMemoryEvidenceProvider(records)
    result = provider.search(EvidenceQuery(text="security"))
    assert result[0].evidence_id == "trace.jsonl:1"
    assert provider.call_context("call-1")[0].claim_strength == "direct"


def test_question_judgment_is_structured():
    judgment = QuestionJudgment(
        question_id="handoff",
        score=0.7,
        confidence=0.6,
        status="partially_supported",
    )
    assert judgment.score == 0.7


def test_catalog_filters_delta_and_marks_retrospective(tmp_path):
    (tmp_path / "trace.jsonl").write_text(
        '{"tool_name":"Agent","arguments":{"description":"dispatch security"},"tool_call_id":"c1"}\n'
        '{"tool_name":"Write","arguments":{"file_path":"artifacts/coordination_log.json","content":"subagent_wait"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "events.jsonl").write_text(
        '{"kind":"llm:content:delta","raw":{"payload":{"content":"repeated"}}}\n'
        '{"kind":"agent:start","timestamp":"t1","raw":{"payload":{"agent_id":"security"}}}\n',
        encoding="utf-8",
    )
    from agentjudge import EvidenceCatalog
    catalog = EvidenceCatalog.from_attempt_dir(tmp_path)
    assert catalog.manifest()["record_count"] == 3
    assert catalog.search(EvidenceQuery(text="subagent_wait", limit=3))[0].evidence_class == "retrospective_artifact"
    assert not catalog.search(EvidenceQuery(text="repeated"))


def test_catalog_exposes_runtime_neutral_fields_and_structured_filters(tmp_path):
    (tmp_path / "trace.jsonl").write_text(
        '{"event_type":"agent_call","tool_name":"Agent","agent_id":"parent","target_agent_id":"child","parent_agent_id":"root","tool_call_id":"call-7","message_id":"msg-7","timestamp":"2026-01-01T00:00:01Z","arguments":{"description":"review security"},"result":{"status":"returned"}}\n',
        encoding="utf-8",
    )
    from agentjudge import EvidenceCatalog
    catalog = EvidenceCatalog.from_attempt_dir(tmp_path)
    record = catalog.search(EvidenceQuery(tool_name="Agent", parent_agent_id="root"))[0]
    assert record.event_type == "agent_call"
    assert record.actor_agent_id == "parent"
    assert record.target_agent_id == "child"
    assert record.message_id == "msg-7"
    assert record.content["arguments"]["description"] == "review security"
    assert record.content["result"]["status"] == "returned"
    assert catalog.query_trajectory()[-1]["operation"] == "search"


def test_catalog_generic_navigation_is_not_rubric_specific(tmp_path):
    (tmp_path / "trace.jsonl").write_text(
        '{"event_type":"agent_call","tool_name":"Agent","agent_id":"parent","target_agent_id":"child","tool_call_id":"call-8","timestamp":"2026-01-01T00:00:01Z"}\n'
        '{"event_type":"agent_end","agent_id":"child","parent_agent_id":"parent","tool_call_id":"call-8","timestamp":"2026-01-01T00:00:02Z","result":{"ok":true}}\n',
        encoding="utf-8",
    )
    from agentjudge import EvidenceCatalog
    catalog = EvidenceCatalog.from_attempt_dir(tmp_path)
    call = catalog.search(EvidenceQuery(tool_call_id="call-8"))[0]
    assert {r.evidence_id for r in catalog.call_context("call-8")} == {"trace.jsonl:1", "trace.jsonl:2"}
    assert catalog.related(call.evidence_id, "child")[0].agent_id == "child"
    assert catalog.related(call.evidence_id, "after")[0].evidence_id == "trace.jsonl:2"
