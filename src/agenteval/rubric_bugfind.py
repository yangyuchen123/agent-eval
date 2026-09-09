"""BugFind role for locating possible compound rubric criteria only."""
from __future__ import annotations
import json
from typing import Any, Mapping, Sequence

def bugfind_prompt(task_context: str, rubric_set: str, criteria: Sequence[Mapping[str, Any]]) -> list[dict[str,str]]:
    payload={"task_context":task_context,"rubric_set":rubric_set,"criteria":[{"criterion_id":x.get("criterion_id"),"text":x.get("text") or x.get("criterion") or "","metadata":{k:x.get(k) for k in ("grounding","scope","evidence_source","atomicity","hardness","judgment_type","capability")}} for x in criteria]}
    system="""You are BugFind for rubric atomicity only. For every criterion, identify whether it is a compound candidate. Do not judge satisfaction, Gold labels, Judge predictions, or accuracy. Do not rewrite criteria. A criterion is compound_candidate only when it contains two or more independently judgeable propositions that could reasonably differ in truth value. Supporting detail, examples, qualifiers, and multiple nouns in one proposition are not enough. Return one record for every input criterion. Output only JSON."""
    user="Input:\n"+json.dumps(payload,ensure_ascii=False,indent=2)+"""\n\nReturn exactly: {"findings":[{"criterion_id":"...","classification":"confirmed_compound|suspected_compound|keep_candidate","reason":"...","independent_propositions":["..."],"confidence":"high|medium|low"}]}"""
    return [{"role":"system","content":system},{"role":"user","content":user}]
