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
