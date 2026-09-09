from __future__ import annotations
import json,time,urllib.request
from pathlib import Path
P=Path(__file__).resolve().parents[1]/'experiments/external-bench-octagon-20260902/submitted_runs.json'
OUT=P.parent/'run_status.json'
BASE='http://127.0.0.1:8100/api/runs/'
TERMINAL={'completed','failed','stopped','cancelled','partial'}
def get(run_id):
 with urllib.request.urlopen(BASE+run_id,timeout=30) as r:return json.load(r)
def main():
 rows=json.loads(P.read_text()); ids=[x['response']['run_id'] for x in rows if x.get('response')]
 latest={}
 while True:
  done=0
  for rid in ids:
   try:d=get(rid)
   except Exception as e:d={'id':rid,'status':'poll_error','error':repr(e)}
   latest[rid]=d
   if d.get('status') in TERMINAL:done+=1
  compact=[]
  for rid,d in latest.items():
   compact.append({'run_id':rid,'task_id':d.get('task_id'),'status':d.get('status'),'attempts':[{'agent':a.get('agent_name'),'status':a.get('status'),'score_total':a.get('score_total'),'scoring_status':a.get('scoring_status'),'execution_status':a.get('execution_status')} for a in d.get('attempts',[])]})
  OUT.write_text(json.dumps(compact,ensure_ascii=False,indent=2)+'\n')
  print(f'{done}/{len(ids)} terminal',flush=True)
  for x in compact: print(x['run_id'],x['task_id'],x['status'],[(a['agent'],a['status'],a['score_total']) for a in x['attempts']],flush=True)
  if done==len(ids): break
  time.sleep(20)
if __name__=='__main__':main()
