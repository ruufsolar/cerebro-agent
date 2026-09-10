import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "response, exit_code, accepted",
    [
        ("0", 0, True),
        ("2", 0, True),
        ("", 0, False),
        ("invalid", 0, False),
        ("", 1, False),
    ],
)
def test_deploy_queue_check_never_treats_database_failure_as_idle(
    response: str, exit_code: int, accepted: bool
) -> None:
    source = (REPO_ROOT / "deploy/cerebro-agent-update.sh").read_text()
    definitions = []
    for name in ("running_jobs", "checked_running_jobs"):
        match = re.search(rf"^{name}\(\) \{{\n.*?^\}}", source, re.M | re.S)
        assert match is not None
        definitions.append(match.group())
    script = "\n".join(
        [
            "set -euo pipefail",
            *definitions,
            'compose() { printf \'%s\' "$TEST_OUTPUT"; return "$TEST_EXIT"; }',
            "COMPOSE=(compose)",
            "checked_running_jobs",
        ]
    )
    result = subprocess.run(
        ["bash", "-c", script],
        env={"TEST_OUTPUT": response, "TEST_EXIT": str(exit_code)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is accepted


def test_consolidated_documentation_links_resolve() -> None:
    paths = [REPO_ROOT / "README.md", REPO_ROOT / "infra/terraform/README.md"]
    paths.extend((REPO_ROOT / "docs").rglob("*.md"))
    for path in paths:
        for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
            if "://" in target or target.startswith("#"):
                continue
            assert (path.parent / target.split("#")[0]).exists(), f"{path.name}: {target}"


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

    assert scope["purpose"] == (
        "internal FinOps payment identification and scoped read-only questions"
    )
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
    # Every source of new work stops before the drain, and comes back on every abort path.
    assert "INGRESS=(slack)" in update_script
    assert "INGRESS+=(caddy)" in update_script
    assert 'stop --timeout "$DRAIN_TIMEOUT_S" "${INGRESS[@]}"' in update_script
    assert 'stop --timeout "$DRAIN_TIMEOUT_S" control-worker agent-worker' in update_script
    assert 'start "${INGRESS[@]}"' in update_script
    assert 'start control-worker agent-worker "${INGRESS[@]}"' in update_script
    assert "http://127.0.0.1:8010/ready" in update_script
    assert "last-good" in update_script


def _terraform_blocks(source: str, resource_type: str) -> list[str]:
    """Every top-level block of one resource type, by brace depth."""
    blocks: list[str] = []
    for start in range(len(source)):
        if not source.startswith(f'resource "{resource_type}" ', start):
            continue
        if start and source[start - 1] != "\n":
            continue
        depth, cursor = 0, source.index("{", start)
        while True:
            if source[cursor] == "{":
                depth += 1
            elif source[cursor] == "}":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        blocks.append(source[start : cursor + 1])
    return blocks


def test_terraform_ingress_is_off_unless_a_hostname_is_configured() -> None:
    """The public path exists only for a deployment that asked for it.

    Every resource that can be reached from the Internet is gated on the same local, so a
    deployment with no ingress_hostname plans no address and no inbound rule at all.
    """
    main = (REPO_ROOT / "infra/terraform/main.tf").read_text()

    assert re.search(r'ingress_enabled\s+= var\.ingress_hostname != ""', main)

    gated = [
        block
        for block in _terraform_blocks(main, "azurerm_public_ip")
        if block.startswith('resource "azurerm_public_ip" "ingress"')
    ]
    gated += _terraform_blocks(main, "azurerm_network_security_rule")
    gated += _terraform_blocks(main, "azurerm_dns_a_record")
    # The address, the two allow rules, the three denies as one for_each, and the A record.
    assert len(gated) == 5
    for block in gated:
        assert "local.ingress_enabled" in block or "local.ingress_dns_managed" in block

    # The VM's address is the ingress one or none; there is no second way to acquire one.
    assert "public_ip_address_id = one(azurerm_public_ip.ingress[*].id)" in main


def test_terraform_opens_only_the_two_ingress_ports() -> None:
    """443 for the endpoint, 80 so the certificate can renew itself. Nothing else."""
    main = (REPO_ROOT / "infra/terraform/main.tf").read_text()

    allowed = [
        block
        for block in _terraform_blocks(main, "azurerm_network_security_rule")
        if 'access                      = "Allow"' in block
    ]
    ports = sorted(
        line.split("=", maxsplit=1)[1].strip().strip('"')
        for block in allowed
        for line in block.splitlines()
        if line.strip().startswith("destination_port_range ")
    )
    assert ports == ["443", "80"]
    assert all('direction                   = "Inbound"' in block for block in allowed)


def test_terraform_keeps_secrets_out_of_its_inputs() -> None:
    main = (REPO_ROOT / "infra/terraform/main.tf").read_text()
    variables = (REPO_ROOT / "infra/terraform/variables.tf").read_text()

    assert 'resource "azurerm_nat_gateway" "cerebro"' in main
    assert 'resource "azurerm_network_interface" "runtime"' in main
    assert 'role_definition_name = "Key Vault Secrets User"' in main
    assert 'role_definition_name = "Key Vault Secrets Officer"' in main
    assert "prevent_destroy = true" in main
    assert "SLACK" not in variables
    assert "OPENAI_API_KEY" not in variables
    assert "REPLICA_URL" not in variables
    # The Authentik values reach the VM through the seeder and Key Vault, like every other
    # runtime setting; putting them here would put them in the plan and in state.
    assert "BANK_INGESTION" not in variables.upper().replace("INGRESS_", "")


def test_the_proxy_publishes_one_method_on_one_path() -> None:
    """The reviewed routing, asserted where a careless edit would otherwise pass CI."""
    caddyfile = (REPO_ROOT / "deploy/Caddyfile").read_text()

    assert "method POST" in caddyfile
    assert "path /integrations/bank-movements" in caddyfile
    assert "reverse_proxy web:8000" in caddyfile
    # Everything the routing must never expose, and the catch-all that keeps it that way.
    assert "handle {\n\t\trespond 404\n\t}" in caddyfile
    for private in ("/health", "/ready", "/docs", "/openapi.json", ":8010", ":5432"):
        assert f"path {private}" not in caddyfile
    # No bearer credential, no request; and no credential in the access log either.
    assert "not header Authorization Bearer*" in caddyfile
    assert "request>headers>Authorization delete" in caddyfile


def test_the_ingress_service_only_exists_under_its_profile() -> None:
    compose = yaml.safe_load((REPO_ROOT / "deploy/compose.yml").read_text())
    caddy = compose["services"]["caddy"]

    assert caddy["profiles"] == ["ingress"]
    assert caddy["ports"] == ["80:80", "443:443"]
    # Nothing else may publish beyond loopback.
    published = [
        port
        for name, service in compose["services"].items()
        if name != "caddy"
        for port in service.get("ports", [])
    ]
    assert all(port.startswith("127.0.0.1:") for port in published), published
