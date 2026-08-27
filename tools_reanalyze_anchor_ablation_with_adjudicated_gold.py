"""Reanalyze prior end-to-end and frozen-scoring 2×2 results with anchor-aware Gold."""
from __future__ import annotations
import json, math, statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parent
GOLD_PATH=ROOT/'meta_eval/gold_adjudication_failure_handling_v2/five_case_anchor_expectations.json'
E2E=ROOT/'run/meta_eval/failure-handling-anchor-wording-ablation-v1'
FROZEN=ROOT/'run/meta_eval/frozen-evidence-scoring-ablation-v1'
CELLS=['A_5_qualitative','B_5_continuum','C_6_qualitative','D_6_continuum']


def expected(gold:dict[str,Any], case_id:str, cell:str)->float:
    return float(gold['cases'][case_id]['expected_by_condition'][cell])


def summarize(rows:list[dict[str,Any]], cell:str, gold:dict[str,Any])->dict[str,Any]:
    errors=[abs(float(x['score'])-expected(gold,x['case_id'],cell)) for x in rows]
    exact=[math.isclose(float(x['score']),expected(gold,x['case_id'],cell),abs_tol=1e-9) for x in rows]
    per=defaultdict(list)
    for x in rows: per[x['case_id']].append(float(x['score']))
    return {'observations':len(rows),'strict_exact_accuracy':statistics.mean(exact),
            'mae':statistics.mean(errors),'rmse':math.sqrt(statistics.mean(e*e for e in errors)),
            'per_case':{c:{'expected':expected(gold,c,cell),'scores':v,
                           'mae':statistics.mean(abs(s-expected(gold,c,cell)) for s in v)} for c,v in per.items()}}


def interaction(cells:dict[str,dict[str,Any]], metric:str)->float:
    A,B,C,D=(cells[x][metric] for x in CELLS)
    return (D-C)-(B-A)


def e2e_rows()->dict[str,list[dict[str,Any]]]:
    specs={
      'A_5_qualitative':ROOT/'run/meta_eval/failure-handling-anchor-v2-v5/5-levels/judgments.jsonl',
      'B_5_continuum':E2E/'5-level-continuum/judgments.jsonl',
      'C_6_qualitative':E2E/'6-level-qualitative/judgments.jsonl',
      'D_6_continuum':ROOT/'run/meta_eval/failure-handling-anchor-small-v1/6-levels/judgments.jsonl'}
    result={}
    allowed=set(json.loads(GOLD_PATH.read_text())['cases'])
    for cell,path in specs.items():
      result[cell]=[json.loads(x) for x in path.read_text().splitlines() if x.strip() and json.loads(x)['case_id'] in allowed]
    return result


def main():
    gold=json.loads(GOLD_PATH.read_text())
    frozen_rows=[json.loads(x) for x in (FROZEN/'judgments.jsonl').read_text().splitlines() if x.strip()]
    datasets={'end_to_end':e2e_rows(),
              'frozen_scoring':{c:[x for x in frozen_rows if x['condition']==c] for c in CELLS}}
    result={'schema_version':'agenteval.anchor_aware_reanalysis.v1',
            'gold_status':gold['status'],'post_hoc_adjudication':True,'datasets':{}}
    for name,groups in datasets.items():
      cells={c:summarize(groups[c],c,gold) for c in CELLS}
      result['datasets'][name]={'cells':cells,'interaction':{
        'mae_difference_in_differences':interaction(cells,'mae'),
        'exact_difference_in_differences':interaction(cells,'strict_exact_accuracy')}}
    out=ROOT/'run/meta_eval/anchor-aware-gold-reanalysis-v1'
    out.mkdir(parents=True,exist_ok=True)
    (out/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'output':str(out/'analysis.json'),'datasets':result['datasets']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
