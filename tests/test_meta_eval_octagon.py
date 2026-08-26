import json
import sqlite3

from agenteval.meta_eval import OctagonDiscovery


def test_octagon_discovery_reads_attempts_and_scores(tmp_path):
    root = tmp_path / "octagon"
    (root / "data" / "attempts" / "att_1").mkdir(parents=True)
    (root / "envs" / "env-a" / "tasks").mkdir(parents=True)
    (root / "data" / "attempts" / "att_1" / "trace.jsonl").write_text('{"x":1}\n')
    db = root / "data" / "octagon.db"
    c = sqlite3.connect(db)
    c.executescript("""
      create table attempts (id text, run_id text, task_id text, env_name text, status text, score_total real, model text, started_at text, ended_at text, created_at text);
      create table scores (attempt_id text, dimension text, value real);
      insert into attempts values ('att_1','run_1','task_1','env-a','completed',88,'model','s','e','1');
      insert into scores values ('att_1','quality',88);
    """)
    c.commit(); c.close()
    found = OctagonDiscovery(root).discover()
    assert len(found) == 1
    assert found[0].score_dimensions == {"quality": 88.0}
    assert found[0].has_trace
    assert len(OctagonDiscovery(root).environment_inventory()) == 1
