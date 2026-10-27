variable "project_id" {
  description = "Existing, billed GCP project. Terraform does not create a project."
  type        = string
  default     = "home-safety-ai"
}

variable "region" {
  description = "Region for compute, photos, and Firestore. Database location is immutable."
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Compute Engine zone within region."
  type        = string
  default     = "us-central1-a"

  validation {
    condition     = startswith(var.zone, "${var.region}-")
    error_message = "zone must belong to region."
  }
}

variable "machine_type" {
  description = "Small CPU-only FastAPI demo VM."
  type        = string
  default     = "e2-small"
}

variable "certificate_email" {
  description = "Contact email for the Let's Encrypt ACME account."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", var.certificate_email))
    error_message = "Provide a valid certificate contact email."
  }
}
