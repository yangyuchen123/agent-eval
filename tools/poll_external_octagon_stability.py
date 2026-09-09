#!/usr/bin/env python3
from __future__ import annotations
import json,time,urllib.request
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]/'experiments/external-bench-octagon-stability-20260902'
BASE='http://127.0.0.1:8100/api/runs/'
TERMINAL={'completed','failed','stopped','cancelled','partial'}
def get(rid):
 with urllib.request.urlopen(BASE+rid,timeout=30) as r:return json.load(r)
def main():
 rows=json.loads((OUT/'submitted_runs.json').read_text()); ids=[x['response']['run_id'] for x in rows if x.get('response')]; latest={}
 while True:
  done=0
  for rid in ids:
   try:d=get(rid)
   except Exception as e:d={'id':rid,'status':'poll_error','error':repr(e)}
   latest[rid]=d
   done+=d.get('status') in TERMINAL
  compact=[]
  for x in rows:
   rid=x.get('response',{}).get('run_id'); d=latest.get(rid,{})
   compact.append({'repeat':x['repeat'],'run_id':rid,'task_id':x['task_id'],'status':d.get('status'),'attempts':[{'agent':a.get('agent_name'),'status':a.get('status'),'score_total':a.get('score_total'),'error_code':a.get('error_code')} for a in d.get('attempts',[])]})
  (OUT/'run_status.json').write_text(json.dumps(compact,ensure_ascii=False,indent=2)+'\n')
  print(f'{done}/{len(ids)} terminal',flush=True)
  if done==len(ids):break
  time.sleep(20)
if __name__=='__main__':main()
