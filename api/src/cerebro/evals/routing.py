"""Versioned offline corpus and safety grading for conversational routing."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from cerebro.agent.models import RequestKind


class RoutingCase(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    text: str
    expected: RequestKind
    prior_thread: list[str] = Field(default_factory=list)
    has_triggering_image: bool = False


class RoutingCorpus(BaseModel):
    version: str
    cases: list[RoutingCase] = Field(min_length=1)


def load_routing_corpus(path: Path | None = None) -> RoutingCorpus:
    source = path or Path(__file__).with_name("routing_cases.yaml")
    return RoutingCorpus.model_validate(yaml.safe_load(source.read_text(encoding="utf-8")))


def grade_routes(corpus: RoutingCorpus, actual: dict[str, RequestKind]) -> dict[str, object]:
    missing = [case.id for case in corpus.cases if case.id not in actual]
    payment_to_general = [
        case.id
        for case in corpus.cases
        if case.expected is RequestKind.PAYMENT_IDENTIFICATION
        and actual.get(case.id) is RequestKind.GENERAL
    ]
    mismatches = [case.id for case in corpus.cases if actual.get(case.id) != case.expected]
    return {
        "version": corpus.version,
        "case_count": len(corpus.cases),
        "passed": not missing and not mismatches and not payment_to_general,
        "missing": missing,
        "mismatches": mismatches,
        "payment_to_general": payment_to_general,
    }
