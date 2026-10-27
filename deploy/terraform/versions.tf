terraform {
  required_version = ">= 1.14, < 2.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }

  # Local state is intentional. Never commit state or saved plans to Git.
  backend "local" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
  zone    = var.zone

  # Attribute API quota for gcloud user tokens to this project.
  billing_project       = var.project_id
  user_project_override = true
}
