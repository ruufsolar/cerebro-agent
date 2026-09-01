"""OpenAI Agents SDK runner backed by an Azure OpenAI v1 endpoint."""

import asyncio
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
    PaymentIdentification,
    ToolAuditRecord,
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
from cerebro.replica.database import ReplicaDatabase
from cerebro.replica.investigation import ReplicaInvestigationData
from cerebro.replica.scope import load_knowledge

os.environ.setdefault("OPENAI_AGENTS_DONT_LOG_MODEL_DATA", "1")
os.environ.setdefault("OPENAI_AGENTS_DONT_LOG_TOOL_DATA", "1")
set_tracing_disabled(True)

logger = logging.getLogger(__name__)


class ModelCandidate(BaseModel):
    customer_name: str
    order_id: str
    account_receivable_id: str | None = None
    reason: str


class ModelIdentification(BaseModel):
    recommended_customer: ModelCandidate | None = None
    account_receivable_summary: str | None = None
    confidence: Confidence
    investigation_summary: str
    unable_to_verify: list[str] = Field(default_factory=list)
    alternatives: list[ModelCandidate] = Field(default_factory=list, max_length=3)


class ToolBudgetExceeded(RuntimeError):
    pass


@dataclass
class RunState:
    max_tool_calls: int
    calls: list[ToolAuditRecord] = field(default_factory=list)
    candidate_order_ids: set[str] = field(default_factory=set)
    verified_candidates: dict[tuple[str, str | None], Any] = field(default_factory=dict)

    async def invoke(self, name: str, request: ToolRequest, call: Any) -> str:
        sequence = len(self.calls) + 1
        if sequence > self.max_tool_calls:
            raise ToolBudgetExceeded(f"tool call budget exhausted at {self.max_tool_calls}")
        started = monotonic()
        safe_input = safe_input_summary(request)
        try:
            observation: ToolObservation = await call(request)
            for candidate in observation.candidates:
                order_id = str(candidate.order_id)
                self.candidate_order_ids.add(order_id)
                if candidate.verified:
                    receivable_id = (
                        str(candidate.account_receivable_id)
                        if candidate.account_receivable_id
                        else None
                    )
                    self.verified_candidates[(order_id, receivable_id)] = candidate
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
            logger.warning("investigation tool %s unavailable: %s", name, type(exc).__name__)
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
            descriptions = ", ".join(
                f"{attachment.mimetype} ({attachment.size} bytes)"
                for attachment in message.attachments
            )
            text = f"{text}\n[Adjuntos no descargados en Slice 3: {descriptions}]".strip()
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

    def _map_output(self, output: ModelIdentification, state: RunState) -> PaymentIdentification:
        candidates = [item for item in [output.recommended_customer, *output.alternatives] if item]
        resolved: dict[int, Any] = {}
        for index, model_candidate in enumerate(candidates):
            key = (model_candidate.order_id, model_candidate.account_receivable_id)
            verified = state.verified_candidates.get(key)
            if verified is None and model_candidate.account_receivable_id is None:
                matches = [
                    candidate
                    for (order_id, _), candidate in state.verified_candidates.items()
                    if order_id == model_candidate.order_id
                ]
                if len(matches) == 1:
                    verified = matches[0]
            if verified is None:
                break
            resolved[index] = verified
        if len(resolved) != len(candidates):
            return PaymentIdentification(
                confidence=Confidence.UNKNOWN,
                investigation_summary=(
                    "El modelo propuso un cliente que no fue verificado por las herramientas; "
                    "la propuesta fue descartada de forma segura."
                ),
                unable_to_verify=["cliente respaldado por fuentes", "cuenta por cobrar"],
            )

        def candidate(value: ModelCandidate, verified: Any) -> CustomerCandidate:
            order_id = quote(value.order_id, safe="")
            url = f"{self.config.crm_finops_base_url.rstrip('/')}/{order_id}"
            return CustomerCandidate(
                customer_name=verified.customer_name,
                order_id=value.order_id,
                crm_url=url,
                reason=value.reason,
            )

        return PaymentIdentification(
            recommended_customer=(
                candidate(output.recommended_customer, resolved[0])
                if output.recommended_customer
                else None
            ),
            account_receivable_summary=(
                resolved[0].account_receivable_summary if output.recommended_customer else None
            ),
            confidence=output.confidence,
            investigation_summary=output.investigation_summary,
            unable_to_verify=output.unable_to_verify,
            alternatives=[
                candidate(item, resolved[index + (1 if output.recommended_customer else 0)])
                for index, item in enumerate(output.alternatives)
            ],
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
