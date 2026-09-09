from __future__ import annotations
import json, pathlib, collections, sqlite3, re
ROOT=pathlib.Path(__file__).resolve().parents[1]; DATA=pathlib.Path('/home/yang/agent-octagon/data'); ATT=DATA/'attempts'
DB=DATA/'octagon.db'; OUT=ROOT/'experiments/external-bench-octagon-stability-20260902'
run_rows=json.loads((OUT/'run_status.json').read_text())
run_ids=[r['run_id'] for r in run_rows]
con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
q='select id,run_id,agent_name,status,score_total,execution_error_code,execution_error_message,started_at,ended_at from attempts where run_id in (%s)'%','.join('?'*len(run_ids))
rows=[dict(x) for x in con.execute(q,run_ids)]
for x in rows:
 d=ATT/x['id']; x['files']={}; x['tool_counts']=collections.Counter(); x['event_counts']=collections.Counter(); x['last_assistant']=''; x['errors']=[]
 for name in ['trace.jsonl','events.jsonl','conversation.jsonl']:
  p=d/name
  if not p.exists(): continue
  ls=p.read_text(errors='replace').splitlines(); x['files'][name]=len(ls)
  for line in ls:
   try:o=json.loads(line)
   except: continue
   typ=o.get('event_type') or o.get('type') or o.get('kind') or o.get('event')
   if typ:x['event_counts'][typ]+=1
   tn=o.get('tool_name') or (o.get('item') or {}).get('type')
   if tn:x['tool_counts'][str(tn)]+=1
   txt=json.dumps(o,ensure_ascii=False)
   if any(k in txt.lower() for k in ['error','timeout','failed','waiting for input','unrecognized_model']):
    if len(x['errors'])<12:x['errors'].append(txt[:500])
   if 'assistant' in txt.lower() and len(txt)>80:
    text=(o.get('text') or (o.get('item') or {}).get('text') or (o.get('raw') or {}).get('message',{}).get('content',''))
    if isinstance(text,str) and text.strip():x['last_assistant']=text[-1000:]
 ws=d/'skill_workspace'; x['workspace_files']=len([p for p in ws.rglob('*') if p.is_file()]) if ws.exists() else 0
 x['workspace_sample']=[str(p.relative_to(ws)) for p in ws.rglob('*') if p.is_file()][:30] if ws.exists() else []
 x['tool_counts']=dict(x['tool_counts']); x['event_counts']=dict(x['event_counts'])
(OUT/'runtrace_diagnostics.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
# compact TSV
for x in rows:
 print(x['run_id'],x['id'],x['agent_name'],x['status'],x['score_total'],'err='+str(x['execution_error_code']),'trace='+str(x['files'].get('trace.jsonl',0)),'events='+str(x['files'].get('events.jsonl',0)),'ws='+str(x['workspace_files']),'tools='+','.join(f'{k}:{v}' for k,v in list(x['tool_counts'].items())[:8]))
