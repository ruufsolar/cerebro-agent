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

output "private_ip" {
  description = "Private VM address. Cerebro has no public listener."
  value       = azurerm_network_interface.runtime.private_ip_address
}

output "next_steps" {
  description = "Secret seeding and activation commands; run them from this directory."
  value = {
    seed     = "./scripts/seed-secrets.sh --vault-name ${azurerm_key_vault.cerebro.name} --env-file ../../.env"
    activate = "./scripts/activate.sh"
  }
}
