#!/usr/bin/env python3
"""Shared RubricRefiner -> AtomicityValidator entry point.

Input is a prepared JSONL of BugFind candidates. The runner can use a single
batch LLM call for refinement; validation is independent and deterministic by
default. Failed validation keeps the original criterion.
"""
from __future__ import annotations
import argparse, json, os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agenteval.rubric_refiner import normalize_result, inherit_metadata, refiner_prompt
from agenteval.rubric_atomicity_validator import validate_atomicity
from agenteval.backends import LLMBackend

def load(path):
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--candidates', required=True, help='JSONL: task_context, criterion, defect')
    p.add_argument('--out', required=True)
    p.add_argument('--base-url', default=os.getenv('GENERATOR_BASE_URL'))
    p.add_argument('--model', default=os.getenv('GENERATOR_MODEL'))
    p.add_argument('--api-key', default=os.getenv('GENERATOR_API_KEY'))
    p.add_argument('--wire-api', default=os.getenv('GENERATOR_WIRE_API','chat'))
    p.add_argument('--max-tokens', type=int, default=4096)
    p.add_argument('--dry-run', action='store_true')
    args=p.parse_args(); items=load(args.candidates)
    raw=[]
    if args.dry_run:
        raw=[{'action':'KEEP','original_criterion_id':str((x.get('criterion') or {}).get('criterion_id') or x.get('criterion_id')),'reason':'dry-run','replacement_criteria':[]} for x in items]
    else:
        if not args.base_url or not args.model: raise SystemExit('base URL and model are required unless --dry-run')
        backend=LLMBackend(base_url=args.base_url, model=args.model, api_key=args.api_key, wire_api=args.wire_api, temperature=0.0, max_tokens=args.max_tokens, retries=1, json_mode=True)
        response=backend.infer(refiner_prompt(items)); parsed=response.get('parsed') or {}
        raw=parsed.get('results') if isinstance(parsed,dict) else None
        if not isinstance(raw,list): raise SystemExit('refiner output must contain results list')
    results=[]
    for item, proposal_raw in zip(items, raw):
        original=item.get('criterion') or item
        proposal=normalize_result(proposal_raw, original)
        validation=validate_atomicity(original, proposal, str(item.get('task_context','')))
        accepted=validation['accept']
        if accepted and proposal['action']=='SPLIT':
            final=[inherit_metadata(original,x) for x in proposal['replacement_criteria']]
        else:
            final=[dict(original)]
        results.append({'task_id':item.get('task_id'),'original_criterion_id':original.get('criterion_id'),'proposal':proposal,'validation':validation,'accepted':accepted,'final_action':proposal['action'] if accepted else 'KEEP_ORIGINAL','final_criteria':final})
    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text('\n'.join(json.dumps(x,ensure_ascii=False) for x in results)+'\n',encoding='utf-8')
    print(out)
if __name__=='__main__': main()
