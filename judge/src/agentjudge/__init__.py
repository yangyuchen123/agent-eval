"""Independent evidence-aware Judge prototype."""
from .agents import QuestionJudgeDeps, build_question_agent
from .catalog import EvidenceCatalog
from .baselines import FullTraceJudgeService, StaticRetrievalJudgeService
from .evidence import EvidenceProvider, InMemoryEvidenceProvider
from .models import Claim, EvidenceQuery, EvidenceRecord, FinalJudgment, JudgeRequest, QuestionJudgment
from .service import JudgeService, QuestionJudgeService
from .scoring import FrozenEvidenceScoringService, FrozenScoringDecision, build_frozen_scoring_agent
from .investigation import (InvestigationFinding, RetrievalInvestigation,
                            RetrievalInvestigationService, build_retrieval_investigator)

__all__ = [
    "Claim", "EvidenceCatalog", "FullTraceJudgeService", "StaticRetrievalJudgeService", "EvidenceProvider", "EvidenceQuery", "EvidenceRecord",
    "FinalJudgment", "InMemoryEvidenceProvider", "JudgeService", "JudgeRequest",
    "QuestionJudgeDeps", "QuestionJudgment", "QuestionJudgeService", "JudgeService",
    "build_question_agent", "FrozenEvidenceScoringService", "FrozenScoringDecision",
    "build_frozen_scoring_agent", "InvestigationFinding", "RetrievalInvestigation",
    "RetrievalInvestigationService", "build_retrieval_investigator",
]
from .agents import build_joint_question_agent
from .models import JointQuestionJudgment
from .service import JointQuestionJudgeService
from .two_stage import EvidenceCollection, EvidenceItem, TwoStageJointJudgeService
from .two_stage import EvidenceThenPerQuestionJudgeService

from .protocols import (JudgeProtocol, ProtocolResult, OriginalIndependentRubricProtocol, JointMultiRubricProtocol, SharedEvidenceJointProtocol, SharedEvidenceIndependentScoreProtocol, build_protocol, protocol_names)
