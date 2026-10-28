variable "project_id" {
  description = "Existing, billed GCP project. Terraform does not create a project."
  type        = string
  default     = "home-safety-ai"
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry, photos, and Firestore. Database location is immutable."
  type        = string
  default     = "us-central1"
}

variable "annotation_worker_url" {
  description = "Stable HTTPS API origin; set to https://api.<domain> before enabling durable highlights."
  type        = string
  default     = ""
  validation {
    condition     = var.annotation_worker_url == "" || can(regex("^https://[^/]+/?$", var.annotation_worker_url))
    error_message = "Use the stable HTTPS service origin, without a path."
  }
}

variable "domain_name" {
  description = "Registered apex domain, without a trailing dot. Empty disables the custom API frontend for bootstrap. Registration remains outside this state."
  type        = string
  default     = ""
  validation {
    condition     = var.domain_name == "" || can(regex("^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$", var.domain_name))
    error_message = "Use a lowercase domain name without scheme, path, or trailing dot."
  }
}

variable "demo_token_initialized" {
  description = "Enable Terraform runtime token IAM after the external token secret has been initialized."
  type        = bool
  default     = false
}
