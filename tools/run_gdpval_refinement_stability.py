#!/usr/bin/env python3
"""B-judge 5-repeat stability regression for original vs refined A/C/D rubrics.

Frozen inputs: one GDPval task, one real AgentOctagon attempt, its trace and
artifact.  Six rubric conditions x five repeats = 30 joint Judge calls.
"""
from __future__ import annotations
import argparse, asyncio, hashlib, json, os, statistics, time
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "run/gdpval-capability-pilot-20260902"
ATTEMPT = Path("/home/yang/agent-octagon/data/attempts/att_869a93f9b7f9")
JUDGE_SRC = ROOT / "judge/src"
sys.path.insert(0, str(JUDGE_SRC))

from agentjudge.catalog import EvidenceCatalog
from agentjudge.models import JudgeRequest
from agentjudge.service import JointQuestionJudgeService
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

sys.path.insert(0, str(ROOT / "src"))
from agenteval.gdpval_official import (
    load_official_criteria,
    official_questions_for_b_judge,
    proxy_gold_labels,
    unweighted_mean,
    weighted_overall,
    weights_by_id,
)

DEFAULT_OUT = PILOT / "b_judge_refinement_stability_30calls"
RRD_DIR = ROOT / "run/gdpval-capability-pilot-20260903/rrd_artifact_noreason"
TASK_JSON = Path("/home/yang/agent-octagon-envs/gdpval-prepaid-amortization-official/tasks/gdpval_prepaid_amortization_official.json")
ORIGINAL_FILES = {
    "A_original": PILOT / "generated_rubric_task_only.json",
    "C_original": PILOT / "generated_rubric_retrieved_human_rubric_gdpval.json",
    "D_original": PILOT / "generated_rubric_global_profile.json",
}
REFINED_FILES = {
    "A_refined": PILOT / "revised_rubrics_a_single_task.jsonl",
    "C_refined": PILOT / "revised_rubrics_c_single_task.jsonl",
    "D_refined": PILOT / "revised_rubrics_d_single_task.jsonl",
}
RRD_FILES = {
    "A_rrd": RRD_DIR / "rrd_A.json",
    "C_rrd": RRD_DIR / "rrd_C.json",
    "D_rrd": RRD_DIR / "rrd_D.json",
}
RRD_FILES_EXTRA = {
    "A_6iter_rrd": ROOT / "run/gdpval-capability-pilot-20260903/rrd_artifact_noreason_6iter/rrd_A.json",
    "A_9iter_rrd": ROOT / "run/gdpval-capability-pilot-20260903/rrd_artifact_noreason_9iter/rrd_A.json",
}


def load_env():
    for line in (ROOT / ".env").read_text().splitlines():
        line=line.strip()
        if line and not line.startswith("#") and "=" in line:
            k,v=line.split("=",1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024), b""): h.update(chunk)
    return h.hexdigest()


GOLD_FILE = Path("/home/yang/agent-octagon-envs/gdpval-prepaid-amortization-official/private/official_rubric.json")
PROXY_GOLD_OUT = ROOT / "run/gdpval-capability-pilot-20260909/b_judge_proxy_gold_official_oneshot_5repeat"

def load_condition(name: str, path: Path) -> tuple[list[dict], dict]:
    gold_tier = None
    if name == "Gold_original":
        questions = official_questions_for_b_judge(load_official_criteria(path))
        condition = "official_rubric_proxy_gold"
        gold_tier = "tier2_proxy_gold"
        meta = {
            "condition": condition,
            "gold_tier": gold_tier,
            "human_calibrated": False,
            "criteria_count": len(questions),
            "official_weight_sum": sum(q["official_weight"] for q in questions),
            "source_file": str(path),
            "source_sha256": sha(path),
        }
        return questions, meta
    if name.endswith("_original"):
        payload=json.loads(path.read_text())
        criteria=payload["criteria"]
        condition=payload.get("condition")
    elif name.endswith("_rrd"):
        payload=json.loads(path.read_text())
        criteria=payload.get("optimized_agent_eval_criteria") or payload.get("optimized_rubrics") or []
        condition="rrd_artifact_noreason"
    else:
        criteria=[]
        for line in path.read_text().splitlines():
            if line.strip(): criteria.append(json.loads(line))
        condition="refined"
    questions=[]
    for c in criteria:
        cid=str(c.get("criterion_id") or c.get("rubric_id") or c.get("rubric_item_id") or c.get("id"))
        text=str(c.get("criterion") or c.get("text") or c.get("question") or c.get("description") or "").strip()
        # B Judge receives only an atomic binary question; metadata remains in
        # the frozen rubric record but does not create additional calls.
        questions.append({
            "id": cid,
            "question": text,
            "description": text,
            "weight": 1.0,
            "official_weight": 1.0,
            "score_anchors": [
                {"score": 0.0, "label": "not_satisfied", "description": "The criterion is not satisfied, or direct evidence is insufficient."},
                {"score": 1.0, "label": "satisfied", "description": "The criterion is satisfied by direct, case-relevant evidence from the supplied artifact and/or trace."},
            ],
            "evidence": str(c.get("evidence_source") or c.get("evidence_scope") or "artifact"),
        })
    return questions, {"condition": condition, "gold_tier": gold_tier, "criteria_count": len(criteria), "source_file": str(path), "source_sha256": sha(path)}


def main_sync_check(files):
    missing=[str(p) for p in [ATTEMPT/"trace.jsonl", ATTEMPT/"events.jsonl", ATTEMPT/"skill_workspace/Aurisic_Prepaid_Amortization_Through_Apr2025.xlsx"] if not p.is_file()]
    if missing: raise SystemExit("Missing frozen fixture: " + ", ".join(missing))
    for p in files.values():
        if not p.is_file(): raise SystemExit(f"Missing rubric input: {p}")


def jsonable(value):
    try: json.dumps(value); return value
    except Exception: return str(value)


async def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-only", action="store_true", help="Run Gold/A/C/D original rubrics only: 4x5=20 calls")
    parser.add_argument("--proxy-gold", action="store_true", help="Phase 0: official GDPval rubric as Proxy Gold, 5 one-shot B repeats")
    parser.add_argument("--rrd", action="store_true", help="Compare frozen original A/C/D vs RRD-optimized A/C/D")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--conditions", default="", help="Optional comma-separated condition names to subset the selected files")
    parser.add_argument("--resume", action="store_true", help="Skip condition/repeat pairs already present in the output JSONL")
    parser.add_argument("--retry-errors", action="store_true", help="With --resume, rerun previous judge_error rows")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    if args.proxy_gold:
        files = {"Gold_original": GOLD_FILE}
        default_out = PROXY_GOLD_OUT
    elif args.original_only:
        files = {"Gold_original": GOLD_FILE, **ORIGINAL_FILES}
        default_out = PILOT / "b_judge_original_stability_20calls"
    elif args.rrd:
        files = {**ORIGINAL_FILES, **RRD_FILES}
        default_out = RRD_DIR / "b_judge_rrd_stability"
    else:
        files = {**ORIGINAL_FILES, **REFINED_FILES}
        default_out = DEFAULT_OUT
    if args.conditions.strip():
        wanted={x.strip() for x in args.conditions.split(",") if x.strip()}
        lookup={**ORIGINAL_FILES, **REFINED_FILES, **RRD_FILES, **RRD_FILES_EXTRA, "Gold_original": GOLD_FILE, **files}
        files={k: lookup[k] for k in wanted if k in lookup}
        missing=wanted-set(files)
        if missing:
            raise SystemExit(f"unknown --conditions: {sorted(missing)}")
        if not files:
            raise SystemExit(f"no matching --conditions in {wanted}")
    repeats=max(1, int(args.repeats))
    out = args.out or default_out
    load_env(); main_sync_check(files); out.mkdir(parents=True, exist_ok=True)
    task=json.loads(TASK_JSON.read_text())
    task_prompt=task["prompt"]
    artifact=ATTEMPT/"skill_workspace/Aurisic_Prepaid_Amortization_Through_Apr2025.xlsx"
    artifact_sha=sha(artifact)
    trace_sha=sha(ATTEMPT/"trace.jsonl")
    # Production B is one-shot: inline the deliverable, do not retrieve trace.
    sys.path.insert(0, str(ROOT / "src"))
    from agenteval.rrd_optimizer.artifacts import render_artifact_text, summarize_xlsx
    deliverable = render_artifact_text([summarize_xlsx(artifact)], compact=True)
    catalog=EvidenceCatalog([])
    records=[]
    conditions={}
    for name,path in files.items():
        qs, meta=load_condition(name,path)
        conditions[name]={"questions":qs,"meta":meta}
    manifest={
        "schema_version":"agenteval.gdpval_refinement_stability_manifest.v1",
        "task_id":"gdpval_prepaid_amortization_official",
        "source_task_id":task.get("context",{}).get("source_task_id"),
        "attempt_id":"att_869a93f9b7f9",
        "trace_sha256":trace_sha,
        "artifact_path":str(artifact), "artifact_sha256":artifact_sha,
        "protocol":"B_joint_multi_rubric_one_shot", "repeat_count":repeats,
        "expected_call_count":repeats * len(files),
        "expected_model_calls":"one_per_task",
        "include_runtrace": False,
        "inline_artifact": True,
        "enable_joint_tools": False,
        "treatment": (
            "proxy_gold_official_oneshot" if args.proxy_gold else
            "rrd_vs_original" if args.rrd else
            ("original_only" if args.original_only else "refined_vs_original")
        ),
        "gold_label_type": "tier2_proxy_gold" if "Gold_original" in files else None,
        "human_calibrated": False,
        "model":os.environ.get("JUDGE_MODEL"),
        "base_url":os.environ.get("JUDGE_BASE_URL"),
        "conditions":{k:v["meta"] for k,v in conditions.items()},
        "evidence_record_count":len(records),
        "deliverable_chars": len(deliverable),
    }
    (out/"experiment_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n")
    (out/"rubric_inputs_snapshot.json").write_text(json.dumps({k:v["questions"] for k,v in conditions.items()},ensure_ascii=False,indent=2)+"\n")

    model_id=os.environ.get("JUDGE_MODEL","gpt-5.6-luna")
    base=os.environ.get("JUDGE_BASE_URL"); key=os.environ.get("JUDGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not base or not key: raise SystemExit("JUDGE_BASE_URL and JUDGE_API_KEY required")
    from pydantic_ai.settings import ModelSettings
    model=OpenAIChatModel(
        model_id,
        provider=OpenAIProvider(base_url=base, api_key=key),
        settings=ModelSettings(
            temperature=0.0,
            thinking=False,
            openai_reasoning_effort="none",
            extra_body={"reasoning": {"effort": "none", "exclude": True}},
        ),
    )
    # Joint B Judge prompts include the full rubric plus catalog/tools. Parallel
    # calls on this endpoint have produced context_too_large; keep default serial.
    sem=asyncio.Semaphore(int(os.environ.get("STABILITY_CONCURRENCY","1")))
    results_path=out/"judge_regression_refinement_results.jsonl"
    existing=[]
    if args.resume and results_path.exists():
        existing=[json.loads(line) for line in results_path.read_text().splitlines() if line.strip()]
    done={(r["condition"], int(r["repeat"])) for r in existing if (r.get("status")!="judge_error" or not args.retry_errors)}
    jobs=[]
    for repeat in range(1, repeats+1):
        for name, cfg in conditions.items():
            if (name, repeat) in done:
                print(f"skip {name} repeat={repeat}", flush=True)
                continue
            jobs.append((repeat,name,cfg))

    async def one(repeat,name,cfg):
        async with sem:
            started=time.perf_counter()
            try:
                service=JointQuestionJudgeService(model, catalog)
                req=JudgeRequest(
                    case={"task": task_prompt}, rubric={"questions":cfg["questions"],"allowed_scores":[0.0,1.0]},
                    agent_output=deliverable,
                    trace_ref=None,
                    artifact_ref={"attempt_id":"att_869a93f9b7f9","path":"skill_workspace/Aurisic_Prepaid_Amortization_Through_Apr2025.xlsx","sha256":artifact_sha,"media_type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
                    metadata={"protocol":"B_one_shot","task_id":"gdpval_prepaid_amortization_official","condition":name,"repeat":repeat,"fixture":"inlined_artifact_no_runtrace","enable_joint_tools":False,"do_not_use_other_tasks":True},
                )
                result=await service.evaluate(req)
                rows=[]
                for j in result.question_judgments:
                    rows.append(j.model_dump())
                score_by_id={str(j["question_id"]): float(j["score"]) for j in rows if j.get("score") is not None}
                weights=weights_by_id(cfg["questions"])
                return {
                    "task_id":manifest["task_id"],"condition":name,"repeat":repeat,"status":result.status,
                    "overall_score":result.overall_score,
                    "unweighted_mean": unweighted_mean(score_by_id.values()),
                    "weighted_overall": weighted_overall(score_by_id, weights),
                    "weight_sum": sum(weights.values()),
                    "confidence":result.confidence,"question_judgments":rows,
                    "query_trajectory":service.last_query_trajectory,"usage":jsonable(service.last_usage),
                    "scoring_provenance":jsonable(service.last_scoring_provenance),
                    "latency_ms":(time.perf_counter()-started)*1000,
                }
            except Exception as e:
                return {"task_id":manifest["task_id"],"condition":name,"repeat":repeat,"status":"judge_error","overall_score":None,"question_judgments":[],"error":repr(e),"latency_ms":(time.perf_counter()-started)*1000}

    rows=list(existing)
    async def wrapped(item):
        row=await one(*item)
        print(f"{row['condition']} repeat={row['repeat']} status={row['status']} qs={len(row.get('question_judgments',[]))}" + (f" ERROR={row['error']}" if row.get('error') else ""),flush=True)
        with results_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False)+"\n")
        return row
    if jobs:
        if not args.resume or not results_path.exists():
            results_path.write_text("")
            rows=[]
        new_rows=await asyncio.gather(*(wrapped(j) for j in jobs))
        rows.extend(new_rows)
    # Keep the last record per condition/repeat if resume mixed old and new.
    latest={}
    for row in rows:
        latest[(row["condition"], int(row["repeat"]))]=row
    rows=sorted(latest.values(), key=lambda x:(x["condition"],x["repeat"]))

    summaries={}
    for name,cfg in conditions.items():
        rs=[r for r in rows if r["condition"]==name]
        by=defaultdict(list)
        for r in rs:
            for j in r.get("question_judgments",[]): by[str(j["question_id"])].append(j)
        per=[]
        for cid, js in sorted(by.items()):
            scores=[float(j["score"]) for j in js if j.get("score") is not None]
            statuses=[j.get("status") for j in js]
            per.append({"criterion_id":cid,"scores":scores,"statuses":statuses,"flip":len(set(scores))>1,"mean":statistics.mean(scores) if scores else None,"score_std":statistics.pstdev(scores) if len(scores)>1 else 0.0 if scores else None,"score_range":max(scores)-min(scores) if scores else None,"status_counts":{s:statuses.count(s) for s in sorted(set(statuses))}})
        all_scores=[x["scores"] for x in per if x["scores"]]
        overall=[r["overall_score"] for r in rs if r.get("overall_score") is not None]
        weighted=[r.get("weighted_overall") for r in rs if r.get("weighted_overall") is not None]
        agreements=[]
        for x in all_scores:
            pairs=[(x[i],x[j]) for i in range(len(x)) for j in range(i+1,len(x))]
            if pairs: agreements.append(sum(a==b for a,b in pairs)/len(pairs))
        scored_maps=[]
        for r in rs:
            scored_maps.append({str(j["question_id"]): float(j["score"]) for j in r.get("question_judgments", []) if j.get("score") is not None})
        weights=weights_by_id(cfg["questions"])
        proxy=proxy_gold_labels(scored_maps, weights) if name=="Gold_original" and scored_maps else None
        summaries[name]={"criterion_count":cfg["meta"]["criteria_count"],"run_count":repeats,"status_counts":{s:sum(r["status"]==s for r in rs) for s in sorted({r["status"] for r in rs})},"call_level_failure_count":sum(r["status"] in {"judge_error","incomplete_evidence"} for r in rs),"flip_criterion_count":sum(x["flip"] for x in per),"flip_rate":(sum(x["flip"] for x in per)/len(per)) if per else None,"mean_prediction_agreement":statistics.mean(agreements) if agreements else None,"mean_score_std":statistics.mean(x["score_std"] for x in per if x["score_std"] is not None) if per else None,"mean_score_range":statistics.mean(x["score_range"] for x in per if x["score_range"] is not None) if per else None,"overall_scores":overall,"overall_score_mean":statistics.mean(overall) if overall else None,"overall_score_std":statistics.pstdev(overall) if len(overall)>1 else 0.0 if overall else None,"overall_score_range":max(overall)-min(overall) if overall else None,"weighted_overalls":weighted,"weighted_overall_mean":statistics.mean(weighted) if weighted else None,"weighted_overall_std":statistics.pstdev(weighted) if len(weighted)>1 else 0.0 if weighted else None,"proxy_gold_majority":proxy,"by_criterion":per}
    metrics={"schema_version":"agenteval.gdpval_refinement_stability_metrics.v1","manifest":"experiment_manifest.json","gold_label_type": manifest.get("gold_label_type"),"human_calibrated": False,"conditions":summaries}
    (out/"refinement_stability_metrics.json").write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(summaries,ensure_ascii=False,indent=2))

if __name__=="__main__": asyncio.run(run())
