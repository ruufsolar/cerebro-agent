"""Per-request specialist turns, shared across at most one route correction."""

from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from typing import Any

from agents.exceptions import MaxTurnsExceeded
from agents.items import ModelResponse, TResponseStreamEvent
from agents.models.interface import Model


@dataclass
class SpecialistTurns:
    limit: int
    used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class TurnLimitedModel(Model):
    def __init__(self, delegate: Model, turns: SpecialistTurns) -> None:
        self.delegate = delegate
        self.turns = turns

    def _prepare(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        if self.turns.used >= self.turns.limit:
            raise MaxTurnsExceeded("specialist turn limit")
        self.turns.used += 1
        if self.turns.used == self.turns.limit:
            kwargs["tools"] = []
            kwargs["handoffs"] = []
            kwargs["model_settings"] = replace(kwargs["model_settings"], tool_choice="none")
            kwargs["system_instructions"] = (kwargs.get("system_instructions") or "") + (
                "\nÚltimo turno: responde ahora con evidencia disponible o una pregunta útil. "
                "No solicites herramientas ni cambio de flujo; no inventes lo que falta."
            )
        return kwargs

    async def get_response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        response = await self.delegate.get_response(*args, **self._prepare(kwargs))
        self.turns.input_tokens += response.usage.input_tokens
        self.turns.output_tokens += response.usage.output_tokens
        return response

    def stream_response(self, *args: Any, **kwargs: Any) -> AsyncIterator[TResponseStreamEvent]:
        # Cerebro currently uses non-streaming Runner.run only.
        return self.delegate.stream_response(*args, **self._prepare(kwargs))
