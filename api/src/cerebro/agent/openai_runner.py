"""OpenAI Agents SDK runner backed by an Azure OpenAI v1 endpoint."""

import asyncio
import base64
import logging
import os
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, cast
from urllib.parse import quote

from agents import Agent, ModelSettings, RunConfig, Runner, function_tool, set_tracing_disabled
from agents.exceptions import (
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelRefusalError,
    ModelTimeoutError,
)
from agents.models.openai_chatcompletions import OpenAIChatCompletionsModel
from agents.models.openai_responses import OpenAIResponsesModel
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from cerebro.agent.data_tools import (
    EmptyInvestigationData,
    InvestigationCandidate,
    InvestigationData,
    KnowledgeQuery,
    PaymentCandidateQuery,
    ReadonlySqlQuery,
    SchemaQuery,
    ToolObservation,
    ToolRequest,
    VambeQuery,
    VerifyCandidateQuery,
    safe_input_summary,
)
from cerebro.agent.models import (
    AgentStep,
    AgentUsage,
    CompletionReason,
    Confidence,
    CustomerCandidate,
    EvidenceKind,
    EvidencePolarity,
    EvidenceSignal,
    IdentificationOutcome,
    PaymentIdentification,
    ToolAuditRecord,
    UnverifiedField,
)
from cerebro.agent.prompt import TRANSCRIPT_LIMIT, load_prompt
from cerebro.agent.runner import (
    AgentRunFailure,
    AgentRunInput,
    AgentRunner,
    AgentRunResult,
    FakeAgentRunner,
)
from cerebro.config import AppConfig, get_config
from cerebro.observability import log_event
from cerebro.replica.database import ReplicaDatabase
from cerebro.replica.investigation import ReplicaInvestigationData
from cerebro.replica.scope import load_knowledge

os.environ.setdefault("OPENAI_AGENTS_DONT_LOG_MODEL_DATA", "1")
os.environ.setdefault("OPENAI_AGENTS_DONT_LOG_TOOL_DATA", "1")
set_tracing_disabled(True)

logger = logging.getLogger(__name__)


class ModelCandidate(BaseModel):
    order_id: str
    account_receivable_id: str | None = None
    evidence_ids: list[str] = Field(min_length=1, max_length=8)


class ModelIdentification(BaseModel):
    outcome: IdentificationOutcome
    recommended_customer: ModelCandidate | None = None
    unable_to_verify: list[UnverifiedField] = Field(default_factory=list, max_length=5)
    alternatives: list[ModelCandidate] = Field(default_factory=list, max_length=3)


class ToolBudgetExceeded(RuntimeError):
    pass


_DIRECT_IDENTITY = {
    EvidenceKind.CUSTOMER_NAME,
    EvidenceKind.RUT,
    EvidenceKind.EMAIL,
    EvidenceKind.PHONE,
}
_BANK_IDENTITY = {EvidenceKind.BANK_NAME, EvidenceKind.BANK_ACCOUNT}
_HARD_CONTRADICTIONS = {
    EvidenceKind.AMOUNT_EXCEEDS_OUTSTANDING,
    EvidenceKind.CURRENCY_MISMATCH,
}
_UNVERIFIED_LABELS = {
    UnverifiedField.AMOUNT: "monto",
    UnverifiedField.GLOSA: "glosa",
    UnverifiedField.TRANSFEROR: "transferente",
    UnverifiedField.DATE: "fecha",
    UnverifiedField.CUSTOMER_IDENTITY: "identidad del cliente",
    UnverifiedField.ACCOUNT_RECEIVABLE: "cuenta por cobrar",
    UnverifiedField.VAMBE_CONTEXT: "contexto de Vambe",
    UnverifiedField.PAYMENT_EVIDENCE: "evidencia del pago",
}


@dataclass
class RunState:
    max_tool_calls: int
    calls: list[ToolAuditRecord] = field(default_factory=list)
    candidate_order_ids: set[str] = field(default_factory=set)
    candidates: dict[tuple[str, str | None], InvestigationCandidate] = field(default_factory=dict)
    verified_candidates: dict[tuple[str, str | None], InvestigationCandidate] = field(
        default_factory=dict
    )
    evidence: dict[str, EvidenceSignal] = field(default_factory=dict)
    source_available: dict[str, bool] = field(default_factory=dict)
    candidate_search_succeeded: bool = False
    candidate_search_count: int | None = None
    candidate_search_conclusive: bool = False

    def _register_signal(self, signal: EvidenceSignal) -> EvidenceSignal:
        registered = signal.model_copy(update={"evidence_id": f"ev_{len(self.evidence) + 1:03d}"})
        self.evidence[registered.evidence_id] = registered
        return registered

    def _register_observation(
        self, name: str, request: ToolRequest, observation: ToolObservation
    ) -> None:
        self.source_available[name] = observation.available
        if name == "search_payment_candidates" and observation.available:
            self.candidate_search_succeeded = True
            self.candidate_search_count = max(
                self.candidate_search_count or 0, len(observation.candidates)
            )
            if isinstance(request, PaymentCandidateQuery):
                self.candidate_search_conclusive = self.candidate_search_conclusive or bool(
                    any(
                        (
                            request.glosa_or_address,
                            request.transferor_name,
                            request.transferor_rut,
                            request.origin_account_number,
                            request.email,
                            request.phone,
                        )
                    )
                )
        observation.evidence = [self._register_signal(item) for item in observation.evidence]
        for candidate in observation.candidates:
            candidate.evidence = [self._register_signal(item) for item in candidate.evidence]
            order_id = str(candidate.order_id)
            receivable_id = (
                str(candidate.account_receivable_id) if candidate.account_receivable_id else None
            )
            key = (order_id, receivable_id)
            self.candidate_order_ids.add(order_id)
            self.candidates[key] = candidate
            if candidate.verified:
                self.verified_candidates[key] = candidate

    async def invoke(self, name: str, request: ToolRequest, call: Any) -> str:
        sequence = len(self.calls) + 1
        if sequence > self.max_tool_calls:
            raise ToolBudgetExceeded(f"tool call budget exhausted at {self.max_tool_calls}")
        started = monotonic()
        safe_input = safe_input_summary(request)
        try:
            observation: ToolObservation = await call(request)
            self._register_observation(name, request, observation)
            safe_output = observation.safe_audit_summary()
            self.calls.append(
                ToolAuditRecord(
                    sequence=sequence,
                    tool_name=name,
                    status="succeeded",
                    input=safe_input,
                    output=safe_output,
                    duration_ms=int((monotonic() - started) * 1_000),
                    query_fingerprint=observation.audit.query_fingerprint,
                    referenced_relations=observation.audit.referenced_relations,
                    row_count=observation.audit.row_count,
                    truncated=observation.audit.truncated,
                )
            )
            return observation.model_dump_json()
        except Exception as exc:
            self.source_available[name] = False
            self.calls.append(
                ToolAuditRecord(
                    sequence=sequence,
                    tool_name=name,
                    status="failed",
                    input=safe_input,
                    duration_ms=int((monotonic() - started) * 1_000),
                    error=type(exc).__name__,
                )
            )
            log_event(
                logger,
                "investigation_tool_unavailable",
                level=logging.WARNING,
                error_type=type(exc).__name__,
                state="unavailable",
            )
            return ToolObservation(
                source=name,
                available=False,
                summary="La fuente de datos falló temporalmente durante esta investigación.",
                limitations=[
                    "La consulta no produjo evidencia; se debe reintentar o revisar manualmente."
                ],
            ).model_dump_json()


def normalize_azure_base_url(endpoint: str) -> str:
    base = endpoint.rstrip("/")
    if base.endswith("/openai/v1"):
        return f"{base}/"
    return f"{base}/openai/v1/"


def build_input_items(run_input: AgentRunInput) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for message in run_input.transcript[-TRANSCRIPT_LIMIT:]:
        role = "assistant" if message.direction == "outbound" else "user"
        text = message.text or ""
        if message.attachments:
            if message.slack_message_ts == run_input.trigger_slack_message_ts:
                text = (
                    f"{text}\n[El mensaje actual incluye {len(message.attachments)} "
                    "captura(s); usa solamente las imágenes adjuntas a este turno.]"
                ).strip()
            else:
                text = (
                    f"{text}\n[Hay {len(message.attachments)} captura(s) histórica(s) "
                    "sanitizada(s), no reenviadas al modelo.]"
                ).strip()
        if (
            role == "user"
            and message.slack_message_ts == run_input.trigger_slack_message_ts
            and run_input.image_paths
        ):
            content: list[dict[str, str]] = [{"type": "input_text", "text": text}]
            for path in run_input.image_paths:
                mimetype = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                }[path.suffix.lower()]
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                content.append(
                    {
                        "type": "input_image",
                        "image_url": f"data:{mimetype};base64,{encoded}",
                        "detail": "high",
                    }
                )
            items.append({"role": role, "content": content})
        else:
            items.append({"role": role, "content": text})
    return items


def _unknown(summary: str, reason: CompletionReason) -> AgentRunResult:
    return AgentRunResult(
        identification=PaymentIdentification(
            confidence=Confidence.UNKNOWN,
            investigation_summary=summary,
            unable_to_verify=["cliente", "cuenta por cobrar", "evidencia en fuentes reales"],
        ),
        completion_reason=reason,
    )


class OpenAIAgentsRunner:
    def __init__(
        self,
        config: AppConfig,
        *,
        data: InvestigationData | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.config = config
        self.data = data or EmptyInvestigationData()
        self.client = client or AsyncOpenAI(
            base_url=normalize_azure_base_url(config.azure_openai_endpoint),
            api_key=config.azure_openai_api_key,
            default_headers={"api-key": config.azure_openai_api_key},
        )

    @property
    def supports_image_input(self) -> bool:
        return True

    async def close(self) -> None:
        await self.data.close()
        await self.client.close()

    async def start(self) -> None:
        await self.data.start()

    def _model(self) -> OpenAIResponsesModel | OpenAIChatCompletionsModel:
        if self.config.azure_openai_use_responses:
            return OpenAIResponsesModel(
                model=self.config.azure_deployment_main,
                openai_client=self.client,
            )
        return OpenAIChatCompletionsModel(
            model=self.config.azure_deployment_main,
            openai_client=self.client,
        )

    def _tools(self, state: RunState) -> list[Any]:
        data = self.data

        @function_tool(failure_error_function=None)
        async def read_finops_knowledge(request: KnowledgeQuery) -> str:
            """Lee política, alcance o limitaciones aprobadas para identificar pagos."""
            return await state.invoke("read_finops_knowledge", request, data.read_finops_knowledge)

        @function_tool(failure_error_function=None)
        async def describe_database_tables(request: SchemaQuery) -> str:
            """Describe columnas y gotchas de hasta ocho tablas permitidas antes de escribir SQL."""
            return await state.invoke(
                "describe_database_tables", request, data.describe_database_tables
            )

        @function_tool(failure_error_function=None)
        async def search_payment_candidates(request: PaymentCandidateQuery) -> str:
            """Busca candidatos por glosa, identidad y saldo; no verifica la propuesta final."""
            return await state.invoke(
                "search_payment_candidates", request, data.search_payment_candidates
            )

        @function_tool(failure_error_function=None)
        async def verify_payment_candidate(request: VerifyCandidateQuery) -> str:
            """Verifica orden y cuenta por cobrar; es obligatorio antes de recomendar."""
            return await state.invoke(
                "verify_payment_candidate", request, data.verify_payment_candidate
            )

        @function_tool(failure_error_function=None)
        async def search_vambe_messages(request: VambeQuery) -> str:
            """Busca texto de Vambe acotado a una orden o teléfono; nunca hace un escaneo global."""
            return await state.invoke("search_vambe_messages", request, data.search_vambe_messages)

        @function_tool(failure_error_function=None)
        async def run_readonly_sql(request: ReadonlySqlQuery) -> str:
            """Ejecuta SELECT PostgreSQL acotado por AST, relaciones, funciones, filas y tiempo."""
            return await state.invoke("run_readonly_sql", request, data.run_readonly_sql)

        return [
            read_finops_knowledge,
            describe_database_tables,
            search_payment_candidates,
            verify_payment_candidate,
            search_vambe_messages,
            run_readonly_sql,
        ]

    @staticmethod
    def _resolve_candidate(
        value: ModelCandidate, state: RunState
    ) -> tuple[tuple[str, str | None], InvestigationCandidate] | None:
        key = (value.order_id, value.account_receivable_id)
        verified = state.verified_candidates.get(key)
        if verified is not None:
            return key, verified
        if value.account_receivable_id is not None:
            return None
        matches = [
            (candidate_key, candidate)
            for candidate_key, candidate in state.verified_candidates.items()
            if candidate_key[0] == value.order_id
        ]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _signals_for_candidate(
        key: tuple[str, str | None], state: RunState
    ) -> list[EvidenceSignal]:
        order_id, receivable_id = key
        return [
            signal
            for signal in state.evidence.values()
            if signal.order_id == order_id and signal.account_receivable_id in {None, receivable_id}
        ]

    @staticmethod
    def _selected_signals(
        value: ModelCandidate,
        key: tuple[str, str | None],
        state: RunState,
    ) -> list[EvidenceSignal] | None:
        allowed = {
            item.evidence_id: item for item in OpenAIAgentsRunner._signals_for_candidate(key, state)
        }
        if not value.evidence_ids or any(item not in allowed for item in value.evidence_ids):
            return None
        signals = [allowed[item] for item in dict.fromkeys(value.evidence_ids)]
        if not any(item.polarity is EvidencePolarity.SUPPORTING for item in signals):
            return None
        return signals

    @staticmethod
    def _material_contradiction(signals: list[EvidenceSignal]) -> bool:
        kinds = {item.kind for item in signals if item.polarity is EvidencePolarity.SUPPORTING}
        contradictions = {
            item.kind for item in signals if item.polarity is EvidencePolarity.CONTRADICTING
        }
        if contradictions & _HARD_CONTRADICTIONS:
            return True
        if EvidenceKind.IDENTITY_CONFLICT in contradictions:
            return not (
                EvidenceKind.VAMBE_CONTEXT in kinds
                and (EvidenceKind.EXACT_OUTSTANDING in kinds or EvidenceKind.EXACT_ADDRESS in kinds)
            )
        return False

    @staticmethod
    def _rank(signals: list[EvidenceSignal]) -> tuple[int, ...]:
        supporting = {item.kind for item in signals if item.polarity is EvidencePolarity.SUPPORTING}
        contradiction_count = sum(
            item.polarity is EvidencePolarity.CONTRADICTING for item in signals
        )
        return (
            int(EvidenceKind.EXACT_ADDRESS in supporting),
            sum(item in supporting for item in _DIRECT_IDENTITY),
            int(EvidenceKind.EXACT_OUTSTANDING in supporting),
            int(EvidenceKind.VAMBE_CONTEXT in supporting),
            int(EvidenceKind.PARTIAL_ADDRESS in supporting),
            int(EvidenceKind.PARTIAL_PAYMENT in supporting),
            -contradiction_count,
        )

    @staticmethod
    def _confidence(signals: list[EvidenceSignal]) -> Confidence:
        if OpenAIAgentsRunner._material_contradiction(signals):
            return Confidence.UNKNOWN
        supporting = {item.kind for item in signals if item.polarity is EvidencePolarity.SUPPORTING}
        if EvidenceKind.EXACT_ADDRESS in supporting:
            return Confidence.HIGH
        if supporting & _DIRECT_IDENTITY:
            return Confidence.MEDIUM
        if EvidenceKind.EXACT_OUTSTANDING in supporting and (
            EvidenceKind.VAMBE_CONTEXT in supporting
            or EvidenceKind.PARTIAL_ADDRESS in supporting
            or bool(supporting & _BANK_IDENTITY)
        ):
            return Confidence.MEDIUM
        return Confidence.UNKNOWN

    @staticmethod
    def _deduplicate_signals(signals: list[EvidenceSignal]) -> list[EvidenceSignal]:
        result: list[EvidenceSignal] = []
        seen: set[str] = set()
        for signal in signals:
            identity = signal.evidence_id or "|".join(
                (
                    signal.order_id or "",
                    signal.account_receivable_id or "",
                    signal.kind,
                    signal.polarity,
                    signal.description,
                )
            )
            if identity not in seen:
                seen.add(identity)
                result.append(signal)
        return result

    def _customer(
        self,
        value: ModelCandidate,
        verified: InvestigationCandidate,
        signals: list[EvidenceSignal],
    ) -> CustomerCandidate:
        order_id = quote(value.order_id, safe="")
        url = f"{self.config.crm_finops_base_url.rstrip('/')}/{order_id}"
        supporting = list(
            dict.fromkeys(
                item.description for item in signals if item.polarity is EvidencePolarity.SUPPORTING
            )
        )[:2]
        return CustomerCandidate(
            customer_name=verified.customer_name,
            order_id=value.order_id,
            crm_url=url,
            reason=" ".join(supporting),
            evidence_ids=[item.evidence_id for item in signals],
        )

    @staticmethod
    def _unable_to_verify(output: ModelIdentification, state: RunState) -> list[str]:
        values = [_UNVERIFIED_LABELS[item] for item in output.unable_to_verify]
        source_labels = {
            "search_payment_candidates": "búsqueda de clientes",
            "verify_payment_candidate": "verificación del cliente",
            "search_vambe_messages": "contexto de Vambe",
        }
        values.extend(
            label
            for source, label in source_labels.items()
            if state.source_available.get(source) is False
        )
        return list(dict.fromkeys(values))[:3]

    @staticmethod
    def _summary(signals: list[EvidenceSignal], fallback: str) -> str:
        canonical = OpenAIAgentsRunner._deduplicate_signals(signals)
        supporting = list(
            dict.fromkeys(
                item.description
                for item in canonical
                if item.polarity is EvidencePolarity.SUPPORTING
            )
        )[:3]
        contradicting = list(
            dict.fromkeys(
                item.description
                for item in canonical
                if item.polarity is EvidencePolarity.CONTRADICTING
            )
        )[:2]
        return " ".join([*supporting, *contradicting]) or fallback

    def _alternatives(
        self, values: list[ModelCandidate], state: RunState
    ) -> tuple[list[CustomerCandidate], list[EvidenceSignal]]:
        resolved: list[tuple[tuple[int, ...], CustomerCandidate, list[EvidenceSignal]]] = []
        seen: set[tuple[str, str | None]] = set()
        for value in values:
            match = self._resolve_candidate(value, state)
            if match is None or match[0] in seen:
                continue
            key, verified = match
            signals = self._selected_signals(value, key, state)
            if signals is None:
                continue
            seen.add(key)
            resolved.append(
                (self._rank(signals), self._customer(value, verified, signals), signals)
            )
        resolved.sort(key=lambda item: item[0], reverse=True)
        candidates = [item[1] for item in resolved[:3]]
        evidence = [signal for item in resolved[:3] for signal in item[2]]
        return candidates, self._deduplicate_signals(evidence)

    def _ambiguous(
        self,
        output: ModelIdentification,
        state: RunState,
        *,
        summary: str = "La evidencia no permite elegir un único cliente.",
        include_recommendation: bool = False,
    ) -> PaymentIdentification:
        values = list(output.alternatives)
        if include_recommendation and output.recommended_customer is not None:
            values.insert(0, output.recommended_customer)
        alternatives, evidence = self._alternatives(values, state)
        return PaymentIdentification(
            outcome=IdentificationOutcome.AMBIGUOUS,
            confidence=Confidence.UNKNOWN,
            investigation_summary=summary,
            unable_to_verify=self._unable_to_verify(output, state),
            alternatives=alternatives,
            evidence=evidence,
        )

    def _map_output(self, output: ModelIdentification, state: RunState) -> PaymentIdentification:
        if output.outcome is IdentificationOutcome.OUT_OF_SCOPE:
            return PaymentIdentification(
                outcome=IdentificationOutcome.OUT_OF_SCOPE,
                confidence=Confidence.UNKNOWN,
                investigation_summary=(
                    "Por ahora Cerebro sólo identifica pagos entrantes para FinOps."
                ),
            )
        if output.outcome is IdentificationOutcome.NO_CUSTOMER_FOUND:
            if (
                state.candidate_search_succeeded
                and state.candidate_search_conclusive
                and state.candidate_search_count == 0
            ):
                return PaymentIdentification(
                    outcome=IdentificationOutcome.NO_CUSTOMER_FOUND,
                    confidence=Confidence.UNKNOWN,
                    investigation_summary=(
                        "La búsqueda no encontró cuentas por cobrar elegibles que coincidan."
                    ),
                    unable_to_verify=self._unable_to_verify(output, state),
                )
            return self._ambiguous(
                output,
                state,
                summary="No fue posible completar una búsqueda suficiente para descartar clientes.",
            )
        if output.outcome is IdentificationOutcome.AMBIGUOUS:
            return self._ambiguous(output, state)
        if output.recommended_customer is None:
            return self._ambiguous(
                output,
                state,
                summary="El resultado no incluyó un cliente verificable.",
            )

        match = self._resolve_candidate(output.recommended_customer, state)
        if match is None:
            return self._ambiguous(
                output,
                state,
                summary="La propuesta no fue verificada por las herramientas.",
                include_recommendation=True,
            )
        key, verified = match
        selected = self._selected_signals(output.recommended_customer, key, state)
        if selected is None:
            return self._ambiguous(
                output,
                state,
                summary="La propuesta no citó evidencia válida de esta investigación.",
                include_recommendation=True,
            )
        all_signals = self._signals_for_candidate(key, state)
        contradictions = [
            item for item in all_signals if item.polarity is EvidencePolarity.CONTRADICTING
        ]
        grounded = self._deduplicate_signals([*selected, *contradictions])
        confidence = self._confidence(grounded)
        if confidence is Confidence.UNKNOWN:
            return self._ambiguous(
                output,
                state,
                summary=self._summary(
                    grounded, "La evidencia disponible es insuficiente o contradictoria."
                ),
                include_recommendation=True,
            )

        target_rank = self._rank(all_signals)
        competitor_exists = any(
            candidate_key != key
            and self._rank(self._signals_for_candidate(candidate_key, state)) >= target_rank
            for candidate_key in state.verified_candidates
        )
        if competitor_exists:
            return self._ambiguous(
                output,
                state,
                summary="Hay más de un cliente con evidencia de igual o mayor precedencia.",
                include_recommendation=True,
            )

        customer = self._customer(output.recommended_customer, verified, grounded)
        return PaymentIdentification(
            outcome=IdentificationOutcome.MATCHED,
            recommended_customer=customer,
            account_receivable_summary=verified.account_receivable_summary,
            confidence=confidence,
            investigation_summary=self._summary(
                grounded, "El cliente y la cuenta por cobrar fueron verificados."
            ),
            unable_to_verify=self._unable_to_verify(output, state),
            evidence=grounded,
        )

    async def run(self, run_input: AgentRunInput) -> AgentRunResult:
        instructions, prompt_version, knowledge_version = load_prompt(self.config)
        state = RunState(max_tool_calls=self.config.max_tool_calls)
        settings_kwargs: dict[str, Any] = {
            "parallel_tool_calls": False,
            "max_tokens": self.config.azure_max_output_tokens,
            "timeout": float(self.config.agent_timeout_seconds),
        }
        if self.config.azure_openai_use_responses:
            settings_kwargs.update(
                reasoning={"effort": self.config.azure_reasoning_effort, "summary": "auto"},
                store=False,
            )
        agent: Agent[None] = Agent(
            name="Cerebro",
            instructions=instructions,
            model=self._model(),
            model_settings=ModelSettings(**settings_kwargs),
            output_type=ModelIdentification,
            tools=self._tools(state),
        )
        try:
            async with asyncio.timeout(self.config.agent_timeout_seconds):
                sdk_result = await Runner.run(
                    agent,
                    cast(Any, build_input_items(run_input)),
                    max_turns=self.config.max_agent_turns,
                    run_config=RunConfig(
                        tracing_disabled=True,
                        trace_include_sensitive_data=False,
                        workflow_name="Cerebro payment identification",
                    ),
                )
        except (TimeoutError, ModelTimeoutError):
            result = _unknown(
                "La investigación excedió el tiempo permitido.", CompletionReason.TIMEOUT
            )
        except MaxTurnsExceeded:
            result = _unknown(
                "La investigación agotó el límite de turnos.", CompletionReason.TURN_LIMIT
            )
        except ToolBudgetExceeded:
            result = _unknown(
                "La investigación agotó el límite de herramientas.",
                CompletionReason.TOOL_LIMIT,
            )
        except ModelRefusalError:
            result = _unknown(
                "El modelo no pudo responder esta solicitud.", CompletionReason.REFUSAL
            )
        except ModelBehaviorError:
            result = _unknown(
                "El modelo no produjo una respuesta estructurada válida.",
                CompletionReason.INVALID_OUTPUT,
            )
        except Exception as exc:
            raise AgentRunFailure(
                f"agent provider/runtime failure: {type(exc).__name__}",
                tool_calls=tuple(state.calls),
                prompt_version=prompt_version,
                knowledge_version=knowledge_version,
            ) from exc
        else:
            try:
                output = sdk_result.final_output_as(
                    ModelIdentification, raise_if_incorrect_type=True
                )
            except (TypeError, ValueError):
                result = _unknown(
                    "El modelo no produjo una respuesta estructurada válida.",
                    CompletionReason.INVALID_OUTPUT,
                )
            else:
                usage = sdk_result.context_wrapper.usage
                result = AgentRunResult(
                    identification=self._map_output(output, state),
                    steps=tuple(AgentStep(type="model_response") for _ in sdk_result.raw_responses),
                    usage=AgentUsage(
                        model=self.config.azure_deployment_main,
                        input_tokens=usage.input_tokens,
                        output_tokens=usage.output_tokens,
                        turns=usage.requests,
                        tool_calls=len(state.calls),
                    ),
                    completion_reason=CompletionReason.COMPLETED,
                )
        return AgentRunResult(
            identification=result.identification,
            steps=result.steps,
            usage=AgentUsage(
                model=result.usage.model or self.config.azure_deployment_main,
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                turns=result.usage.turns,
                tool_calls=len(state.calls),
            ),
            prompt_version=prompt_version,
            knowledge_version=knowledge_version,
            completion_reason=result.completion_reason,
            tool_calls=tuple(state.calls),
        )


def build_agent_runner(config: AppConfig | None = None) -> AgentRunner:
    config = config or get_config()
    if config.azure_agent_partially_configured:
        raise ValueError(
            "CEREBRO_AZURE_OPENAI_ENDPOINT and CEREBRO_AZURE_OPENAI_API_KEY must be set together"
        )
    if not config.azure_openai_endpoint and not config.azure_openai_api_key:
        return FakeAgentRunner()
    if not config.azure_deployment_main:
        raise ValueError("CEREBRO_AZURE_DEPLOYMENT_MAIN is required for the Azure agent")
    data: InvestigationData = EmptyInvestigationData()
    if config.replica_ready:
        knowledge = load_knowledge(config.knowledge_dir)
        data = ReplicaInvestigationData(
            ReplicaDatabase(config, knowledge),
            knowledge,
            config.knowledge_dir,
        )
    return OpenAIAgentsRunner(config, data=data)
