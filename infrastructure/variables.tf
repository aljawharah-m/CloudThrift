variable "subscription_id" {
  description = "Azure subscription ID used to deploy CloudThrift."
  type        = string
  sensitive   = true
}

variable "location" {
  description = "Azure region used for CloudThrift resources."
  type        = string
  default     = "UAE North"
}

variable "environment" {
  description = "Deployment environment."
  type        = string
  default     = "development"

  validation {
    condition = contains(
      ["development", "staging", "production"],
      var.environment
    )

    error_message = "Environment must be development, staging, or production."
  }
}

variable "admin_username" {
  description = "Administrative username for VM Scale Set instances."
  type        = string
  default     = "cloudadmin"
}

variable "admin_ssh_public_key" {
  description = "SSH public key used by VM Scale Set instances."
  type        = string
  sensitive   = true
}

variable "vm_sku" {
  description = "Azure VM SKU used by the VM Scale Set."
  type        = string
  default     = "Standard_B1s"
}

variable "initial_instance_count" {
  description = "Initial number of VM Scale Set instances."
  type        = number
  default     = 1

  validation {
    condition     = var.initial_instance_count >= 1 && var.initial_instance_count <= 5
    error_message = "Initial instance count must be between 1 and 5."
  }
}

variable "minimum_instance_count" {
  description = "Minimum instance count allowed by CloudThrift."
  type        = number
  default     = 1
}

variable "maximum_instance_count" {
  description = "Maximum instance count allowed by CloudThrift."
  type        = number
  default     = 3
}