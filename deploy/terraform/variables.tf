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

variable "annotation_queue_name" {
  description = "Cloud Tasks queue ID. Choose a fresh name after deletion while Google blocks reuse of the previous name."
  type        = string
  default     = "home-safety-annotations"
  validation {
    condition     = can(regex("^[A-Za-z0-9_-]{1,100}$", var.annotation_queue_name))
    error_message = "Use 1 to 100 letters, digits, underscores or hyphens."
  }
}
