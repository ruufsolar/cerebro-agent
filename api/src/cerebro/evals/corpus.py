from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from cerebro.agent.data_tools import ToolObservation
from cerebro.agent.models import Confidence, EvidenceKind, IdentificationOutcome


class EvalCase(BaseModel):
    id: str
    prompt: str
    expected_outcome: IdentificationOutcome
    expected_confidence: Confidence = Confidence.UNKNOWN
    expected_order_id: str | None = None
    allowed_alternative_order_ids: list[str] = Field(default_factory=list)
    required_evidence_kinds: list[EvidenceKind] = Field(default_factory=list)
    forbidden_evidence_kinds: list[EvidenceKind] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    image_text: list[str] = Field(default_factory=list)
    observations: dict[str, ToolObservation] = Field(default_factory=dict)


class EvalCorpus(BaseModel):
    version: str
    cases: list[EvalCase]


def load_corpus(path: Path | None = None) -> EvalCorpus:
    source = path or Path(__file__).with_name("cases.yaml")
    return EvalCorpus.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))
