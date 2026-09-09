from __future__ import annotations

from agenteval.rubric_generation import build_memory, extract_task_features, retrieve


def test_features_do_not_read_checklist() -> None:
    case = {
        "instance_id": "q",
        "user_query": ["Fix the Python module and run pytest."],
        "checklist": {"secret": {"checks": [{"description": "do not leak"}]}},
    }
    features = extract_task_features(case)
    assert "python" in features["language_or_framework"]
    assert "run_tests" in features["required_operations"]
    assert "secret" not in str(features)


def test_retrieve_excludes_heldout() -> None:
    cases = [
        {"instance_id": "a", "user_query": ["Fix Python code"], "checklist": {}},
        {"instance_id": "b", "user_query": ["Fix Python code"], "checklist": {}},
    ]
    memory = [{
        "task_id": c["instance_id"],
        "task_text": c["user_query"][0],
        "task_features": extract_task_features(c),
        "human_rubrics": [],
    } for c in cases]
    result = retrieve(cases[0], memory, top_k=2, excluded_task_ids={"a"})
    assert result
    assert all(row["retrieved_task_id"] != "a" for row in result)


def test_build_memory_preserves_task_level_rubrics(tmp_path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    labels = tmp_path / "labels.json"
    dataset.write_text(
        '{"instance_id":"x","user_query":["Implement a Python feature"],'
        '"category":"User Query","checklist":{"User Query":{"checks":['
        '{"check_id":"c1","description":"Run tests"}]}}}\n',
        encoding="utf-8",
    )
    labels.write_text(
        '{"results":[{"instance_id":"x","User Query":{"checks":['
        '{"check_id":"c1","result":"success"}]}}]}\n',
        encoding="utf-8",
    )
    memory = build_memory(dataset, labels)
    assert len(memory) == 1
    assert memory[0]["human_rubrics"][0]["gold_label"] == "success"
    assert memory[0]["provenance_status"] == "aligned"
