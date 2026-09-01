"""Build a human-review calibration candidate manifest from real Octagon data.

This is deliberately a candidate manifest, not Gold. It records repeated
attempts and scorer metadata so a reviewer can choose question-level Gold.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
from agenteval.meta_eval import OctagonDiscovery

def main():
 p=argparse.ArgumentParser(); p.add_argument('--root',default='/home/yang/agent-octagon'); p.add_argument('--output',default='run/meta_eval/octagon-calibration-candidates/manifest.json'); p.add_argument('--max-groups',type=int,default=50); args=p.parse_args()
 d=OctagonDiscovery(args.root); attempts=d.discover(only_with_trace=True); groups=d.task_groups(attempts)
 candidates=[]
 for key, vals in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))[:args.max_groups]:
  candidates.append({'group_id':key,'env_name':vals[0].env_name,'task_id':vals[0].task_id,'attempts':[x.to_dict() for x in vals], 'gold_status':'pending_human_review'})
 out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps({'schema_version':'agenteval.octagon_calibration_candidates.v1','gold_policy':'human_only','candidate_group_count':len(candidates),'groups':candidates},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'output':str(out),'candidate_groups':len(candidates),'candidate_attempts':sum(len(x['attempts']) for x in candidates)},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
