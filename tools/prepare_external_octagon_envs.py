#!/usr/bin/env python3
"""Materialize a declarative, replayable 10-task external benchmark slice."""
from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
ENVS=Path('/home/yang/agent-octagon-envs')
DEVAI=Path('/home/yang/DEVAI/instances')
AGENCY=Path('/home/yang/AgencyBench/AgencyBench-v2/Code')

DEVAI_IDS=[51,52,53,54,55]
DEVAI_FILES={i: next(DEVAI.glob(f'{i:02d}_*.json')) for i in DEVAI_IDS}
DEVAI_EXPECTED={
  51:['src/visualize.py','results/figures'],
  52:['src/env.py','src/data_loader.py','models/saved_models','results/metrics/finetuning_summary.txt'],
  53:['src/data_loader.py','models/saved_models','results/figures','results/metrics/model_performance_report.txt'],
  54:['src/frontend.py','src/message_list.py','src/backend.py','src/frontend_render.py'],
  55:['src/frontend.py','src/cache.py','src/backend.py','src/backend_logic.py','src/frontend_render.py'],
}
AGENCY_EXPECTED={
  1:['source/equation.py','source/analysis.py','source/evaluate_equation.py'],
  2:['README.md'],
  3:['subtask1_generator.py','domain'],
  4:['evaluation/task/evaluation.py'],
  5:['agents/research_agent.py','agents/research_agent_prompts.py','tests/test_research_agent_skeleton.py'],
}

def digest(p:Path)->str:
 h=hashlib.sha256()
 if p.is_file(): h.update(p.read_bytes())
 else:
  for q in sorted(p.rglob('*')):
   if q.is_file(): h.update(str(q.relative_to(p)).encode()); h.update(q.read_bytes())
 return h.hexdigest()

def write(p:Path,s:str): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(s,encoding='utf-8')

def common_files(env:str, title:str, prompt:str, expected:list[str], source_ref:str, source_digest:str):
 d=ENVS/env; d.mkdir(parents=True,exist_ok=True)
 meta={'name':env,'category':'external-benchmark','type':'coding','description':title,
       'dimensions':[{'name':'task_completion','weight':60,'description':'Required deliverables exist and are materially implemented.'},
                    {'name':'artifact_quality','weight':25,'description':'Artifacts are coherent, runnable or structurally valid for the task.'},
                    {'name':'validation_evidence','weight':15,'description':'Agent provides or creates tests, checks, or validation evidence.'}],
       'pass_threshold':60,'prerequisites':[],'materials':{'agent':['source']} if (d/'source').exists() else {'agent':[]},
       'provenance':{'benchmark':'DEVAI' if 'devai' in env else 'AgencyBench','source_ref':source_ref,'source_digest':source_digest},
       'task_adaptation':{'expected_artifacts':expected,'adaptation':'Converted benchmark query into one Octagon coding task; workspace paths are relative and external credentials/services are optional.'}}
 write(d/'meta.yaml', __import__('yaml').safe_dump(meta,allow_unicode=True,sort_keys=False))
 write(d/'core.py','"""No business tools; agents use native workspace tools."""\n')
 write(d/'tasks'/(env+'_001.json'),json.dumps({'id':env+'_001','env_name':env,'prompt':prompt,'constraints':{'expected_files':expected,'source_root':'source'},'timeout_seconds':900},ensure_ascii=False,indent=2)+'\n')
 write(d/'scorer.py', (ROOT/'tools'/'external_octagon_scorer.py').read_text())
 write(d/'README.md',f'# {title}\n\nAdapted from `{source_ref}`.\n')

def main():
    for i,p in DEVAI_FILES.items():
        src=json.load(open(p)); prompt=(src.get('query') or '')+'\n\nAdaptation requirements: work only in the Octagon workspace; do not depend on private credentials. If an upstream download or GPU/API is unavailable, implement a reproducible offline/mock fallback and document it in the requested report. Create all requested paths and leave validation evidence.'
        env=f'external-devai-{i}-{["hidden-messages","qlora","road-damage","openai-response-analyzer","sqlite-viewer"][i-51]}'
        common_files(env,src['name'],prompt,DEVAI_EXPECTED[i],str(p),digest(p))
    for i in range(1,6):
        p=AGENCY/f'scenario{i}'; env=f'external-agencybench-code-{i}-'+['reaction-rate','repo-review','event-generator','graph-algorithm','deep-research'][i-1]
        src=json.load(open(p/'description.json')); prompt='Adapted AgencyBench coding task. Work only inside the current Octagon workspace. The original benchmark used model-specific absolute paths; use relative paths under this workspace instead.\n\n'+'\n\n'.join(str(src[k]) for k in sorted(src) if k.startswith('subtask'))+'\n\nCreate a runnable implementation, preserve supplied source materials, and add tests or validation evidence. Avoid requiring secrets; use mocks/offline fixtures when external services are unavailable.'
        target=ENVS/env/'source'
        if target.exists(): shutil.rmtree(target)
        shutil.copytree(p, target, ignore=shutil.ignore_patterns('.env','__pycache__','*.pyc','description.json','eval_task.py','claude'))
        common_files(env,f'AgencyBench Code scenario {i}',prompt,AGENCY_EXPECTED[i],str(p),digest(p))
    manifest={'schema_version':'external-bench-octagon-slice.v1','created':'2026-09-02','dataset':{'DEVAI':[str(x) for x in DEVAI_FILES.values()],'AgencyBench':[str(AGENCY/f'scenario{i}') for i in range(1,6)]},'selection':{'DEVAI':DEVAI_IDS,'AgencyBench':list(range(1,6))},'task_count':10,'adaptation':'One source scenario -> one Octagon env/task; original prompts retained and normalized to relative workspace paths.','scorer':'tools/external_octagon_scorer.py@external-octagon-scorer-v1'}
    write(ROOT/'experiments/external-bench-octagon-20260902/dataset_manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
