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

variable "github_repository" {
  description = "owner/name of the repository whose main branch may push images to the registry."
  type        = string
  default     = "ruufsolar/cerebro-agent"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$", var.github_repository))
    error_message = "github_repository must look like owner/name."
  }
}

# GitHub's OIDC subject claim embeds these numeric IDs. Find them with:
#   gh api repos/OWNER/NAME --jq '{owner_id: .owner.id, repository_id: .id}'
variable "github_owner_id" {
  description = "Numeric GitHub ID of the repository owner (organization or user)."
  type        = number
}

variable "github_repository_id" {
  description = "Numeric GitHub ID of the repository."
  type        = number
}

variable "github_deploy_environment" {
  description = "GitHub environment whose jobs may change the production image tag and activate the VM."
  type        = string
  default     = "production"

  validation {
    condition     = can(regex("^[A-Za-z0-9._-]+$", var.github_deploy_environment))
    error_message = "github_deploy_environment must be a plain environment name."
  }
}

# --- public HTTPS ingress ------------------------------------------------------
# Empty ingress_hostname keeps the private-only shape ADR-009 provisioned: no VM public
# IP, no inbound NSG rule, no Caddy container. Setting it is what turns ingress on, in
# Terraform and (through the vault's public-hostname secret) on the VM.

variable "ingress_hostname" {
  description = "Public hostname for the bank-movements endpoint, e.g. cerebro.ruuf.cl. Empty leaves Cerebro private."
  type        = string
  default     = ""

  validation {
    condition     = var.ingress_hostname == "" || can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.ingress_hostname))
    error_message = "ingress_hostname must be a lowercase fully qualified domain name, or empty."
  }
}

# Application-level Authentik validation is the real gate, but a source allowlist means a
# scanner never reaches it. Narrow this to the monolith's egress addresses as soon as the
# platform owner confirms them; "Internet" is the working default, not the target state.
variable "ingress_allowed_source_ranges" {
  description = "Sources allowed to reach TCP 443. Azure service tags or CIDRs. Narrow to the monolith's egress addresses."
  type        = list(string)
  default     = ["Internet"]

  validation {
    condition     = length(var.ingress_allowed_source_ranges) > 0
    error_message = "ingress_allowed_source_ranges must list at least one source; use [\"Internet\"] deliberately."
  }
}

# Optional: manage the A record here when ruuf.cl (or a delegated zone) lives in Azure DNS.
# Left empty, Terraform only reports the address and the record is created wherever the zone
# is hosted. Certificate issuance needs the record to exist before the VM is activated.
variable "dns_zone_name" {
  description = "Azure DNS zone holding ingress_hostname. Empty means the record is managed outside Terraform."
  type        = string
  default     = ""
}

variable "dns_zone_resource_group_name" {
  description = "Resource group of dns_zone_name. Required when dns_zone_name is set."
  type        = string
  default     = ""
}

variable "dns_record_ttl" {
  description = "TTL for the managed A record. Keep it short while the address may still move."
  type        = number
  default     = 300

  validation {
    condition     = var.dns_record_ttl >= 60 && var.dns_record_ttl <= 86400
    error_message = "dns_record_ttl must be between 60 and 86400 seconds."
  }
}
