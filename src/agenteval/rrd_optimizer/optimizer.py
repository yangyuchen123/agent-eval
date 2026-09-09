"""Independent RRD-style rubric optimization loop."""
from __future__ import annotations
import math
from collections.abc import Callable, Sequence
from typing import Any
from .evaluator import evaluate_with_callable, metrics_from_matrix
from .metrics import behavioral_redundancy_warnings, correlation_aware_weights, rubric_set_metrics, semantic_filter
from .models import CalibrationResponse, DecompositionProposal, OptimizationConfig, OptimizationResult, Rubric

Evaluator = Callable[[str, Sequence[Rubric], Sequence[CalibrationResponse]], Any]
Decomposer = Callable[[str, Sequence[tuple[Rubric, dict[str, int]]], Sequence[CalibrationResponse], int], Any]

class RRDRubricOptimizer:
    """Response-driven decomposition, misalignment filtering and weighting.

    RRD broadness is intentionally independent from strong/weak discrimination:
    a rubric satisfied by more than the configured number of samples is a
    decomposition candidate. Strong/weak direction is used later to identify
    misaligned criteria; behavioral correlation produces warnings/weights, not
    automatic deletion.
    """
    def __init__(self, evaluator: Evaluator, decomposer: Decomposer, config: OptimizationConfig | None = None):
        self.evaluator, self.decomposer, self.config = evaluator, decomposer, config or OptimizationConfig()

    def _apply_filters(self, current, matrix, metrics):
        dropped=[]
        if self.config.enable_misalignment_filter:
            kept=[]
            for rubric in current:
                m=metrics[rubric.rubric_id]
                if m.misalignment_candidate:
                    dropped.append({"rubric_id":rubric.rubric_id,"reason":"weak_preference_misalignment","strong_support_rate":m.strong_support_rate,"weak_support_rate":m.weak_support_rate})
                else: kept.append(rubric)
            current=kept
        if self.config.enable_semantic_filter and current:
            current, semantic_drops=semantic_filter(current,matrix,metrics,semantic_threshold=self.config.semantic_similarity_threshold)
            dropped.extend(semantic_drops)
        return current,dropped

    def optimize(self, task_id: str, task: str, initial_rubrics: Sequence[Rubric], calibration_responses: Sequence[CalibrationResponse]) -> OptimizationResult:
        if not initial_rubrics: raise ValueError("initial_rubrics cannot be empty")
        if len(calibration_responses)<2 or not any(x.quality_group=="strong" for x in calibration_responses) or not any(x.quality_group=="weak" for x in calibration_responses): raise ValueError("calibration_responses must include strong and weak responses")
        original=list(initial_rubrics); current=list(initial_rubrics); trace=[]; tree={}; dropped=[]; round_snapshots=[]
        def _snapshot(iteration, phase, rubrics, metrics, *, broad=None, dropped_this_round=None, stop_reason=None, extra=None):
            snap={
                "iteration": iteration,
                "phase": phase,
                "stop_reason": stop_reason,
                "rubric_count": len(rubrics),
                "broad_count": len(broad or []),
                "broad_candidates": list(broad or []),
                "set_metrics": rubric_set_metrics(metrics) if metrics else {},
                "dropped_this_round": list(dropped_this_round or []),
                "rubrics": [{"rubric_id": r.rubric_id, "text": r.text} for r in rubrics],
            }
            if extra: snap.update(extra)
            round_snapshots.append(snap)
            return snap
        expansion_cap = self.config.max_total_expansion_ratio
        for iteration in range(self.config.max_iterations):
            matrix,eval_meta=evaluate_with_callable(self.evaluator,task,current,calibration_responses)
            metrics=metrics_from_matrix(matrix,calibration_responses,self.config)
            broad=[r for r in current if metrics[r.rubric_id].broad_candidate]
            event={"iteration":iteration,"phase":"evaluate","snapshot":{"rubrics":[r.to_dict() for r in current],"matrix":matrix,"metrics":{k:v.to_dict() for k,v in metrics.items()},"set_metrics":rubric_set_metrics(metrics)},"broad_candidates":[r.rubric_id for r in broad],"misalignment_candidates":[r.rubric_id for r in current if metrics[r.rubric_id].misalignment_candidate],"evaluator_metadata":eval_meta}
            _snapshot(iteration, "evaluate", current, metrics, broad=[r.rubric_id for r in broad])
            if not broad:
                _snapshot(iteration, "stop", current, metrics, broad=[], stop_reason="no_broad_candidates")
                trace.append(event|{"stop_reason":"no_broad_candidates"}); break
            candidates=[(r,matrix[r.rubric_id]) for r in broad]
            value=self.decomposer(task,candidates,calibration_responses,self.config.max_children_per_rubric)
            proposals,decomp_meta=value if isinstance(value,tuple) and len(value)==2 else (value,{})
            event["phase"]="decompose"; event["decomposition"]=[{"parent_rubric_id":p.parent_rubric_id,"status":p.status,"reason":p.reason,"children":[x.to_dict() for x in p.children]} for p in proposals]; event["decomposer_metadata"]=decomp_meta
            replacements={}
            for proposal in proposals:
                if proposal.status!="split" or len(proposal.children)<self.config.min_children: continue
                if iteration+1>self.config.max_decomposition_depth:
                    tree.setdefault(proposal.parent_rubric_id,{})[str(iteration)]={"status":"budget_exceeded","children":[]}; continue
                projected=len(current)-1+len(proposal.children)
                if expansion_cap and projected>math.ceil(len(original)*float(expansion_cap)):
                    tree.setdefault(proposal.parent_rubric_id,{})[str(iteration)]={"status":"budget_exceeded","children":[x.to_dict() for x in proposal.children]}; continue
                replacements[proposal.parent_rubric_id]=proposal.children
                tree.setdefault(proposal.parent_rubric_id,{})[str(iteration)]={"status":"split","children":[x.to_dict() for x in proposal.children],"reason":proposal.reason}
            if not replacements:
                _snapshot(iteration, "stop", current, metrics, broad=[r.rubric_id for r in broad], stop_reason="no_budgeted_decomposition")
                trace.append(event|{"stop_reason":"no_budgeted_decomposition"}); break
            pre=list(current); next_set=[]
            for rubric in pre: next_set.extend(replacements.get(rubric.rubric_id,[rubric]))
            child_matrix,child_meta=evaluate_with_callable(self.evaluator,task,next_set,calibration_responses); child_metrics=metrics_from_matrix(child_matrix,calibration_responses,self.config)
            # Discrimination is reported as child measurement gain, not used as
            # a prerequisite for decomposition acceptance.
            for parent_id,children in replacements.items():
                tree[parent_id][str(iteration)]["parent_discrimination"]=metrics[parent_id].discrimination
                tree[parent_id][str(iteration)]["child_discriminations"]={c.rubric_id:child_metrics[c.rubric_id].discrimination for c in children}
                tree[parent_id][str(iteration)]["max_child_gain"]=max(child_metrics[c.rubric_id].discrimination for c in children)-metrics[parent_id].discrimination
            current=next_set
            filter_matrix, filter_metrics, filter_meta = child_matrix, child_metrics, child_meta
            current,filter_drops=self._apply_filters(current,filter_matrix,filter_metrics); dropped.extend(filter_drops)
            warnings=behavioral_redundancy_warnings(current,filter_matrix,threshold=self.config.behavioral_agreement_threshold) if self.config.enable_behavioral_warnings else []
            event["child_evaluation"]={"matrix":child_matrix,"metrics":{k:v.to_dict() for k,v in child_metrics.items()},"metadata":child_meta}; event["filter"]={"decisions":filter_drops,"post_filter_count":len(current),"reused_child_matrix":True,"metadata":filter_meta}; event["behavioral_warnings"]=warnings; trace.append(event)
            _snapshot(iteration, "after_split", current, filter_metrics, broad=[r.rubric_id for r in current if filter_metrics.get(r.rubric_id) and filter_metrics[r.rubric_id].broad_candidate], dropped_this_round=filter_drops, extra={"split_parents": sorted(replacements)})
        final_matrix,final_meta=evaluate_with_callable(self.evaluator,task,current,calibration_responses); final_metrics=metrics_from_matrix(final_matrix,calibration_responses,self.config)
        # Apply direction and semantic filters once more on the final evaluated set.
        before=list(current); current,final_drops=self._apply_filters(current,final_matrix,final_metrics); dropped.extend(final_drops)
        if current!=before:
            final_matrix,final_meta=evaluate_with_callable(self.evaluator,task,current,calibration_responses); final_metrics=metrics_from_matrix(final_matrix,calibration_responses,self.config)
        warnings=behavioral_redundancy_warnings(current,final_matrix,threshold=self.config.behavioral_agreement_threshold) if self.config.enable_behavioral_warnings else []
        weights=correlation_aware_weights(current,final_matrix,final_metrics)
        trace.append({"iteration":self.config.max_iterations,"phase":"final","snapshot":{"rubrics":[r.to_dict() for r in current],"matrix":final_matrix,"metrics":{k:v.to_dict() for k,v in final_metrics.items()},"set_metrics":rubric_set_metrics(final_metrics)},"filter_decisions":final_drops,"behavioral_warnings":warnings,"rubric_weights":weights,"evaluator_metadata":final_meta})
        _snapshot(self.config.max_iterations, "final", current, final_metrics, broad=[r.rubric_id for r in current if final_metrics.get(r.rubric_id) and final_metrics[r.rubric_id].broad_candidate], dropped_this_round=final_drops, extra={"rubric_weights": weights})
        return OptimizationResult(task_id,original,current,final_metrics,final_matrix,tree,dropped,trace,weights,warnings,round_snapshots)
