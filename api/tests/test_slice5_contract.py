from cerebro.agent.models import (
    Confidence,
    CustomerCandidate,
    IdentificationOutcome,
    PaymentIdentification,
)
from cerebro.agent.runner import AgentRunResult
from cerebro.slack.pipeline import render_identification


def _customer(name: str = "Cliente Sintético") -> CustomerCandidate:
    return CustomerCandidate(
        customer_name=name,
        order_id="50000000-0000-0000-0000-000000000001",
        crm_url="https://tutu.ruuf.cl/account-receivables/crm-finops/order",
        reason="La identidad coincide.",
        evidence_ids=["ev_001"],
    )


def test_matched_renderer_is_concise() -> None:
    result = AgentRunResult(
        identification=PaymentIdentification(
            outcome=IdentificationOutcome.MATCHED,
            recommended_customer=_customer(),
            account_receivable_summary="Pago final 30%; saldo pendiente 2202000 CLP",
            confidence=Confidence.MEDIUM,
            investigation_summary=(
                "El nombre del transferente coincide con el cliente. "
                "El monto coincide exactamente con el saldo 2202000 CLP."
            ),
            unable_to_verify=["contexto de Vambe"],
        ),
        prompt_version="payment-identification-slice5-v1",
    )

    rendered = render_identification(result)

    assert len(rendered.splitlines()) <= 6
    assert len(rendered.split()) <= 110
    assert "*Cliente:*" in rendered
    assert "*Por qué:*" in rendered
    assert "Slice 5" in rendered


def test_ambiguous_no_customer_and_out_of_scope_render_distinctly() -> None:
    ambiguous = render_identification(
        AgentRunResult(
            identification=PaymentIdentification(
                outcome=IdentificationOutcome.AMBIGUOUS,
                confidence=Confidence.UNKNOWN,
                investigation_summary="Hay dos clientes con evidencia equivalente.",
                alternatives=[_customer("Alternativa")],
            ),
            prompt_version="payment-identification-slice5-v1",
        )
    )
    no_customer = render_identification(
        AgentRunResult(
            identification=PaymentIdentification(
                outcome=IdentificationOutcome.NO_CUSTOMER_FOUND,
                confidence=Confidence.UNKNOWN,
                investigation_summary="La búsqueda disponible no encontró candidatos elegibles.",
            ),
            prompt_version="payment-identification-slice5-v1",
        )
    )
    out_of_scope = render_identification(
        AgentRunResult(
            identification=PaymentIdentification(
                outcome=IdentificationOutcome.OUT_OF_SCOPE,
                confidence=Confidence.UNKNOWN,
                investigation_summary="Por ahora Cerebro sólo identifica pagos entrantes.",
            ),
            prompt_version="payment-identification-slice5-v1",
        )
    )

    assert "no sé" in ambiguous
    assert "*Opciones:*" in ambiguous
    assert "no encontré un cliente" in no_customer
    assert len(out_of_scope.splitlines()) == 2
    assert "sólo identifica pagos entrantes" in out_of_scope


def test_renderer_enforces_absolute_length_caps_with_long_fields() -> None:
    long_text = " ".join(["evidencia"] * 100)
    alternatives = [_customer(" ".join([f"Nombre{index}"] * 20)) for index in range(3)]
    for candidate in alternatives:
        candidate.reason = long_text
    matched = render_identification(
        AgentRunResult(
            identification=PaymentIdentification(
                outcome=IdentificationOutcome.MATCHED,
                recommended_customer=_customer(" ".join(["Cliente"] * 30)),
                account_receivable_summary=long_text,
                confidence=Confidence.MEDIUM,
                investigation_summary=long_text,
                unable_to_verify=[long_text, long_text, long_text],
                alternatives=alternatives,
            ),
            prompt_version="payment-identification-slice5-v1",
        )
    )
    ambiguous = render_identification(
        AgentRunResult(
            identification=PaymentIdentification(
                outcome=IdentificationOutcome.AMBIGUOUS,
                confidence=Confidence.UNKNOWN,
                investigation_summary=long_text,
                unable_to_verify=[long_text, long_text, long_text],
                alternatives=alternatives,
            ),
            prompt_version="payment-identification-slice5-v1",
        )
    )

    assert len(matched.splitlines()) <= 6
    assert len(matched.split()) <= 130
    assert len(ambiguous.splitlines()) <= 4
    assert len(ambiguous.split()) <= 130
