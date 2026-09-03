locals {
  key_vault_name = "${var.name_prefix}-kv-${random_string.suffix.result}"
  vm_name        = "${var.name_prefix}-vm"

  cloud_init = templatefile("${path.module}/templates/cloud-init.yaml.tftpl", {
    azure_env_b64 = base64encode(join("", [
      "CEREBRO_KEY_VAULT_NAME=${local.key_vault_name}\n",
      "CEREBRO_AZURE_TENANT_ID=${data.azurerm_client_config.current.tenant_id}\n",
      "CEREBRO_REGISTRY_LOGIN_SERVER=${azurerm_container_registry.cerebro.login_server}\n",
      "CEREBRO_IMAGE_REPOSITORY=${azurerm_container_registry.cerebro.login_server}/cerebro-agent\n",
    ]))
    backup_script_b64 = base64encode(file("${path.module}/../../deploy/cerebro-agent-backup.sh"))
    backup_service_b64 = base64encode(
      file("${path.module}/../../deploy/systemd/cerebro-agent-backup.service")
    )
    backup_timer_b64 = base64encode(
      file("${path.module}/../../deploy/systemd/cerebro-agent-backup.timer")
    )
    bootstrap_script_b64  = base64encode(file("${path.module}/../../deploy/bootstrap.sh"))
    bootstrap_service_b64 = base64encode(file("${path.module}/templates/cerebro-agent-bootstrap.service"))
    registry_login_b64    = base64encode(file("${path.module}/templates/cerebro-registry-login.sh"))
    compose_b64           = base64encode(file("${path.module}/../../deploy/compose.yml"))
    compose_env_b64       = base64encode(file("${path.module}/../../deploy/compose.env.example"))
    docker_daemon_b64 = base64encode(jsonencode({
      "data-root"  = "/srv/cerebro/docker"
      "log-driver" = "json-file"
      "log-opts" = {
        "max-file" = "3"
        "max-size" = "20m"
      }
    }))
    runtime_env_b64    = base64encode(file("${path.module}/../../deploy/env.example"))
    update_script_b64  = base64encode(file("${path.module}/../../deploy/cerebro-agent-update.sh"))
    update_service_b64 = base64encode(file("${path.module}/../../deploy/systemd/cerebro-agent-update.service"))
    update_timer_b64   = base64encode(file("${path.module}/../../deploy/systemd/cerebro-agent-update.timer"))
    vm_bootstrap_b64   = base64encode(file("${path.module}/templates/vm-bootstrap.sh"))
  })
}

resource "random_string" "suffix" {
  length  = 5
  lower   = true
  numeric = true
  special = false
  upper   = false
}

resource "azurerm_resource_group" "cerebro" {
  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

resource "azurerm_virtual_network" "cerebro" {
  name                = "${var.name_prefix}-vnet"
  address_space       = ["10.42.0.0/16"]
  location            = azurerm_resource_group.cerebro.location
  resource_group_name = azurerm_resource_group.cerebro.name
  tags                = var.tags
}

resource "azurerm_subnet" "runtime" {
  name                 = "runtime"
  resource_group_name  = azurerm_resource_group.cerebro.name
  virtual_network_name = azurerm_virtual_network.cerebro.name
  address_prefixes     = ["10.42.1.0/24"]
}

resource "azurerm_public_ip" "nat" {
  name                = "${var.name_prefix}-egress-ip"
  location            = azurerm_resource_group.cerebro.location
  resource_group_name = azurerm_resource_group.cerebro.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = var.tags
}

resource "azurerm_nat_gateway" "cerebro" {
  name                    = "${var.name_prefix}-nat"
  location                = azurerm_resource_group.cerebro.location
  resource_group_name     = azurerm_resource_group.cerebro.name
  sku_name                = "Standard"
  idle_timeout_in_minutes = 10
  tags                    = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "cerebro" {
  nat_gateway_id       = azurerm_nat_gateway.cerebro.id
  public_ip_address_id = azurerm_public_ip.nat.id
}

resource "azurerm_subnet_nat_gateway_association" "runtime" {
  subnet_id      = azurerm_subnet.runtime.id
  nat_gateway_id = azurerm_nat_gateway.cerebro.id
}

resource "azurerm_network_security_group" "runtime" {
  name                = "${var.name_prefix}-runtime-nsg"
  location            = azurerm_resource_group.cerebro.location
  resource_group_name = azurerm_resource_group.cerebro.name
  tags                = var.tags
}

resource "azurerm_subnet_network_security_group_association" "runtime" {
  subnet_id                 = azurerm_subnet.runtime.id
  network_security_group_id = azurerm_network_security_group.runtime.id
}

resource "azurerm_network_interface" "runtime" {
  name                = "${var.name_prefix}-nic"
  location            = azurerm_resource_group.cerebro.location
  resource_group_name = azurerm_resource_group.cerebro.name
  tags                = var.tags

  ip_configuration {
    name                          = "private"
    subnet_id                     = azurerm_subnet.runtime.id
    private_ip_address_allocation = "Dynamic"
  }

  depends_on = [
    azurerm_subnet_nat_gateway_association.runtime,
    azurerm_subnet_network_security_group_association.runtime,
  ]
}

resource "azurerm_key_vault" "cerebro" {
  name                          = local.key_vault_name
  location                      = azurerm_resource_group.cerebro.location
  resource_group_name           = azurerm_resource_group.cerebro.name
  tenant_id                     = data.azurerm_client_config.current.tenant_id
  sku_name                      = "standard"
  rbac_authorization_enabled    = true
  purge_protection_enabled      = true
  soft_delete_retention_days    = 7
  public_network_access_enabled = true
  tags                          = var.tags
}

resource "azurerm_linux_virtual_machine" "runtime" {
  name                            = local.vm_name
  computer_name                   = "cerebro-prod"
  location                        = azurerm_resource_group.cerebro.location
  resource_group_name             = azurerm_resource_group.cerebro.name
  size                            = var.vm_size
  admin_username                  = var.admin_username
  disable_password_authentication = true
  network_interface_ids           = [azurerm_network_interface.runtime.id]
  custom_data                     = base64encode(local.cloud_init)
  secure_boot_enabled             = true
  vtpm_enabled                    = true
  tags                            = var.tags

  admin_ssh_key {
    username   = var.admin_username
    public_key = trimspace(var.admin_ssh_public_key)
  }

  identity {
    type = "SystemAssigned"
  }

  os_disk {
    name                 = "${var.name_prefix}-os"
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 32
  }

  source_image_reference {
    publisher = "Canonical"
    offer     = "ubuntu-24_04-lts"
    sku       = "server"
    version   = "latest"
  }

  boot_diagnostics {}
}

resource "azurerm_managed_disk" "data" {
  name                 = "${var.name_prefix}-data"
  location             = azurerm_resource_group.cerebro.location
  resource_group_name  = azurerm_resource_group.cerebro.name
  storage_account_type = "StandardSSD_LRS"
  create_option        = "Empty"
  disk_size_gb         = var.data_disk_size_gb
  tags                 = var.tags

  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_virtual_machine_data_disk_attachment" "data" {
  managed_disk_id    = azurerm_managed_disk.data.id
  virtual_machine_id = azurerm_linux_virtual_machine.runtime.id
  lun                = 0
  caching            = "None"
}

resource "azurerm_role_assignment" "runtime_secrets" {
  scope                = azurerm_key_vault.cerebro.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_linux_virtual_machine.runtime.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

resource "azurerm_role_assignment" "secret_operator" {
  scope                = azurerm_key_vault.cerebro.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = var.secret_operator_object_id
}

# Container registry. The VM pulls with its own system-assigned identity and GitHub
# Actions pushes through a federated credential, so no registry password exists anywhere:
# not in Key Vault, not in GitHub secrets, and not in /root/.docker on the VM.
resource "azurerm_container_registry" "cerebro" {
  name                = "${replace(var.name_prefix, "-", "")}acr${random_string.suffix.result}"
  location            = azurerm_resource_group.cerebro.location
  resource_group_name = azurerm_resource_group.cerebro.name
  sku                 = "Basic"
  admin_enabled       = false
  tags                = var.tags
}

resource "azurerm_role_assignment" "runtime_acr_pull" {
  scope                = azurerm_container_registry.cerebro.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_linux_virtual_machine.runtime.identity[0].principal_id
  principal_type       = "ServicePrincipal"
}

# A user-assigned identity rather than an Entra app registration: federated credentials
# work the same way for CI, but this stays an ARM resource the subscription owner can
# create without directory-level application permissions.
resource "azurerm_user_assigned_identity" "ci" {
  name                = "${var.name_prefix}-ci"
  location            = azurerm_resource_group.cerebro.location
  resource_group_name = azurerm_resource_group.cerebro.name
  tags                = var.tags
}

# GitHub now presents an ID-qualified subject (owner@id/repo@id) by default so that a
# renamed or re-created repository cannot inherit trust. Trust both that form and the
# plain owner/repo form, so the credential keeps working whichever the repository sends.
locals {
  github_owner = split("/", var.github_repository)[0]
  github_repo  = split("/", var.github_repository)[1]
  github_subject_prefixes = {
    plain = "repo:${var.github_repository}"
    ids   = "repo:${local.github_owner}@${var.github_owner_id}/${local.github_repo}@${var.github_repository_id}"
  }
  # Publish identity: pushes from the main branch.
  github_oidc_subjects = {
    "github-main"     = "${local.github_subject_prefixes.plain}:ref:refs/heads/main"
    "github-main-ids" = "${local.github_subject_prefixes.ids}:ref:refs/heads/main"
  }
  # Deploy identity: jobs bound to the protected GitHub environment, whatever branch they run on.
  github_deploy_subjects = {
    "github-${var.github_deploy_environment}"     = "${local.github_subject_prefixes.plain}:environment:${var.github_deploy_environment}"
    "github-${var.github_deploy_environment}-ids" = "${local.github_subject_prefixes.ids}:environment:${var.github_deploy_environment}"
  }
}

moved {
  from = azurerm_federated_identity_credential.ci_main
  to   = azurerm_federated_identity_credential.ci_main["github-main"]
}

resource "azurerm_federated_identity_credential" "ci_main" {
  for_each            = local.github_oidc_subjects
  name                = each.key
  resource_group_name = azurerm_resource_group.cerebro.name
  parent_id           = azurerm_user_assigned_identity.ci.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = each.value
}

resource "azurerm_role_assignment" "ci_acr_push" {
  scope                = azurerm_container_registry.cerebro.id
  role_definition_name = "AcrPush"
  principal_id         = azurerm_user_assigned_identity.ci.principal_id
  principal_type       = "ServicePrincipal"
}

# Deploy identity for the scheduled production workflow. Kept separate from the publish
# identity so the credential that can push images cannot change what production runs, and
# the credential that changes production cannot push images. It is trusted only from the
# GitHub environment named in var.github_deploy_environment, so that environment's
# protection rules gate every production change.
resource "azurerm_user_assigned_identity" "deploy" {
  name                = "${var.name_prefix}-deploy"
  location            = azurerm_resource_group.cerebro.location
  resource_group_name = azurerm_resource_group.cerebro.name
  tags                = var.tags
}

resource "azurerm_federated_identity_credential" "deploy" {
  for_each            = local.github_deploy_subjects
  name                = each.key
  resource_group_name = azurerm_resource_group.cerebro.name
  parent_id           = azurerm_user_assigned_identity.deploy.id
  audience            = ["api://AzureADTokenExchange"]
  issuer              = "https://token.actions.githubusercontent.com"
  subject             = each.value
}

# The workflow changes only the image-tag secret, but Key Vault RBAC at secret scope needs
# the secret to exist first, which the seeder creates after apply. Vault-wide Secrets Officer
# keeps a fresh deployment orderable; Run Command below already implies root on the VM, where
# the same secrets are decrypted, so a narrower vault scope would not reduce real exposure.
resource "azurerm_role_assignment" "deploy_secrets_officer" {
  scope                = azurerm_key_vault.cerebro.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
}

# Confirms the resolved tag exists in the registry before pointing production at it.
resource "azurerm_role_assignment" "deploy_acr_pull" {
  scope                = azurerm_container_registry.cerebro.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.deploy.principal_id
  principal_type       = "ServicePrincipal"
}

# Just enough to invoke Run Command on this one VM; Virtual Machine Contributor would also
# allow resizing, deleting, or re-imaging it.
resource "azurerm_role_definition" "vm_run_command" {
  name        = "${var.name_prefix}-vm-run-command"
  scope       = azurerm_linux_virtual_machine.runtime.id
  description = "Invoke Run Command on the Cerebro production VM."

  permissions {
    actions = [
      "Microsoft.Compute/virtualMachines/read",
      "Microsoft.Compute/virtualMachines/runCommand/action",
    ]
  }

  assignable_scopes = [azurerm_linux_virtual_machine.runtime.id]
}

resource "azurerm_role_assignment" "deploy_vm_run_command" {
  scope              = azurerm_linux_virtual_machine.runtime.id
  role_definition_id = azurerm_role_definition.vm_run_command.role_definition_resource_id
  principal_id       = azurerm_user_assigned_identity.deploy.principal_id
  principal_type     = "ServicePrincipal"
}
