variable "project_id" {
  description = "Existing, billed GCP project. Terraform does not create a project."
  type        = string
  default     = "home-safety-ai"
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry, photos, Firestore, Cloud Tasks and Scheduler. Database location is immutable: change regions with `deploy rebuild --region`."
  type        = string
  default     = "australia-southeast1"
}

variable "adopt_existing_identity_config" {
  description = "Guided deployments use an existing verified test account and import its persistent Identity Platform config."
  type        = bool
  default     = false
}

variable "firestore_database_id" {
  description = "Firestore database ID. Guided start chooses a fresh ID after teardown to avoid GCP's name-reuse delay."
  type        = string
  default     = "(default)"
  validation {
    condition     = var.firestore_database_id == "(default)" || can(regex("^[a-z][a-z0-9-]{2,61}[a-z0-9]$", var.firestore_database_id))
    error_message = "Use (default) or a 4-63 character lowercase database ID starting with a letter and ending with a letter or digit."
  }
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
