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


def test_compose_isolates_control_and_agent_workers() -> None:
    compose = yaml.safe_load((REPO_ROOT / "deploy/compose.local.yml").read_text())
    services = compose["services"]

    assert services["control-worker"]["command"] == "python -m cerebro.worker --role control"
    assert services["agent-worker"]["command"] == "python -m cerebro.worker --role agent"
    assert services["control-worker"]["stop_grace_period"] == "240s"
    assert services["agent-worker"]["stop_grace_period"] == "240s"


def test_deployment_aborts_on_busy_jobs_and_gates_on_readiness() -> None:
    update_script = (REPO_ROOT / "deploy/cerebro-agent-update.sh").read_text()

    assert "DRAIN_TIMEOUT_S=240" in update_script
    assert 'flock -w "$LOCK_WAIT_S"' in update_script
    assert "aborting deploy" in update_script
    assert 'stop --timeout "$DRAIN_TIMEOUT_S" slack' in update_script
    assert 'stop --timeout "$DRAIN_TIMEOUT_S" control-worker agent-worker' in update_script
    assert "start slack" in update_script
    assert "http://127.0.0.1:8010/ready" in update_script
    assert "last-good" in update_script


def test_terraform_runtime_has_no_public_ingress_or_secret_inputs() -> None:
    main = (REPO_ROOT / "infra/terraform/main.tf").read_text()
    variables = (REPO_ROOT / "infra/terraform/variables.tf").read_text()

    assert 'resource "azurerm_nat_gateway" "cerebro"' in main
    assert 'resource "azurerm_network_interface" "runtime"' in main
    assert (
        "public_ip_address_id"
        not in main.split('resource "azurerm_network_interface" "runtime"', maxsplit=1)[1].split(
            'resource "azurerm_key_vault"', maxsplit=1
        )[0]
    )
    assert 'role_definition_name = "Key Vault Secrets User"' in main
    assert 'role_definition_name = "Key Vault Secrets Officer"' in main
    assert "prevent_destroy = true" in main
    assert "SLACK" not in variables
    assert "OPENAI_API_KEY" not in variables
    assert "REPLICA_URL" not in variables
