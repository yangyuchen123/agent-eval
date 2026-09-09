#!/usr/bin/env python3
"""Run AgentEval's autonomous evidence Judge repeatedly on the frozen Octagon 5-case set."""
from __future__ import annotations
import asyncio, hashlib, json, os, statistics, time
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent
FIX=ROOT/'meta_eval/octagon_llm_judge_5case_v1'
OUT=ROOT/'run/meta_eval/agent-eval-octagon-fixed-5case-stability-20260902'
JUDGE_SRC=ROOT/'judge/src'
import sys
sys.path.insert(0,str(JUDGE_SRC))

from agentjudge.catalog import EvidenceCatalog
from agentjudge.models import JudgeRequest
from agentjudge.service import QuestionJudgeService
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


def load_dotenv():
    p=ROOT/'.env'
    if p.is_file():
        for line in p.read_text().splitlines():
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1); os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def load_json(path): return json.loads(Path(path).read_text())

def rubric_for(task):
    env=Path('/home/yang/agent-octagon-envs')/task['env']
    if task['env']=='gdpval-source-faithfulness-official':
        return {'rubric_id':'gdpval-official-rubric','version':digest(env/'private/official_rubric.json')[:16], 'official_rubric':load_json(env/'private/official_rubric.json')}
    if task['env'].startswith('presentbench-'):
        common=load_json(env/'private/common_judge_prompt.json')
        specific=load_json(env/'private/judge_prompt.json')
        weights=(env/'private/judge_weights.yaml').read_text()
        return {'rubric_id':'presentbench-official-rubric','version':digest(env/'private/judge_prompt.json')[:16], 'common_checklist':common, 'task_checklist':specific, 'weights_yaml':weights}
    if task['env']=='user-programming-scenario-visitor-appointment':
        return {'rubric_id':'visitor-product-rubric','version':digest(env/'private/product_judge_rubric.json')[:16], 'official_rubric':load_json(env/'private/product_judge_rubric.json')}
    if task['env']=='user-programming-scenario-weather-forecast':
        return {'rubric_id':'weather-ui-rubric','version':digest(env/'private/ui_judge_rubric.json')[:16], 'official_rubric':load_json(env/'private/ui_judge_rubric.json')}
    raise ValueError(task['env'])


def question_rows(task, rubric):
    rows=[]
    for i,d in enumerate(task['judge_dimensions']):
        qid=d['name']
        rows.append({'id':qid, 'question':d['description'], 'description':d['description'],
                     'weight':d.get('weight',0),
                     'score_anchors':[
                       {'score':0.0,'label':'not_satisfied','description':'The criterion is not satisfied, or the supplied runtrace does not provide sufficient direct evidence.'},
                       {'score':0.5,'label':'partially_satisfied','description':'The criterion is partially satisfied or evidence is mixed/incomplete.'},
                       {'score':1.0,'label':'satisfied','description':'The criterion is satisfied by direct, case-relevant evidence in the supplied runtrace.'},
                     ]})
    return rows


def task_case(task, rubric):
    trace_dir=FIX/'runtraces'/task['canonical_attempt']['attempt_id']
    catalog=EvidenceCatalog.from_attempt_dir(trace_dir)
    records=[r.model_dump() for r in catalog.records]
    trace_digest=next(x['sha256'] for x in task['runtrace']['files'] if x['name']=='trace.jsonl')
    return {'task':task['task_snapshot']['prompt'], 'env_name':task['env'], 'task_id':task['task_id'], 'case_id':task['task_id']}, records, trace_digest

async def main_async():
    load_dotenv()
    repeats=int(os.environ.get('AGENTEVAL_STABILITY_REPEATS','5'))
    concurrency=int(os.environ.get('AGENTEVAL_STABILITY_CONCURRENCY','4'))
    model_id=os.environ.get('JUDGE_MODEL','gpt-5.6-luna')
    base_url=os.environ.get('JUDGE_BASE_URL')
    api_key=os.environ.get('JUDGE_API_KEY') or os.environ.get('OPENAI_API_KEY')
    if not base_url or not api_key: raise SystemExit('JUDGE_BASE_URL and JUDGE_API_KEY/OPENAI_API_KEY are required')
    tasks=[json.loads(x) for x in (FIX/'tasks.jsonl').read_text().splitlines() if x.strip()]
    prepared=[]
    for task in tasks:
        rub=rubric_for(task); case,records,td=task_case(task,rub)
        prepared.append((task,rub,case,records,td,question_rows(task,rub)))
    OUT.mkdir(parents=True,exist_ok=True)
    manifest={'schema_version':'agenteval.judge_stability_run.v1','dataset_id':'octagon_llm_judge_5case_v1','run_date':'2026-09-02','repeats':repeats,'concurrency':concurrency,'model':model_id,'base_url':base_url,'protocol':'single_question_agentic_evidence','score_anchors':[0,0.5,1],'cases':[{'task_id':t['task_id'],'attempt_id':t['canonical_attempt']['attempt_id'],'trace_sha256':td,'rubric':rub} for t,r,c,rec,td,qs in prepared]}
    (OUT/'run_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    model=OpenAIChatModel(model_id,provider=OpenAIProvider(base_url=base_url,api_key=api_key))
    sem=asyncio.Semaphore(concurrency)
    async def one(task,rub,case,records,td,q,rep):
        async with sem:
            started=time.perf_counter()
            try:
                from agentjudge.models import EvidenceRecord
                provider=EvidenceCatalog([EvidenceRecord.model_validate(r) for r in records])
                service=QuestionJudgeService(model,provider)
                req=JudgeRequest(case=case,rubric=rub,rubric_question=q,agent_output='',trace_ref={'attempt_id':task['canonical_attempt']['attempt_id'],'trace_sha256':td},metadata={'dataset_id':'octagon_llm_judge_5case_v1','task_id':task['task_id'],'repeat':rep,'agent_eval':True,'system_failure_policy':'filter system/infrastructure/capture/evaluator records; retain agent-visible failures'})
                j=await service.evaluate(req)
                return {'task_id':task['task_id'],'env':task['env'],'criterion_id':q['id'],'repeat':rep,'score':j.score,'status':j.status,'confidence':j.confidence,'evidence_refs':j.evidence_refs,'missing_evidence':j.missing_evidence,'contradictions':j.contradictions,'claims':[c.model_dump() for c in j.claims],'query_trajectory':service.last_query_trajectory,'scoring_provenance':service.last_scoring_provenance,'usage':service.last_usage,'latency_ms':(time.perf_counter()-started)*1000}
            except Exception as e:
                return {'task_id':task['task_id'],'env':task['env'],'criterion_id':q['id'],'repeat':rep,'score':None,'status':'judge_error','error':repr(e),'evidence_refs':[],'claims':[],'latency_ms':(time.perf_counter()-started)*1000}
    jobs=[one(t,r,c,rec,td,q,rep) for rep in range(1,repeats+1) for t,r,c,rec,td,qs in prepared for q in qs]
    rows=[]
    for i,coro in enumerate(asyncio.as_completed(jobs),1):
        row=await coro; rows.append(row)
        if i%5==0 or row.get('error'): print(f"{i}/{len(jobs)} {row['task_id']}::{row['criterion_id']} r{row['repeat']} score={row['score']} status={row['status']}" + (f" ERROR {row['error']}" if row.get('error') else ''),flush=True)
    rows.sort(key=lambda x:(x['repeat'],x['task_id'],x['criterion_id']))
    (OUT/'judgments.jsonl').write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in rows)+'\n')
    groups=defaultdict(list)
    for x in rows: groups[(x['task_id'],x['criterion_id'])].append(x)
    per={}
    for (tid,cid),rs in groups.items():
        valid=[x for x in rs if x['score'] is not None]
        scores=[x['score'] for x in valid]; statuses=[x['status'] for x in rs]
        refs=[set(x.get('evidence_refs',[])) for x in valid]
        pairs=[(scores[i],scores[j]) for i in range(len(scores)) for j in range(i+1,len(scores))]
        per[f'{tid}::{cid}']={'n':len(rs),'valid_n':len(valid),'error_n':len(rs)-len(valid),'scores':scores,'mean':statistics.mean(scores) if scores else None,'population_std':statistics.pstdev(scores) if len(scores)>1 else 0.0 if scores else None,'range':max(scores)-min(scores) if scores else None,'exact_score_agreement':len(set(scores))==1 if scores else None,'pairwise_score_agreement':statistics.mean(a==b for a,b in pairs) if pairs else None,'exact_status_agreement':len(set(statuses))==1,'status_counts':dict((s,statuses.count(s)) for s in sorted(set(statuses))), 'mean_evidence_jaccard':statistics.mean(len(a&b)/len(a|b) if a|b else 1.0 for i,a in enumerate(refs) for b in refs[i+1:]) if len(refs)>1 else None}
    eligible=[t['task_id'] for t in tasks if t.get('case_eligibility',{}).get('status')=='eligible']
    vals=list(per.values()); exact=[x['exact_score_agreement'] for x in vals if x['exact_score_agreement'] is not None]
    summary={'schema_version':'agenteval.judge_stability_summary.v1','dataset_id':'octagon_llm_judge_5case_v1','task_n':len(tasks),'eligible_task_n':len(eligible),'criterion_n':len(vals),'repeat_n':repeats,'observation_n':len(rows),'valid_observation_n':sum(x['valid_n'] for x in vals),'judge_error_n':sum(x['error_n'] for x in vals),'eligible_tasks':eligible,'overall':{'exact_score_agreement_rate':statistics.mean(exact) if exact else None,'all_repeat_scores_same_n':sum(exact),'any_score_flip_n':sum(1 for x in exact if not x),'mean_population_std':statistics.mean(x['population_std'] for x in vals if x['population_std'] is not None),'mean_score_range':statistics.mean(x['range'] for x in vals if x['range'] is not None),'mean_pairwise_score_agreement':statistics.mean(x['pairwise_score_agreement'] for x in vals if x['pairwise_score_agreement'] is not None),'mean_evidence_jaccard':statistics.mean(x['mean_evidence_jaccard'] for x in vals if x['mean_evidence_jaccard'] is not None)},'by_criterion':per}
    (OUT/'metrics.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ['task_n','criterion_n','repeat_n','observation_n','valid_observation_n','judge_error_n','overall']},ensure_ascii=False,indent=2))

if __name__=='__main__': asyncio.run(main_async())
