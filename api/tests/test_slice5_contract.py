from cerebro.agent.models import (
    Confidence,
    CustomerCandidate,
    GeneralAnswer,
    IdentificationOutcome,
    PaymentIdentification,
)
from cerebro.agent.runner import AgentRunResult, GeneralAgentRunResult, ImageIngestion
from cerebro.slack.pipeline import render_general_answer, render_identification


def test_payment_renderer_keeps_whole_sentences_and_image_notice() -> None:
    summary = "La identidad coincide. " + " ".join(["explicación"] * 90) + "."
    rendered = render_identification(
        AgentRunResult(
            identification=PaymentIdentification(
                confidence=Confidence.UNKNOWN,
                investigation_summary=summary,
                unable_to_verify=["cliente", "cuenta", "contexto", "fecha"],
            )
        ),
        ImageIngestion(requested=2, downloaded=1, rejected=1),
    )
    assert "*Por qué:* La identidad coincide." in rendered
    assert "explicación" not in rendered
    assert "1/2 capturas no procesadas" in rendered
    assert "…" not in rendered


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
    assert rendered.startswith("*Resultado:*")
    assert "*Cliente:*" in rendered
    assert "*Por qué:*" in rendered
    assert "Slice" not in rendered
    assert "Piloto" not in rendered


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
    assert len(out_of_scope.splitlines()) == 1
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
    assert "…" not in matched
    assert "…" not in ambiguous


def test_general_renderer_keeps_complete_sentences_and_image_limit() -> None:
    answer = " ".join(f"Esta es la observación número {index}." for index in range(1, 80))
    rendered = render_general_answer(
        GeneralAgentRunResult(response=GeneralAnswer(answer=answer)),
        ImageIngestion(requested=2, downloaded=1, rejected=1),
    )

    assert len(rendered.split()) <= 180
    assert rendered.endswith("No pude procesar 1 de 2 capturas.")
    assert "..." not in rendered
    assert "…" not in rendered
    assert rendered.splitlines()[0].endswith(".")


def test_general_renderer_removes_a_trailing_ellipsis() -> None:
    rendered = render_general_answer(
        GeneralAgentRunResult(response=GeneralAnswer(answer="Mi brillante conclusión…"))
    )

    assert rendered == "Mi brillante conclusión."
