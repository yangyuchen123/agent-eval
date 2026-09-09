#!/usr/bin/env python3
from __future__ import annotations
import json, time, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ENVROOT=Path('/home/yang/agent-octagon-envs')
OUT=ROOT/'experiments/external-bench-octagon-20260902'
BASE='http://127.0.0.1:8100/api'
AGENTS=['claude-code','codex','blade-agent']
MODELS={'claude-code':'or-cc/deepseek/deepseek-v4-flash-0731','codex':'or-codex/deepseek/deepseek-v4-flash-0731','blade-agent':'provider-efe778e50f::deepseek/deepseek-v4-flash-0731'}
def post(body):
 data=json.dumps(body).encode(); req=urllib.request.Request(BASE+'/runs',data=data,headers={'content-type':'application/json'},method='POST')
 with urllib.request.urlopen(req,timeout=30) as r: return json.load(r)
def main():
 tasks=[]
 for d in sorted(ENVROOT.iterdir()):
  if not d.is_dir() or not d.name.startswith(('external-devai-','external-agencybench-')): continue
  for p in sorted((d/'tasks').glob('*.json')): tasks.append(json.loads(p.read_text()))
 tasks.sort(key=lambda x:x['id'])
 OUT.mkdir(parents=True,exist_ok=True)
 results=[]
 for task in tasks:
  body={'env_name':task['env_name'],'task_id':task['id'],'agents':AGENTS,'models':MODELS,'compare_mode':'same-model','execution':'parallel','timeout_seconds':900,'capture_policy':'metadata'}
  print('submit',task['id'],flush=True)
  try: result=post(body); results.append({'task_id':task['id'],'request':body,'response':result})
  except Exception as e: results.append({'task_id':task['id'],'request':body,'error':repr(e)})
  (OUT/'submitted_runs.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
  time.sleep(1)
 print(json.dumps(results,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
