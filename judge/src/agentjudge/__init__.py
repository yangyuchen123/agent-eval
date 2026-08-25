"""Independent evidence-aware Judge prototype."""
from .agents import QuestionJudgeDeps, build_question_agent
from .catalog import EvidenceCatalog
from .evidence import EvidenceProvider, InMemoryEvidenceProvider
from .models import Claim, EvidenceQuery, EvidenceRecord, FinalJudgment, JudgeRequest, QuestionJudgment
from .service import JudgeService, QuestionJudgeService

__all__ = [
    "Claim", "EvidenceCatalog", "EvidenceProvider", "EvidenceQuery", "EvidenceRecord",
    "FinalJudgment", "InMemoryEvidenceProvider", "JudgeService", "JudgeRequest",
    "QuestionJudgeDeps", "QuestionJudgment", "QuestionJudgeService", "JudgeService",
    "build_question_agent",
]
