"""Analyze existing AgentOctagon repeated attempts without rerunning agents."""
from __future__ import annotations
import argparse, json, statistics
from collections import Counter
from pathlib import Path
from agenteval.meta_eval import OctagonDiscovery, write_inventory

def main():
 p=argparse.ArgumentParser(); p.add_argument('--root',default='/home/yang/agent-octagon'); p.add_argument('--output',default='run/meta_eval/octagon-stability'); args=p.parse_args()
 root=Path(args.output); root.mkdir(parents=True,exist_ok=True)
 d=OctagonDiscovery(args.root); attempts=d.discover(only_with_trace=True); groups=d.task_groups(attempts)
 rows=[]
 for key, values in sorted(groups.items()):
  if len(values)<2: continue
  scores=[float(x.score_total) for x in values if x.score_total is not None]
  if not scores: continue
  rows.append({'group':key,'n':len(values),'score_mean':statistics.mean(scores),'score_std':statistics.stdev(scores) if len(scores)>1 else 0.0,'score_min':min(scores),'score_max':max(scores),'score_range':max(scores)-min(scores),'exact_score_agreement':len(set(scores))==1,'status_counts':dict(Counter(x.status for x in values)),'model_counts':dict(Counter(x.model for x in values)),'attempt_ids':[x.attempt_id for x in values]})
 summary={'schema_version':'agenteval.octagon_stability.v1','attempts_with_trace':len(attempts),'environments':len(d.environment_inventory()),'repeat_groups':len(rows),'repeat_attempts':sum(x['n'] for x in rows),'groups_exact_score_agreement':sum(x['exact_score_agreement'] for x in rows),'groups_with_score_range_gt_10':sum(x['score_range']>10 for x in rows),'groups_with_score_range_gt_25':sum(x['score_range']>25 for x in rows),'max_score_range':max((x['score_range'] for x in rows),default=None),'mean_group_score_std':statistics.mean(x['score_std'] for x in rows) if rows else None}
 (root/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 (root/'groups.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
 write_inventory(root/'inventory.json',attempts,d.environment_inventory())
 print(json.dumps(summary,ensure_ascii=False,indent=2))
 print('\nLargest score ranges:')
 for row in sorted(rows,key=lambda x:x['score_range'],reverse=True)[:15]: print(row['group'],row['n'],row['score_min'],row['score_max'],row['score_range'])
if __name__=='__main__': main()
