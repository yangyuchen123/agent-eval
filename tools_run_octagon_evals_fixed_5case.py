#!/usr/bin/env python3
"""Run octagon-evals on AgentEval's pre-frozen B 5-task stability set.

AgentEval results are not rerun; they are loaded from the five archived B
repeats. octagon-evals is run with the identical five tasks, 22 criteria,
trajectory inputs, binary gold threshold, model and five repeats.
"""
from __future__ import annotations
import concurrent.futures, json, os, statistics, sys, time
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,"/tmp/octagon-evals/src")
from octagon_evals.scorers.agent_judge import AgentJudge, AgentJudgeConfig

EXP=ROOT/"archive/2026-08-31/project-history/run/meta_eval/stability-B-5case-5repeat-20260901"
DATA=ROOT/"archive/2026-08-31/project-history/run/meta_eval/conditional-validation-coding20-20260901"
RB=Path("/home/yang/RuVerBench/data/benchmark")
OUT=ROOT/"run/meta_eval/octagon-evals-fixed-5case-5repeat-20260902"
REPEATS=5
CONCURRENCY=int(os.environ.get("OCTAGON_EVALS_CONCURRENCY","8"))

def load_env():
    for line in (ROOT/".env").read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line: continue
        k,v=line.split("=",1)
        os.environ.setdefault(k.strip(),v.strip().strip('"').strip("'"))
load_env()


def jl(p): return [json.loads(x) for x in Path(p).read_text().splitlines() if x.strip()]

def trajectory_map():
    return {x["meta"]["session_id"]:x for x in jl(RB/"agenticcoding_trajectories.jsonl")}

def trace_for(traces, instance_id):
    return "\n".join(json.dumps(m,ensure_ascii=False) for m in traces[instance_id].get("messages",[]) if isinstance(m,dict))

def load_data():
    lock=json.loads((EXP/"protocol_lock.json").read_text())
    selected=lock["task_ids"]
    tasks={x["task_id"]:x for x in jl(DATA/"tasks.jsonl")}
    gold={(x["task_id"],x["criterion_id"]):bool(x["gold_label"]) for x in jl(DATA/"criterion_gold.jsonl")}
    traces=trajectory_map()
    return [tasks[x] for x in selected],gold,traces

def anchors():
    return [
      {"score":0.0,"label":"not_satisfied","description":"The criterion is not satisfied; evidence is absent, contradicted, or materially insufficient."},
      {"score":1.0,"label":"satisfied","description":"The criterion is satisfied by direct evidence in the supplied response or trajectory."},
    ]

def call_one(task, criterion, trace, repeat):
    cfg=AgentJudgeConfig(
      endpoint=os.environ["JUDGE_BASE_URL"].rstrip("/")+"/chat/completions",
      model=os.environ.get("JUDGE_MODEL","gpt-5.6-luna"), api_key=os.environ.get("JUDGE_API_KEY"), prompt_version="octagon-evals-fixed-5case-v1")
    evidence={
      "task_id":task["task_id"], "benchmark":task.get("benchmark"),
      "request":task.get("request"), "system_prompt":task.get("system_prompt"),
      "criterion_id":criterion["criterion_id"], "criterion":criterion.get("description") or criterion.get("text",""),
      "agent_output":trace,
      "trajectory":trace,
    }
    judge=AgentJudge(cfg)
    started=time.perf_counter()
    try:
      s=judge.score(f"{task['task_id']}::{criterion['criterion_id']}::r{repeat}", evidence,
                    criterion.get("description") or criterion.get("text",""), anchors=anchors(),
                    output_schema={"type":"object","required":["value","reason","raw"],"value_range":[0,1]})
      return {"task_id":task["task_id"],"criterion_id":criterion["criterion_id"],"repeat":repeat,"score":s.value,"prediction":s.value>=.5,"source":s.source,"reason":s.reason,"raw":s.raw,"lineage":s.lineage,"latency_sec":time.perf_counter()-started}
    except Exception as e:
      return {"task_id":task["task_id"],"criterion_id":criterion["criterion_id"],"repeat":repeat,"score":None,"prediction":None,"error":repr(e),"latency_sec":time.perf_counter()-started}

def metric(rows,gold):
    valid=[r for r in rows if r["score"] is not None]
    pred=[r["prediction"] for r in valid]
    correct=[p==gold for p in pred]
    scores=[r["score"] for r in valid]
    return {"n":len(valid),"gold":gold,"accuracy":statistics.mean(correct) if correct else None,"mae":statistics.mean(abs(x-float(gold)) for x in scores) if scores else None,"mean":statistics.mean(scores) if scores else None,"population_std":statistics.pstdev(scores) if len(scores)>1 else 0.0 if scores else None,"range":max(scores)-min(scores) if scores else None,"all_predictions_same":len(set(pred))==1 if pred else None,"prediction_agreement":max(Counter(pred).values())/len(pred) if pred else None}

def main():
    tasks,gold,traces=load_data(); OUT.mkdir(parents=True,exist_ok=True)
    rows=[]
    jobs=[(task,c,trace_for(traces,task["source_task_ref"]["instance_id"]),r) for r in range(1,REPEATS+1) for task in tasks for c in task["rubric_items"]]
    print(f"fixed tasks={len(tasks)} criteria={len(jobs)//REPEATS} repeats={REPEATS} concurrency={CONCURRENCY}",flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
      futures=[pool.submit(call_one,*job) for job in jobs]
      for i,f in enumerate(concurrent.futures.as_completed(futures),1):
        row=f.result(); rows.append(row)
        if i%5==0 or row.get("error"): print(f"{i}/{len(futures)} {row['task_id'].split('::')[-1]} {row['criterion_id']} score={row['score']}" + (f" ERROR {row['error']}" if row.get('error') else ""),flush=True)
    rows.sort(key=lambda x:(x["repeat"],x["task_id"],x["criterion_id"]))
    (OUT/"octagon_evals_judgments.jsonl").write_text("\n".join(json.dumps(x,ensure_ascii=False) for x in rows)+"\n")
    by_task_crit={(r["task_id"],r["criterion_id"]):[x for x in rows if x["task_id"]==r["task_id"] and x["criterion_id"]==r["criterion_id"]] for r in rows}
    per={}
    for key,rs in by_task_crit.items(): per[f"{key[0]}::{key[1]}"]=metric(rs,gold[key])
    repeat_metrics=[]
    for rep in range(1,REPEATS+1):
      rr=[x for x in rows if x["repeat"]==rep and x["score"] is not None]
      correct=[x["prediction"]==gold[(x["task_id"],x["criterion_id"])] for x in rr]
      repeat_metrics.append({"repeat":rep,"n":len(rr),"accuracy":statistics.mean(correct) if correct else None,"errors":len([x for x in rows if x["repeat"]==rep and x.get("error")])})
    allvalid=[x for x in rows if x["score"] is not None]
    allcorrect=[x["prediction"]==gold[(x["task_id"],x["criterion_id"])] for x in allvalid]
    stability={"criterion_n":len(by_task_crit),"all_predictions_same_n":sum(v["all_predictions_same"] for v in per.values() if v["all_predictions_same"] is not None),"all_predictions_same_rate":statistics.mean(v["all_predictions_same"] for v in per.values() if v["all_predictions_same"] is not None),"any_flip_n":sum(not v["all_predictions_same"] for v in per.values() if v["all_predictions_same"] is not None),"mean_agreement_rate":statistics.mean(v["prediction_agreement"] for v in per.values() if v["prediction_agreement"] is not None),"mean_score_std":statistics.mean(v["population_std"] for v in per.values() if v["population_std"] is not None),"mean_score_range":statistics.mean(v["range"] for v in per.values() if v["range"] is not None)}
    summary={"schema_version":"octagon-evals.fixed-5case-comparison.v1","source_experiment":str(EXP),"task_ids":[t["task_id"] for t in tasks],"task_n":len(tasks),"criterion_n":len(by_task_crit),"repeat_n":REPEATS,"model":os.environ.get("JUDGE_MODEL"),"concurrency":CONCURRENCY,"overall":{"n":len(allvalid),"accuracy":statistics.mean(allcorrect) if allcorrect else None,"mae":statistics.mean(abs(x["score"]-float(gold[(x["task_id"],x["criterion_id"])])) for x in allvalid) if allvalid else None},"repeat_metrics":repeat_metrics,"criterion_stability":stability,"by_criterion":per}
    (OUT/"metrics.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:summary[k] for k in ["task_n","criterion_n","repeat_n","overall","repeat_metrics","criterion_stability"]},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
