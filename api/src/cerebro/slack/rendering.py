"""Bounded Slack presentation, independent of database/job orchestration."""

import re

from cerebro.agent.models import (
    Confidence,
    CustomerCandidate,
    EvidenceKind,
    EvidencePolarity,
    IdentificationOutcome,
    PaymentIdentification,
)
from cerebro.agent.runner import AgentRunResult, GeneralAgentRunResult, ImageIngestion, RunnerResult
from cerebro.config import get_config


def render_identification(
    run_result: AgentRunResult, image_ingestion: ImageIngestion | None = None
) -> str:
    result = run_result.identification
    confidence = {
        Confidence.HIGH: "alta",
        Confidence.MEDIUM: "media",
        Confidence.LOW: "baja",
        Confidence.UNKNOWN: "no sé",
    }[result.confidence]
    if result.outcome is IdentificationOutcome.OUT_OF_SCOPE:
        return f"*Resultado:* {_clip_words(result.investigation_summary, 25)}"

    image_note = ""
    if image_ingestion and image_ingestion.unprocessed:
        image_note = (
            f"{image_ingestion.unprocessed}/{image_ingestion.requested} capturas no procesadas"
        )
    unable = list(result.unable_to_verify)
    if image_note and image_note not in unable:
        unable.append(image_note)
    # Always preserve the deterministic image notice, even when several other checks failed.
    details = [item for item in unable if item != image_note][: 2 if image_note else 3]
    if image_note:
        details.append(image_note)
    pending = ", ".join(_clip_words(item, 5) for item in details)

    if result.outcome is IdentificationOutcome.MATCHED and result.recommended_customer:
        candidate = result.recommended_customer
        lines = [
            f"*Resultado:* coincidencia — confianza {confidence}.",
            f"*Cliente:* {_customer_link(candidate)}",
        ]
        if result.account_receivable_summary:
            lines.append(f"*Cuenta:* {_clip_words(result.account_receivable_summary, 16)}")
        lines.append(f"*Por qué:* {_clip_words(result.investigation_summary, 34)}")
        tail: list[str] = []
        if pending:
            tail.append(f"*No pude verificar:* {pending}")
        if result.alternatives:
            tail.append(f"*Alternativas:* {_render_alternatives(result)}")
        if tail:
            lines.append(" · ".join(tail))
        return "\n".join(lines)

    if result.outcome is IdentificationOutcome.NO_CUSTOMER_FOUND:
        lines = [
            "*Resultado:* no encontré un cliente.",
            f"*Por qué:* {_clip_words(result.investigation_summary, 24)}",
        ]
        if pending:
            lines.append(f"*No pude verificar:* {pending}")
        if result.clarification_question:
            lines.append(_clip_words(" ".join(result.clarification_question.split()), 20))
        return "\n".join(lines)

    lines = [
        "*Resultado:* no sé; FinOps debe revisar el pago.",
        f"*Por qué:* {_clip_words(result.investigation_summary, 24)}",
    ]
    details: list[str] = []
    if result.alternatives:
        details.append(f"*Opciones:* {_render_alternatives(result)}")
    if pending:
        details.append(f"*Falta:* {pending}")
    if details:
        lines.append(" · ".join(details))
    if result.clarification_question:
        lines.append(_clip_words(" ".join(result.clarification_question.split()), 20))
    return "\n".join(lines)


def render_general_answer(
    run_result: GeneralAgentRunResult, image_ingestion: ImageIngestion | None = None
) -> str:
    image_note = None
    if image_ingestion and image_ingestion.unprocessed:
        image_note = (
            f"No pude procesar {image_ingestion.unprocessed} de "
            f"{image_ingestion.requested} capturas."
        )
    return _limit_complete_answer(
        run_result.response.answer,
        get_config().general_max_words,
        required_suffix=image_note,
    )


def render_response(run_result: RunnerResult, image_ingestion: ImageIngestion | None = None) -> str:
    if isinstance(run_result, GeneralAgentRunResult):
        return render_general_answer(run_result, image_ingestion)
    return render_identification(run_result, image_ingestion)


def _clip_words(value: str, limit: int) -> str:
    value = re.sub(r"(?:\.{3}|…)\s*$", ".", value.strip())
    words = value.split()
    if len(words) <= limit:
        return value.strip()
    sentences = re.split(r"(?<=[.!?])\s+", value.strip())
    selected: list[str] = []
    for sentence in sentences:
        if len(" ".join([*selected, sentence]).split()) > limit:
            break
        selected.append(sentence)
    return " ".join(selected) or "Detalle pendiente."


def _limit_complete_answer(value: str, limit: int, *, required_suffix: str | None = None) -> str:
    answer = re.sub(r"(?:\.{3}|…)\s*$", ".", value.strip())
    suffix_words = required_suffix.split() if required_suffix else []
    available = max(limit - len(suffix_words), 1)
    if len(answer.split()) <= available:
        parts = [answer]
    else:
        units = [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", answer) if item.strip()]
        parts: list[str] = []
        used = 0
        for unit in units:
            size = len(unit.split())
            if used + size > available:
                break
            parts.append(unit)
            used += size
        if not parts:
            parts = [
                "Mi respuesta excedió el formato breve de Slack. "
                "Pídeme que la divida y desplegaré el resto de mi intelecto."
            ]
    if required_suffix:
        parts.append(required_suffix)
    return "\n".join(parts)


def _render_alternatives(result: PaymentIdentification) -> str:
    labels = {
        EvidenceKind.EXACT_ADDRESS: "dirección exacta",
        EvidenceKind.PARTIAL_ADDRESS: "dirección parcial",
        EvidenceKind.CUSTOMER_NAME: "nombre del cliente",
        EvidenceKind.SIGNEE_NAME: "nombre de firmante",
        EvidenceKind.NAME_FRAGMENT: "fragmento de nombre",
        EvidenceKind.RUT: "RUT",
        EvidenceKind.EMAIL: "correo",
        EvidenceKind.PHONE: "teléfono",
        EvidenceKind.BANK_NAME: "titular bancario",
        EvidenceKind.BANK_ACCOUNT: "cuenta bancaria",
        EvidenceKind.EXACT_OUTSTANDING: "saldo exacto",
        EvidenceKind.PARTIAL_PAYMENT: "abono posible",
        EvidenceKind.VAMBE_CONTEXT: "contexto de Vambe",
    }
    evidence = {item.evidence_id: item for item in result.evidence}

    def compact_reason(candidate: CustomerCandidate) -> str:
        reasons = list(
            dict.fromkeys(
                labels[signal.kind]
                for evidence_id in candidate.evidence_ids
                if (signal := evidence.get(evidence_id)) is not None
                and signal.polarity is EvidencePolarity.SUPPORTING
                and signal.kind in labels
            )
        )
        return " + ".join(reasons[:2]) or "evidencia por verificar"

    return "; ".join(
        f"{_customer_link(candidate, max_name_words=5)} — {compact_reason(candidate)}"
        for candidate in result.alternatives[:3]
    )


def _customer_link(candidate: CustomerCandidate, *, max_name_words: int = 8) -> str:
    customer_name = " ".join(candidate.customer_name.split()[:max_name_words])
    return f"<{candidate.crm_url}|{customer_name}>"
