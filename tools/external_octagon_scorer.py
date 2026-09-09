from pathlib import Path
from typing import Any
import ast, re

def _attempt(attempt_id, env_db):
    p=Path(env_db) if env_db else Path('data/attempts')/attempt_id
    return p if p.name==attempt_id else p.parent

def _exists(ws, rel):
    return (ws/rel).exists()

def score(*, attempt_id: str, task: dict, env_db=None, **kw: Any):
    root=_attempt(attempt_id, env_db); ws=root/'skill_workspace'
    if not ws.exists(): ws=root
    expected=(task.get('constraints') or {}).get('expected_files', [])
    present=[x for x in expected if _exists(ws,x)]
    completion=round(100*len(present)/len(expected)) if expected else 0
    files=[p for p in ws.rglob('*') if p.is_file()] if ws.exists() else []
    code=[p for p in files if p.suffix=='.py']
    syntax=0
    for p in code:
        try: ast.parse(p.read_text(encoding='utf-8'))
        except Exception: continue
        syntax+=1
    quality=round(100*syntax/len(code)) if code else (100 if present else 0)
    text=' '.join(p.read_text(errors='ignore')[:20000] for p in files if p.suffix in {'.md','.txt','.py','.json'})
    validation=100 if re.search(r'pytest|unittest|assert |test_',text,re.I) else (50 if re.search(r'validate|check|verify|evaluation|report',text,re.I) else 0)
    missing=[x for x in expected if x not in present]
    return [
        {'dimension':'task_completion','value':completion,'detail':f'{len(present)}/{len(expected)} expected artifacts present; missing={missing}'},
        {'dimension':'artifact_quality','value':quality,'detail':f'{syntax}/{len(code)} Python files parse successfully'},
        {'dimension':'validation_evidence','value':validation,'detail':'Validation/test/report evidence detected' if validation else 'No validation evidence detected'},
    ]
score.__version__='external-octagon-scorer-v1'
