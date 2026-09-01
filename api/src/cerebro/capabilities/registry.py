from dataclasses import dataclass
from enum import StrEnum


class CapabilityState(StrEnum):
    FOUNDATION = "foundation"
    SHELL = "shell"
    PLANNED = "planned"
    LIVE = "live"
    PAUSED = "paused"


@dataclass(frozen=True)
class Capability:
    key: str
    state: CapabilityState
    trigger: str
    external_effects: tuple[str, ...]
    business_writes: bool


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="payment_identification_v0",
        state=CapabilityState.SHELL,
        trigger="Slack app mention with text and/or image",
        external_effects=("Slack thread reply",),
        business_writes=False,
    ),
    Capability(
        key="register_account_receivable_payment",
        state=CapabilityState.PLANNED,
        trigger="Explicit FinOps confirmation",
        external_effects=("Approval-gated monolith API call",),
        business_writes=True,
    ),
    Capability(
        key="hold_recommendation_and_application",
        state=CapabilityState.PLANNED,
        trigger="Due receivable without identified payment",
        external_effects=("Slack proposal", "Approval-gated monolith API call"),
        business_writes=True,
    ),
)
