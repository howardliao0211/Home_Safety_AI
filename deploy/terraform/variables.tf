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
  description = "Stable Cloud Run service URL; set after the initial release to enable durable annotation recovery."
  type        = string
  default     = ""
  validation {
    condition     = var.annotation_worker_url == "" || can(regex("^https://[^/]+/?$", var.annotation_worker_url))
    error_message = "Use the stable HTTPS service origin, without a path."
  }
}
