output "resource_group_name" {
  description = "Resource group containing the Cerebro production runtime."
  value       = azurerm_resource_group.cerebro.name
}

output "vm_name" {
  description = "Private VM running the Cerebro Compose stack."
  value       = azurerm_linux_virtual_machine.runtime.name
}

output "key_vault_name" {
  description = "Key Vault into which the approved operator seeds runtime secrets."
  value       = azurerm_key_vault.cerebro.name
}

output "outbound_public_ip" {
  description = "Stable outbound address to allowlist on the read replica firewall."
  value       = azurerm_public_ip.nat.ip_address
}

# --- public HTTPS ingress ------------------------------------------------------------
# All null while ingress_hostname is empty, which is also how a reviewer confirms from
# `terraform output` alone that this deployment has no public listener.

output "ingress_public_ip" {
  description = "Inbound address for the bank-movements endpoint. Point the DNS record here."
  value       = one(azurerm_public_ip.ingress[*].ip_address)
}

output "ingress_hostname" {
  description = "Hostname the certificate is issued for and the monolith calls."
  value       = var.ingress_hostname != "" ? var.ingress_hostname : null
}

output "ingress_azure_fqdn" {
  description = "Azure-owned name for the same address. Diagnostics only; not the integration hostname."
  value       = one(azurerm_public_ip.ingress[*].fqdn)
}

output "ingress_url" {
  description = "The endpoint the monolith posts bank-payment events to."
  value       = var.ingress_hostname != "" ? "https://${var.ingress_hostname}/integrations/bank-movements" : null
}

output "ingress_dns_record" {
  description = "Whether Terraform manages the A record, or the record the zone owner must create."
  value = var.ingress_hostname == "" ? null : (
    local.ingress_dns_managed
    ? "managed by Terraform in Azure DNS zone ${var.dns_zone_name}"
    : "create A ${var.ingress_hostname} -> ${one(azurerm_public_ip.ingress[*].ip_address)} in whichever zone hosts ruuf.cl"
  )
}

output "private_ip" {
  description = "Private VM address. Cerebro has no public listener."
  value       = azurerm_network_interface.runtime.private_ip_address
}

output "registry_login_server" {
  description = "Container registry the VM pulls from with its managed identity."
  value       = azurerm_container_registry.cerebro.login_server
}

output "github_actions_variables" {
  description = "Non-secret repository variables to set on the GitHub repo so CI can push images and the scheduled workflow can deploy them."
  value = {
    AZURE_CI_CLIENT_ID          = azurerm_user_assigned_identity.ci.client_id
    AZURE_DEPLOY_CLIENT_ID      = azurerm_user_assigned_identity.deploy.client_id
    AZURE_TENANT_ID             = data.azurerm_client_config.current.tenant_id
    AZURE_SUBSCRIPTION_ID       = var.subscription_id
    AZURE_REGISTRY_NAME         = azurerm_container_registry.cerebro.name
    AZURE_REGISTRY_LOGIN_SERVER = azurerm_container_registry.cerebro.login_server
    AZURE_RESOURCE_GROUP        = azurerm_resource_group.cerebro.name
    AZURE_VM_NAME               = azurerm_linux_virtual_machine.runtime.name
    AZURE_KEY_VAULT_NAME        = azurerm_key_vault.cerebro.name
  }
}

output "next_steps" {
  description = "Secret seeding and activation commands; run them from this directory."
  value = merge(
    {
      seed     = "./scripts/seed-secrets.sh --vault-name ${azurerm_key_vault.cerebro.name} --env-file ../../.env"
      activate = "./scripts/activate.sh"
    },
    var.ingress_hostname == "" ? {} : {
      # The certificate is requested on Caddy's first start, so the name has to resolve
      # before activation or the ingress comes up without one and retries on a backoff.
      dns = "confirm ${var.ingress_hostname} resolves to ${one(azurerm_public_ip.ingress[*].ip_address)} before activating"
    },
  )
}
