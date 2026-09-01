from cerebro.capabilities import CAPABILITIES, CapabilityState


def test_v0_shell_is_read_only_and_future_writes_remain_planned() -> None:
    v0, payment_write, hold_write = CAPABILITIES

    assert v0.key == "payment_identification_v0"
    assert v0.state is CapabilityState.SHELL
    assert v0.business_writes is False
    assert payment_write.business_writes is True
    assert payment_write.state is CapabilityState.PLANNED
    assert hold_write.business_writes is True
    assert hold_write.state is CapabilityState.PLANNED
