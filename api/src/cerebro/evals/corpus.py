from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from cerebro.agent.data_tools import ToolObservation
from cerebro.agent.models import Confidence


class EvalCase(BaseModel):
    id: str
    prompt: str
    expected_confidence: Confidence
    expected_order_id: str | None = None
    observations: dict[str, ToolObservation] = Field(default_factory=dict)


class EvalCorpus(BaseModel):
    version: str
    cases: list[EvalCase]


def load_corpus(path: Path | None = None) -> EvalCorpus:
    source = path or Path(__file__).with_name("cases.yaml")
    return EvalCorpus.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))
