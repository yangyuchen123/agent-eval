#!/usr/bin/env python3
from __future__ import annotations
import json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'experiments/external-bench-octagon-stability-20260902'
BASE='http://127.0.0.1:8100/api'
TASKS=['external-agencybench-code-2-repo-review_001','external-agencybench-code-3-event-generator_001','external-devai-52-qlora_001','external-devai-54-openai-response-analyzer_001']
ENVS={x.split('_001')[0]:x.split('_001')[0] for x in TASKS}
AGENTS=['claude-code','codex','blade-agent']
MODELS={'claude-code':'or-cc/deepseek/deepseek-v4-flash-0731','codex':'or-codex/deepseek/deepseek-v4-flash-0731','blade-agent':'provider-efe778e50f::deepseek/deepseek-v4-flash-0731'}
def post(body):
 req=urllib.request.Request(BASE+'/runs',data=json.dumps(body).encode(),headers={'content-type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
def main():
 rows=[]; OUT.mkdir(parents=True,exist_ok=True)
 for repeat in range(1,4):
  for task_id in TASKS:
   env=task_id[:-4]
   body={'env_name':env,'task_id':task_id,'agents':AGENTS,'models':MODELS,'compare_mode':'same-model','execution':'parallel','timeout_seconds':900,'capture_policy':'metadata'}
   print(f'submit repeat={repeat} task={task_id}',flush=True)
   try: r=post(body); rows.append({'repeat':repeat,'task_id':task_id,'request':body,'response':r})
   except Exception as e: rows.append({'repeat':repeat,'task_id':task_id,'request':body,'error':repr(e)})
   (OUT/'submitted_runs.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
   time.sleep(1)
 print(json.dumps(rows,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
