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
  description = "HTTPS API origin; set to the current Cloud Run service URL before enabling durable highlights."
  type        = string
  default     = ""
  validation {
    condition     = var.annotation_worker_url == "" || can(regex("^https://[^/]+/?$", var.annotation_worker_url))
    error_message = "Use the stable HTTPS service origin, without a path."
  }
}

variable "demo_token_initialized" {
  description = "Enable Terraform runtime token IAM after the external token secret has been initialized."
  type        = bool
  default     = false
}
