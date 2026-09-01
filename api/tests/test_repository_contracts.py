from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_contains_v0_thread_and_feedback_events() -> None:
    manifest = yaml.safe_load((REPO_ROOT / "manifest.yaml").read_text())
    events = set(manifest["settings"]["event_subscriptions"]["bot_events"])

    assert {
        "app_mention",
        "message.channels",
        "message.groups",
        "reaction_added",
        "reaction_removed",
    } <= events
    assert manifest["settings"]["socket_mode_enabled"] is True


def test_knowledge_scope_is_explicitly_read_only() -> None:
    scope = yaml.safe_load((REPO_ROOT / "knowledge/data-scope.yaml").read_text())

    assert scope["purpose"] == "payment identification only"
    assert scope["query_limits"]["statements"] == ["SELECT", "WITH"]
    assert "dml" in scope["query_limits"]["forbid"]
    assert "ddl" in scope["query_limits"]["forbid"]
