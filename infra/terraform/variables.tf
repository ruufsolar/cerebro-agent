variable "subscription_id" {
  description = "Azure subscription that will own the Cerebro production resources."
  type        = string
}

variable "location" {
  description = "Azure region approved for the production workload."
  type        = string
  default     = "eastus2"
}

variable "resource_group_name" {
  description = "Dedicated resource group for Cerebro production."
  type        = string
  default     = "rg-cerebro-prod"
}

variable "name_prefix" {
  description = "Short lowercase prefix used in globally scoped Azure names."
  type        = string
  default     = "cerebro-prod"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,10}[a-z0-9]$", var.name_prefix))
    error_message = "name_prefix must be 3-12 lowercase letters, digits, or interior hyphens."
  }
}

variable "vm_size" {
  description = "VM size for the controlled pilot. Validate the attached-disk path before changing VM families."
  type        = string
  default     = "Standard_B2ms"
}

variable "admin_username" {
  description = "Emergency VM administrator account. There is no public SSH listener."
  type        = string
  default     = "cerebroadmin"
}

variable "admin_ssh_public_key" {
  description = "SSH public key retained for an approved Bastion/emergency-access path."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^(ssh-(rsa|ed25519)|ecdsa-sha2-nistp(256|384|521)) ", trimspace(var.admin_ssh_public_key)))
    error_message = "admin_ssh_public_key must be a supported OpenSSH public key."
  }
}

variable "secret_operator_object_id" {
  description = "Microsoft Entra object ID allowed to seed and rotate Cerebro Key Vault secrets."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-fA-F-]{36}$", var.secret_operator_object_id))
    error_message = "secret_operator_object_id must be a Microsoft Entra object UUID."
  }
}

variable "data_disk_size_gb" {
  description = "Persistent disk for Docker state, Cerebro PostgreSQL, and local backups."
  type        = number
  default     = 64

  validation {
    condition     = var.data_disk_size_gb >= 32
    error_message = "data_disk_size_gb must be at least 32 GiB."
  }
}

variable "tags" {
  description = "Additional Azure resource tags."
  type        = map(string)
  default = {
    environment = "production"
    managed-by  = "terraform"
    service     = "cerebro-agent"
  }
}
