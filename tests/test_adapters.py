from __future__ import annotations

import json
from pathlib import Path

import pytest

from agenteval import (
    AgentIdentity,
    ArtifactRef,
    ConversationTurn,
    EvalSample,
    JsonRuntimeAdapter,
    ToolCall,
)


def test_eval_sample_projects_multiturn_runtime_data_to_case():
    sample = EvalSample(
        sample_id="sample-1",
        task_id="env/task@1",
        task="Complete the task",
        output="done",
        agent=AgentIdentity(name="codex", model="model-1"),
        backend="agent-octagon",
        artifacts=(ArtifactRef(path="artifacts/report.md", role="primary"),),
        conversation=(ConversationTurn(
            turn_id="turn-1",
            role="assistant",
            content="I will inspect the workspace",
            tool_calls=(ToolCall(call_id="call-1", name="ls"),),
        ),),
        environment={"name": "demo-env", "scorer_version": "v2"},
    )

    case = sample.to_case()
    assert case.case_id == "sample-1"
    assert case.metadata["task_id"] == "env/task@1"
    assert case.context["backend"] == "agent-octagon"
    assert case.context["conversation"][0]["tool_calls"][0]["name"] == "ls"
    assert case.context["artifacts"][0]["path"] == "artifacts/report.md"


def test_json_runtime_adapter_rejects_duplicate_ids(tmp_path: Path):
    path = tmp_path / "samples.json"
    path.write_text(json.dumps({"samples": [
        {"sample_id": "same", "task": "a"},
        {"sample_id": "same", "task": "b"},
    ]}))
    with pytest.raises(ValueError, match="duplicate"):
        JsonRuntimeAdapter(path).iter_samples()


def test_json_runtime_adapter_roundtrip(tmp_path: Path):
    path = tmp_path / "samples.json"
    path.write_text(json.dumps({"samples": [{
        "sample_id": "s1",
        "task_id": "t1",
        "task": "task",
        "output": "answer",
        "backend": "harbor",
        "agent": {"name": "agent", "model": "m"},
        "conversation": [{"turn_id": "1", "role": "user", "content": "task"}],
    }]}))
    samples = JsonRuntimeAdapter(path).iter_samples()
    assert len(samples) == 1
    assert samples[0].backend == "harbor"
    assert samples[0].conversation[0].content == "task"


def test_agent_octagon_adapter_reads_attempt_database_and_files(tmp_path: Path):
    import sqlite3

    data = tmp_path / "data"
    attempt = data / "attempts" / "att_1"
    workspace = attempt / "skill_workspace"
    workspace.mkdir(parents=True)
    (workspace / "report.md").write_text("# done\n", encoding="utf-8")
    (attempt / "conversation.jsonl").write_text(
        json.dumps({"event": "turn.started", "turn_id": "t1", "purpose": "task"}) + "\n",
        encoding="utf-8",
    )
    (attempt / "trace.jsonl").write_text(
        json.dumps({"tool_name": "Read", "arguments": {"path": "report.md"}, "turn_id": "t1"}) + "\n",
        encoding="utf-8",
    )
    (attempt / "final_state.json").write_text(json.dumps({"done": True}), encoding="utf-8")

    conn = sqlite3.connect(data / "octagon.db")
    conn.executescript("""
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY, env_name TEXT, prompt TEXT,
            context_json TEXT, constraints_json TEXT,
            timeout_seconds INTEGER, source TEXT, created_at TEXT
        );
        CREATE TABLE attempts (
            id TEXT PRIMARY KEY, run_id TEXT, task_id TEXT, env_name TEXT,
            agent_name TEXT, model TEXT, status TEXT, score_total INTEGER,
            error_code TEXT, error_message TEXT, created_at TEXT,
            execution_status TEXT, scoring_status TEXT
        );
        CREATE TABLE scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id TEXT,
            dimension TEXT, value REAL, detail TEXT,
            scored_at TEXT, evaluation_manifest_ref TEXT
        );
    """)
    conn.execute("INSERT INTO tasks VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                 ("task-1", "demo-env", "Do it", "{}", "{}", 60, "file", "now"))
    conn.execute("INSERT INTO attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                 ("att_1", "run_1", "task-1", "demo-env", "codex", "model-x",
                  "completed", 80, None, None, "now", "completed", "completed"))
    conn.execute("INSERT INTO scores VALUES (?, ?, ?, ?, ?, ?, ?)",
                 (None, "att_1", "quality", 80, "good", None, "manifest-1"))
    conn.commit()
    conn.close()

    from agenteval import AgentOctagonAdapter
    samples = AgentOctagonAdapter(data).iter_samples()
    assert len(samples) == 1
    sample = samples[0]
    assert sample.sample_id == "att_1"
    assert sample.task_id == "task-1"
    assert sample.backend == "agent-octagon"
    assert sample.agent.model == "model-x"
    assert sample.output == "# done\n"
    assert sample.artifacts[0].path == "skill_workspace/report.md"
    assert sample.conversation[0].turn_id == "t1"
    assert sample.conversation[0].tool_calls[0].name == "Read"
    assert sample.context["final_state"] == {"done": True}
    assert sample.runtime_result["scores"][0]["dimension"] == "quality"


def test_agent_octagon_adapter_uses_blade_history_fallback(tmp_path: Path):
    import sqlite3
    data = tmp_path / "data"
    attempt = data / "attempts" / "att_legacy"
    attempt.mkdir(parents=True)
    (attempt / "blade_history.json").write_text(json.dumps({"nodes": [
        {"id": "u1", "kind": "message", "role": "user", "content": "task"},
        {"id": "a1", "kind": "message", "role": "assistant", "content": "done",
         "tool_calls": [{"id": "c1", "function": {"name": "Bash", "arguments": "{}"}}]},
    ]}), encoding="utf-8")
    conn = sqlite3.connect(data / "octagon.db")
    conn.executescript("""
        CREATE TABLE tasks (id TEXT, env_name TEXT, prompt TEXT, context_json TEXT,
            constraints_json TEXT, timeout_seconds INTEGER, source TEXT, created_at TEXT);
        CREATE TABLE attempts (id TEXT, run_id TEXT, task_id TEXT, env_name TEXT,
            agent_name TEXT, model TEXT, status TEXT, score_total INTEGER,
            error_code TEXT, error_message TEXT, created_at TEXT,
            execution_status TEXT, scoring_status TEXT);
        CREATE TABLE scores (id INTEGER, attempt_id TEXT, dimension TEXT, value REAL,
            detail TEXT, scored_at TEXT, evaluation_manifest_ref TEXT);
    """)
    conn.execute("INSERT INTO tasks VALUES ('t','e','p','{}','{}',60,'file','now')")
    conn.execute("INSERT INTO attempts VALUES ('att_legacy','r','t','e','blade',NULL,'completed',1,NULL,NULL,'now','completed','completed')")
    conn.commit(); conn.close()
    from agenteval import AgentOctagonAdapter
    sample = AgentOctagonAdapter(data).iter_samples()[0]
    assert [turn.role for turn in sample.conversation] == ["user", "assistant"]
    assert sample.conversation[1].tool_calls[0].name == "Bash"


def test_octagon_scorer_bridge_normalizes_environment_scores(tmp_path: Path):
    env_root = tmp_path / "envs" / "demo-env"
    env_root.mkdir(parents=True)
    (env_root / "meta.yaml").write_text(
        "name: demo-env\npass_threshold: 70\ndimensions:\n"
        "  - name: correctness\n    weight: 75\n"
        "  - name: format\n    weight: 25\n",
        encoding="utf-8",
    )
    (env_root / "scorer.py").write_text(
        "def score(*, attempt_id, task, env_db=None, trace=None, final_state=None, events=None):\n"
        "    return [{'dimension': 'correctness', 'value': 80, 'detail': 'ok'},\n"
        "            {'dimension': 'format', 'value': 100, 'detail': 'ok'}]\n",
        encoding="utf-8",
    )
    from agenteval import OctagonScorerBridge
    sample = EvalSample(
        sample_id="att-1", task_id="task-1", task="do it",
        attempt_id="att-1", environment={"name": "demo-env"},
        context={"task": {"id": "task-1", "prompt": "do it"}},
    )
    result = OctagonScorerBridge(tmp_path / "envs").score(sample)
    assert result.status == "ok"
    assert result.score == 0.85
    assert result.subscores["correctness"] == 80.0
    assert result.evidence["scorer_manifest"]["env_name"] == "demo-env"


def test_octagon_runtime_client_create_and_wait(monkeypatch):
    import io
    import json as json_module
    from agenteval import AgentOctagonRuntimeClient

    calls = []
    responses = [
        {"run_id": "run-1", "status": "created"},
        {"run_id": "run-1", "status": "running"},
        {"run_id": "run-1", "status": "completed", "attempts": []},
    ]

    class Response:
        def __init__(self, value):
            self.value = value
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return json_module.dumps(self.value).encode()

    def fake_urlopen(request, timeout):
        calls.append((request.method, request.full_url, json_module.loads(request.data) if request.data else None))
        return Response(responses.pop(0))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AgentOctagonRuntimeClient("http://octagon.test", request_timeout=2)
    created = client.create_run(env_name="demo", task_id="task-1", agents=["codex"], model="m")
    finished = client.wait_run(created.run_id, timeout=1, poll_interval=0)
    assert finished.status == "completed"
    assert calls[0][0:2] == ("POST", "http://octagon.test/api/runs")
    assert calls[0][2]["env_name"] == "demo"
    assert calls[1][1].endswith("/api/runs/run-1")


def test_octagon_runtime_client_run_does_not_forward_wait_options(monkeypatch):
    from agenteval import AgentOctagonRuntimeClient
    client = AgentOctagonRuntimeClient()
    seen = {}
    monkeypatch.setattr(client, "create_run", lambda **kwargs: seen.update(kwargs) or type("R", (), {"run_id": "r"})())
    monkeypatch.setattr(client, "wait_run", lambda run_id, **kwargs: (run_id, kwargs))
    assert client.run(env_name="e", task_id="t", agents=["a"], wait_timeout=3, poll_interval=0) == ("r", {"timeout": 3.0, "poll_interval": 0.0})
    assert "wait_timeout" not in seen and "poll_interval" not in seen


def test_octagon_llm_judge_receives_deterministic_score(tmp_path: Path):
    from agenteval import LLMBackend, OctagonScorerBridge
    from agenteval.adapters.octagon_scorer import OctagonLLMJudgeSkill

    env = tmp_path / "envs" / "demo"
    env.mkdir(parents=True)
    (env / "scorer.py").write_text(
        "def score(**kwargs): return [{'dimension': 'exact', 'value': 80, 'detail': 'det ok'}]\n",
        encoding="utf-8",
    )
    data = tmp_path / "data"
    attempt = data / "attempts" / "a1"
    attempt.mkdir(parents=True)
    sample = EvalSample(sample_id="a1", task_id="t1", task="Do X", output="done", environment={"name": "demo"}, context={"attempt_dir": str(attempt)})
    # The bridge needs only the persisted attempt id and environment; use the
    # reconstruction payload generated by to_case().
    backend = LLMBackend(base_url="http://judge", model="judge")
    seen = {}
    def fake_infer(messages):
        seen["prompt"] = messages[-1]["content"]
        return {"parsed": {"score": 0.6, "subscores": {"semantic": 0.6}, "reasons": {"semantic": "covered"}, "confidence": 0.9}, "response_metadata": {}}
    backend.infer = fake_infer  # type: ignore[method-assign]
    skill = OctagonLLMJudgeSkill(backend, OctagonScorerBridge(tmp_path / "envs"), "Must satisfy X")
    result = skill.evaluate(sample.to_case(), sample.output)
    assert result.score == 0.6
    assert result.evidence["deterministic_environment_score"]["score"] == 0.8
    assert "deterministic_environment_score" in seen["prompt"]


def test_octagon_llm_judge_supports_pure_judge_without_environment_scorer():
    from agenteval import LLMBackend
    from agenteval.adapters.octagon_scorer import OctagonLLMJudgeSkill

    sample = EvalSample(sample_id="pure", task_id="t", task="Judge this", output="answer")
    backend = LLMBackend(base_url="http://judge", model="judge")
    backend.infer = lambda messages: {  # type: ignore[method-assign]
        "parsed": {"score": 0.75, "subscores": {"quality": 0.75}, "reasons": {"quality": "good"}},
        "response_metadata": {},
    }
    skill = OctagonLLMJudgeSkill(backend, bridge=None, rubric="Quality")
    result = skill.evaluate(sample.to_case(), sample.output)
    assert result.score == 0.75
    assert result.evidence["deterministic_environment_score"] is None


def test_octagon_llm_judge_generates_case_rubric_from_meta_rubric():
    from agenteval import LLMBackend, MetaPrinciple, MetaRubric, RubricPlanner
    import json
    from agenteval.adapters.octagon_scorer import OctagonLLMJudgeSkill

    sample = EvalSample(sample_id="generated", task_id="t", task="Plan safely", output="plan")
    backend = LLMBackend(base_url="http://judge", model="judge")
    calls = []
    responses = [
        {"parsed": {"rubric_id": "case", "version": "1", "description": "adapted", "questions": [
            {"id": "grounded", "question": "Is the plan grounded?", "anchors": "1 grounded; 0.5 partial; 0 invented", "score_anchors": [{"score": 0, "description": "invented"}, {"score": 0.5, "description": "partly grounded"}, {"score": 1, "description": "grounded"}], "evidence": "output", "lineage": ["grounding"], "source_principles": ["grounding"], "case_adaptation": "apply to planning"}
        ], "provenance": {}}, "response_metadata": {}},
        {"parsed": {"score": 0.8, "subscores": {"grounded": 1.0}, "reasons": {"grounded": "grounded"}}, "response_metadata": {}},
    ]
    def fake_infer(messages):
        calls.append(messages)
        return responses.pop(0)
    backend.infer = fake_infer  # type: ignore[method-assign]
    meta = MetaRubric("human", "1", "human preferences", (
        MetaPrinciple("grounding", "Grounding", "Do not invent facts", source_examples=("p1",)),
    ), source_examples=("p1",))
    skill = OctagonLLMJudgeSkill(
        backend, rubric_planner=RubricPlanner(backend), meta_rubric=meta
    )
    result = skill.evaluate(sample.to_case(), sample.output)
    assert result.score == 1.0
    assert result.diagnostics["model_reported_score"] == 0.8
    assert result.diagnostics["score_aggregation"] == "weighted_structured_anchors"
    packet = json.loads(calls[1][-1]["content"])
    assert json.loads(packet["rubric"])["rubric_id"] == "case"
    assert result.evidence["rubric_provenance"]["source_meta_rubric"] == "human"


def test_octagon_judge_preserves_trace_arguments_and_agent_lifecycle():
    from agenteval.adapters.octagon_scorer import OctagonLLMJudgeSkill

    trace = [{
        "tool_name": "Agent", "timestamp": "t1",
        "arguments": {"description": "dispatch WP-01", "prompt": "review"},
        "result": "returned findings", "tool_call_id": "call-1",
    }]
    events = [{
        "kind": "agent:start", "timestamp": "t1",
        "raw": {"payload": {"loop_name": "agent:a", "description": "dispatch WP-01", "parent_fork_tool_call_id": "call-1"}},
    }, {
        "kind": "agent:end", "timestamp": "t2",
        "raw": {"payload": {"loop_name": "agent:a", "description": "dispatch WP-01", "ok": True}},
    }]
    compact = OctagonLLMJudgeSkill._compact_records(trace)
    assert compact[0]["arguments"]
    assert compact[0]["result"] == "returned findings"
    lifecycle = OctagonLLMJudgeSkill._agent_lifecycle(events)
    assert [x["kind"] for x in lifecycle] == ["agent:start", "agent:end"]
    assert lifecycle[0]["loop_name"] == "agent:a"


def test_octagon_judge_uses_semantic_trajectory_and_wire_layers():
    import json
    from agenteval import LLMBackend
    from agenteval.adapters.octagon_scorer import OctagonLLMJudgeSkill

    sample = EvalSample(
        sample_id="semantic", task_id="t", task="Do it", output="done",
        context={
            "trajectory": {"schema_version": "octagon-trajectory-v1", "steps": [
                {"sequence": 1, "kind": "tool_call", "agent_id": "agent:a", "tool_name": "Agent", "tool_call_id": "call-1"},
            ]},
            "wire": [{
                "schema_version": "octagon-wire-v1", "record_type": "llm_call",
                "phase": "agent_run", "record_id": "wr-1",
                "correlation": {"agent_id": "agent:a", "parent_agent_id": "main"},
                "time": {"timestamp": "t1"},
                "data": {"call_role": "subagent", "finish_reason": "stop", "usage": {"output_tokens": 3}},
            }],
            "trace": [{"tool_name": "Agent", "arguments": {"prompt": "raw"}}],
            "events": [{"kind": "llm:content:delta", "raw": {"payload": {"content": "raw token"}}}],
        },
    )
    skill = OctagonLLMJudgeSkill(LLMBackend("http://judge", "judge"), rubric="R")
    packet = json.loads(skill.messages(sample.to_case(), sample.output)[1]["content"])
    assert "evidence index" in packet["runtrace"]["source"]
    assert packet["runtrace"]["evidence_manifest"]["record_count"] == 2
    assert packet["runtrace"]["evidence_manifest"]["query"]["name"] == "grep_runtime_evidence"
    assert "raw token" not in json.dumps(packet["runtrace"], ensure_ascii=False)


def test_octagon_runtrace_prompt_is_compact():
    import json
    from agenteval import LLMBackend
    from agenteval.adapters.octagon_scorer import OctagonLLMJudgeSkill

    steps = [
        {"sequence": i, "step_id": f"step-{i}", "timestamp": "t", "agent_id": "a",
         "kind": "tool_call", "tool_call_id": f"call-{i}", "tool_name": "Read",
         "logical_call_id": f"logical-{i}", "producer_event_refs": [{"file": "events.jsonl", "line": i}],
         "content_hash": "x" * 64, "content_bytes": 999999}
        for i in range(1000)
    ]
    sample = EvalSample(
        sample_id="bounded", task_id="t", task="Do it", output="done",
        context={"trajectory": {"steps": steps}, "wire": []},
    )
    skill = OctagonLLMJudgeSkill(LLMBackend("http://judge", "judge"), rubric="R")
    packet = json.loads(skill.messages(sample.to_case(), sample.output)[1]["content"])
    assert "trajectory" not in packet["runtrace"]
    assert packet["runtrace"]["trajectory_steps"] == 1000
    assert len(json.dumps(packet, ensure_ascii=False)) < 100_000


def test_runtime_evidence_index_preserves_content_and_excludes_deltas():
    from agenteval.adapters.runtime_evidence import RuntimeEvidenceIndex
    index = RuntimeEvidenceIndex.from_sample_context({
        "trace": [{"tool_name": "Agent", "arguments": {"description": "dispatch security"}, "result": "handoff complete"}],
        "events": [{"kind": "llm:content:delta", "raw": {"payload": {"content": "secret repeated"}}}, {"kind": "agent:end", "raw": {"payload": {"description": "security done"}}}],
    })
    manifest = index.manifest()
    assert manifest["record_count"] == 2
    result = index.grep("security")
    assert result["count"] == 2
    assert "handoff complete" in str(result)
    assert "secret repeated" not in str(result)


def test_runtime_evidence_index_filters_by_agent():
    from agenteval.adapters.runtime_evidence import RuntimeEvidenceIndex
    index = RuntimeEvidenceIndex.from_sample_context({"trace": [
        {"agent_id": "a", "tool_name": "Agent", "arguments": {"description": "requirements"}},
        {"agent_id": "b", "tool_name": "Agent", "arguments": {"description": "security"}},
    ]})
    result = index.grep("Agent", agent_id="b")
    assert result["count"] == 1
    assert result["hits"][0]["record"]["agent_id"] == "b"
