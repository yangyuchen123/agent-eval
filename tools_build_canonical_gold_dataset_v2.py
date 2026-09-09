from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path('/home/yang/agent-eval')
ARCHIVE = ROOT / 'archive/2026-08-31/project-history/run/meta_eval'
OUT = ROOT / 'run/meta_eval/canonical-gold-v2'
RB = Path('/home/yang/RuVerBench/data/benchmark')
HEALTH = ARCHIVE / 'healthbench-gold-v1'
SEED = 20260831


def load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stable_digest(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def flatten_checks(checklist: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section, value in checklist.items():
        if not isinstance(value, dict):
            continue
        for check in value.get('checks', []):
            out.append({
                'criterion_id': check['check_id'],
                'section': section,
                'description': check.get('description', ''),
                'check_type': check.get('check_type'),
            })
    return out


def coding_gold(labels: dict[str, Any], iid: str) -> list[dict[str, Any]]:
    row = next((x for x in labels['results'] if x['instance_id'] == iid), None)
    if row is None:
        return []
    out = []
    for section, value in row.items():
        if section == 'instance_id' or not isinstance(value, dict):
            continue
        for check in value.get('checks', []):
            if 'result' in check:
                out.append({
                    'criterion_id': check['check_id'],
                    'section': section,
                    'gold_label': check['result'] == 'success',
                    'gold_raw': check['result'],
                    'gold_source': 'RuVerBench agenticcoding_labels.json',
                })
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # Freeze the existing selected views; these are not resampled here.
    health_cases = load_jsonl(HEALTH / 'agent-eval-gold/cases.jsonl')
    dr_cases = load_jsonl(ARCHIVE / 'ruverbench-agent-eval-pilot-v1/cases.jsonl')
    code_cases = load_jsonl(ARCHIVE / 'ruverbench-agenticcoding-agent-eval-pilot-v1/cases.jsonl')

    health_source = load_jsonl(HEALTH / 'source/healthbench.jsonl')
    health_consensus = {x['prompt_id']: x for x in load_jsonl(HEALTH / 'source/healthbench_consensus.jsonl')}
    health_by_id = {x['prompt_id']: x for x in health_source}
    health_meta = load_jsonl(HEALTH / 'source/healthbench_meta_eval.jsonl')
    health_meta_by_prompt: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for x in health_meta:
        health_meta_by_prompt[x['prompt_id']].append(x)

    dr_dataset = {x['id']: x for x in load_json(RB / 'deepresearch_dataset.json')}
    dr_labels = {x['id']: x for x in load_json(RB / 'deepresearch_labels.json')}
    dr_responses = {x['id']: x for x in load_json(RB / 'deepresearch_responses.json')}
    dr_taxonomy = load_json(RB / 'deepresearch_taxonomy.json')
    dr_points = {f"{x['question_id']}::{x['point_index']}": x for x in dr_taxonomy['points']}

    code_dataset = {x['instance_id']: x for x in load_jsonl(RB / 'agenticcoding_dataset.jsonl')}
    code_labels = load_json(RB / 'agenticcoding_labels.json')
    code_traces = {x['meta']['session_id']: x for x in load_jsonl(RB / 'agenticcoding_trajectories.jsonl')}

    canonical: list[dict[str, Any]] = []
    criterion_gold: list[dict[str, Any]] = []
    legacy: list[dict[str, Any]] = []
    grouped: list[dict[str, Any]] = []

    # Group only tasks represented by the frozen legacy sample. Keep all source criteria.
    groups: dict[str, dict[str, Any]] = {}

    for case in health_cases:
        tid = case['prompt_id']
        src = health_by_id[tid]
        cons = health_consensus.get(tid, {})
        task_id = f'healthbench::{tid}'
        source_criteria = []
        consensus_criteria = []
        for i, rubric in enumerate(src.get('rubrics', [])):
            source_criteria.append({'criterion_id': f'{task_id}::rubric::{i}', 'index': i, 'text': rubric, 'source': 'healthbench.jsonl', 'rubric_set': 'source'})
        for i, rubric in enumerate(cons.get('rubrics', [])):
            consensus_criteria.append({'criterion_id': f'{task_id}::consensus_rubric::{i}', 'index': i, 'text': rubric, 'source': 'healthbench_consensus.jsonl', 'rubric_set': 'consensus'})
        # Keep source and consensus as separate rubric sets. Consensus is not an
        # additional criterion to be merged into the source rubric list.
        criteria = source_criteria
        meta_rows = health_meta_by_prompt.get(tid, [])
        selected_completion = next((x for x in meta_rows if x.get('completion_id') == case.get('completion_id')), None)
        if selected_completion:
            completion_ref = {'completion_id': selected_completion['completion_id'], 'completion': selected_completion.get('completion'), 'rubric': selected_completion.get('rubric'), 'physician_labels': selected_completion.get('binary_labels', case.get('physician_labels'))}
        else:
            completion_ref = {'completion_id': case.get('completion_id'), 'completion': case.get('completion'), 'rubric': case.get('rubric'), 'physician_labels': case.get('physician_labels')}
        task = {
            'task_id': task_id, 'benchmark': 'healthbench', 'source_task_ref': {'file': 'healthbench-gold-v1/source/healthbench.jsonl', 'prompt_id': tid},
            'request': src.get('prompt'), 'response': completion_ref.get('completion'), 'trajectory_ref': None, 'artifact_ref': None,
            'rubric_items': criteria, 'rubric_sets': {'source': source_criteria, 'consensus': consensus_criteria}, 'task_metadata': {'theme': case.get('broad_category'), 'category': case.get('category'), 'completion_id': case.get('completion_id'), 'available_completion_count': len(meta_rows)},
            'gold_status': 'candidate_requires_human_adjudication', 'gold_aggregation': 'criterion_only',
            'gold_notes': 'HealthBench source rubrics/consensus are preserved; no criterion-level AgentEval Gold is fabricated.',
            'provenance': {'source_files': ['healthbench.jsonl', 'healthbench_consensus.jsonl', 'healthbench_meta_eval.jsonl'], 'source_digests': {str(p.relative_to(ROOT)): digest(p) for p in [HEALTH/'source/healthbench.jsonl', HEALTH/'source/healthbench_consensus.jsonl', HEALTH/'source/healthbench_meta_eval.jsonl']}},
        }
        groups[task_id] = task
        legacy.append({'view_id': case['case_id']+'::M0', 'task_id': task_id, 'condition': 'M0_mechanical_single_rubric', 'selected_criterion_ids': [], 'adapter_rubric': case.get('rubric'), 'legacy_case_ref': case['case_id'], 'gold_ref': case.get('gold_expected_binary'), 'input_record': case})
        for c in source_criteria + consensus_criteria:
            criterion_gold.append({'task_id': task_id, 'benchmark': 'healthbench', **c, 'gold_label': None, 'gold_status': 'unadjudicated', 'gold_source': 'none', 'source_ref': task['source_task_ref']})

    for case in dr_cases:
        tid = case['instance_id']; src = dr_dataset[tid]; response = dr_responses[tid]; task_id = f'ruverbench_deepresearch::{tid}'
        criteria = []
        for i, rubric in enumerate(src.get('rubric', [])):
            pid = f'{tid}::{i}'; point = dr_points.get(pid, {})
            label = dr_labels[tid]['result']['coverage_results'][i]['covered']
            c = {'criterion_id': f'{task_id}::point::{i}', 'point_id': pid, 'index': i, 'text': rubric.get('point') if isinstance(rubric, dict) else rubric, 'category': point.get('category'), 'source': 'deepresearch_dataset.json'}
            criteria.append(c)
            criterion_gold.append({'task_id': task_id, 'benchmark': 'ruverbench_deepresearch', **c, 'gold_label': bool(label), 'gold_status': 'gold', 'gold_source': 'deepresearch_labels.json', 'source_ref': {'instance_id': tid, 'point_id': pid}})
        task = {'task_id': task_id, 'benchmark': 'ruverbench_deepresearch', 'source_task_ref': {'repo': '/home/yang/RuVerBench', 'file': 'data/benchmark/deepresearch_dataset.json', 'id': tid}, 'request': src.get('question'), 'response': response.get('response') if isinstance(response, dict) else response, 'trajectory_ref': None, 'artifact_ref': None, 'rubric_items': criteria, 'task_metadata': {'taxonomy_categories': sorted({c.get('category') for c in criteria if c.get('category')}), 'legacy_selected_point_ids': [x['point_id'] for x in dr_cases if x['instance_id'] == tid]}, 'gold_status': 'gold', 'gold_aggregation': 'criterion_only', 'gold_notes': 'RuVerBench provides criterion-level coverage labels; no task-level label is invented.', 'provenance': {'source_files': ['deepresearch_dataset.json', 'deepresearch_labels.json', 'deepresearch_responses.json', 'deepresearch_taxonomy.json'], 'source_digests': {str(p.relative_to(Path('/home/yang'))): digest(p) for p in [RB/'deepresearch_dataset.json', RB/'deepresearch_labels.json', RB/'deepresearch_responses.json', RB/'deepresearch_taxonomy.json']}}}
        groups[task_id] = task
        for x in dr_cases:
            if x['instance_id'] == tid:
                legacy.append({'view_id': x['case_id']+'::M0', 'task_id': task_id, 'condition': 'M0_mechanical_single_rubric', 'selected_criterion_ids': [f'{task_id}::point::{x["point_id"].split("::")[1]}'], 'legacy_case_ref': x['case_id'], 'gold_ref': x['gold_label'], 'input_record': x})

    for case in code_cases:
        iid = case['instance_id']; src = code_dataset[iid]; task_id = f'ruverbench_agenticcoding::{iid}'
        criteria = flatten_checks(src.get('checklist', {})); golds = {x['criterion_id']: x for x in coding_gold(code_labels, iid)}
        for c in criteria:
            g = golds.get(c['criterion_id'], {})
            criterion_gold.append({'task_id': task_id, 'benchmark': 'ruverbench_agenticcoding', **c, 'gold_label': g.get('gold_label'), 'gold_status': 'gold' if 'gold_label' in g else 'missing', 'gold_source': g.get('gold_source'), 'source_ref': {'instance_id': iid, 'check_id': c['criterion_id']}})
        task = {'task_id': task_id, 'benchmark': 'ruverbench_agenticcoding', 'source_task_ref': {'repo': '/home/yang/RuVerBench', 'file': 'data/benchmark/agenticcoding_dataset.jsonl', 'instance_id': iid}, 'request': src.get('user_query'), 'system_prompt': src.get('system_prompt'), 'response': None, 'trajectory_ref': {'repo': '/home/yang/RuVerBench', 'file': 'data/benchmark/agenticcoding_trajectories.jsonl', 'session_id': iid}, 'artifact_ref': {'workspace_abs_path': src.get('workspace_abs_path'), 'scaffold': src.get('scaffold')}, 'rubric_items': criteria, 'task_metadata': {'source_category': src.get('category'), 'check_sections': sorted({c['section'] for c in criteria}), 'legacy_selected_check_ids': [x['check_id'] for x in code_cases if x['instance_id'] == iid]}, 'gold_status': 'gold', 'gold_aggregation': 'criterion_only', 'gold_notes': 'RuVerBench AgenticCoding provides per-check labels; no task-level label is invented.', 'provenance': {'source_files': ['agenticcoding_dataset.jsonl', 'agenticcoding_labels.json', 'agenticcoding_trajectories.jsonl'], 'source_digests': {str(p.relative_to(Path('/home/yang'))): digest(p) for p in [RB/'agenticcoding_dataset.jsonl', RB/'agenticcoding_labels.json', RB/'agenticcoding_trajectories.jsonl']}}}
        groups[task_id] = task
        legacy.append({'view_id': case['case_id']+'::M0', 'task_id': task_id, 'condition': 'M0_mechanical_single_rubric', 'selected_criterion_ids': [f'{task_id}::criterion::{case["check_id"]}'], 'legacy_case_ref': case['case_id'], 'gold_ref': case['gold_label'], 'input_record': case})

    canonical = list(groups.values())
    for task in canonical:
        grouped.append({'task_id': task['task_id'], 'benchmark': task['benchmark'], 'criterion_ids': [x['criterion_id'] for x in task['rubric_items']], 'criterion_count': len(task['rubric_items']), 'gold_status': task['gold_status'], 'gold_aggregation': task['gold_aggregation'], 'canonical_task_ref': task['task_id']})

    # Stable ordering for reproducibility.
    canonical.sort(key=lambda x: x['task_id']); grouped.sort(key=lambda x: x['task_id']); legacy.sort(key=lambda x: x['view_id']); criterion_gold.sort(key=lambda x: (x['task_id'], x['criterion_id']))
    for name, rows in [('canonical_tasks.jsonl', canonical), ('criterion_gold.jsonl', criterion_gold), ('legacy_instance_views.jsonl', legacy), ('task_grouped_views.jsonl', grouped)]:
        (OUT / name).write_text('\n'.join(json.dumps(x, ensure_ascii=False, sort_keys=True) for x in rows) + '\n')

    source_paths = [HEALTH/'source/healthbench.jsonl', HEALTH/'source/healthbench_consensus.jsonl', HEALTH/'source/healthbench_meta_eval.jsonl', RB/'deepresearch_dataset.json', RB/'deepresearch_labels.json', RB/'deepresearch_responses.json', RB/'deepresearch_taxonomy.json', RB/'agenticcoding_dataset.jsonl', RB/'agenticcoding_labels.json', RB/'agenticcoding_trajectories.jsonl']
    manifest = {
        'schema_version': 'agenteval.canonical_gold_dataset.v2', 'created_date': '2026-09-01', 'status': 'frozen_index_not_resampled', 'seed_reference': SEED,
        'purpose': 'Restore task-level and original multi-rubric/check relationships while preserving legacy 60-instance Judge baseline.',
        'counts': {'canonical_tasks': len(canonical), 'criterion_gold_rows': len(criterion_gold), 'legacy_instances': len(legacy), 'benchmarks': dict(Counter(x['benchmark'] for x in canonical)), 'legacy_by_benchmark': dict(Counter(x['task_id'].split('::', 1)[0] for x in legacy))},
        'gold_policy': {'criterion_level': 'preserve source labels only; no invented task-level labels', 'healthbench': 'candidate/unadjudicated where applicable', 'task_level': 'source_defined_only'},
        'views': {'M0': 'legacy_instance_views.jsonl; mechanical one-criterion adapter', 'canonical': 'canonical_tasks.jsonl; full task context and all source criteria', 'grouped': 'task_grouped_views.jsonl; task clusters and criterion ids'},
        'source_digests': {str(p.relative_to(Path('/home/yang'))): digest(p) for p in source_paths},
        'output_digests': {},
        'selection_refs': {'healthbench': str(HEALTH/'manifest.json'), 'deepresearch': str(ARCHIVE/'ruverbench-agent-eval-pilot-v1/manifest.json'), 'agenticcoding': str(ARCHIVE/'ruverbench-agenticcoding-agent-eval-pilot-v1/manifest.json')},
        'rules': ['Do not alter raw source files.', 'M0 is a comparison condition, not the canonical task structure.', 'Multiple criteria from one task are clustered for statistical reporting.', 'Do not fabricate task-level Gold when source provides criterion-only labels.'],
    }
    for name in ['canonical_tasks.jsonl', 'criterion_gold.jsonl', 'legacy_instance_views.jsonl', 'task_grouped_views.jsonl']:
        manifest['output_digests'][name] = digest(OUT / name)
    (OUT/'dataset_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    audit = {'status': 'pass', 'checks': [], 'summary': manifest['counts']}
    audit['checks'].append({'name': 'legacy_count', 'expected': 60, 'actual': len(legacy), 'pass': len(legacy) == 60})
    audit['checks'].append({'name': 'canonical_task_ids_unique', 'pass': len({x['task_id'] for x in canonical}) == len(canonical)})
    audit['checks'].append({'name': 'criterion_ids_unique_within_task', 'pass': all(len({c['criterion_id'] for c in t['rubric_items']}) == len(t['rubric_items']) for t in canonical)})
    audit['checks'].append({'name': 'no_fabricated_task_gold', 'pass': all(t['gold_aggregation'] != 'inferred' for t in canonical)})
    audit['checks'].append({'name': 'source_files_exist', 'pass': all(p.exists() for p in source_paths)})
    audit['status'] = 'pass' if all(x.get('pass', False) for x in audit['checks']) else 'fail'
    (OUT/'dataset_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    report = f'''# Canonical Gold Dataset v2 恢复报告\n\n日期：2026-09-01\n\n## 目的\n\n在不修改外部原始数据、不重新运行 Judge/Harbor/Pi 的前提下，恢复当前 60-case Gold 样本背后的 task-level 关系和原始多 rubric/check 结构。\n\n## 结果\n\n- canonical task：{len(canonical)}\n- criterion-level rows：{len(criterion_gold)}\n- legacy Judge instances：{len(legacy)}\n- benchmark 分布：`{json.dumps(dict(Counter(x['benchmark'] for x in canonical)), ensure_ascii=False)}`\n\n## 三个视图\n\n- `canonical_tasks.jsonl`：每个原始 task/trajectory 一条，保留全部 source rubric/check。\n- `criterion_gold.jsonl`：每个 criterion/check 一条，保留 source Gold；没有推造 task-level label。\n- `legacy_instance_views.jsonl`：原有 60 个适配 instance，作为 M0 mechanical single-rubric 对照。\n- `task_grouped_views.jsonl`：按 task 聚合的 criterion 清单。\n\n## 重要限制\n\nHealthBench 当前 source rubrics/consensus 仍按 candidate/unadjudicated 处理，未将 AgentEval 历史输出反向当作 Gold。DeepResearch 和 AgenticCoding 保留 source criterion/check labels，但只声明 criterion-only Gold，因为源数据没有可靠的 task-level 聚合标签。\n\n## 后续最小实验\n\n先用存在多个 source criterion/check 的 task 构造 M0 vs M1。固定 response/trajectory、Gold、模型和阈值，只改变 rubric topology；不要先运行 dynamic planner 或 skill router。\n'''
    (OUT/'DATASET_RESTORATION_REPORT.md').write_text(report)
    print(json.dumps({'out': str(OUT), 'counts': manifest['counts'], 'audit': audit['status']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
