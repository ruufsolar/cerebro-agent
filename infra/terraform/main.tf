locals {
  key_vault_name = "${var.name_prefix}-kv-${random_string.suffix.result}"
  vm_name        = "${var.name_prefix}-vm"

  cloud_init = templatefile("${path.module}/templates/cloud-init.yaml.tftpl", {
    azure_env_b64     = base64encode("CEREBRO_KEY_VAULT_NAME=${local.key_vault_name}\n")
    backup_script_b64 = base64encode(file("${path.module}/../../deploy/cerebro-agent-backup.sh"))
    backup_service_b64 = base64encode(
      file("${path.module}/../../deploy/systemd/cerebro-agent-backup.service")
    )
    backup_timer_b64 = base64encode(
      file("${path.module}/../../deploy/systemd/cerebro-agent-backup.timer")
    )
    bootstrap_script_b64  = base64encode(file("${path.module}/../../deploy/bootstrap.sh"))
    bootstrap_service_b64 = base64encode(file("${path.module}/templates/cerebro-agent-bootstrap.service"))
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
