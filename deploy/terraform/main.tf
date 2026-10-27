locals {
  name = "home-safety-demo"
  labels = {
    application = "home-safety-ai"
    environment = "demo"
    managed_by  = "terraform"
  }
  services = toset([
    "artifactregistry.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_service_account" "backend" {
  account_id   = "home-safety-demo"
  display_name = "Home Safety Cloud Run backend"
  depends_on   = [google_project_service.required]
}

resource "google_storage_bucket" "photos" {
  name                        = "${var.project_id}-demo-photos"
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = true
  labels                      = local.labels

  versioning {
    enabled = false
  }
  soft_delete_policy {
    retention_duration_seconds = 0
  }
  depends_on = [google_project_service.required]
}

resource "google_storage_bucket_iam_member" "backend_photos" {
  bucket = google_storage_bucket.photos.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_firestore_database" "assessments" {
  project                     = var.project_id
  name                        = "(default)"
  location_id                 = var.region
  type                        = "FIRESTORE_NATIVE"
  database_edition            = "STANDARD"
  concurrency_mode            = "PESSIMISTIC"
  app_engine_integration_mode = "DISABLED"
  delete_protection_state     = "DELETE_PROTECTION_DISABLED"
  deletion_policy             = "DELETE"

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "backend_database" {
  project    = var.project_id
  role       = "roles/datastore.user"
  member     = "serviceAccount:${google_service_account.backend.email}"
  depends_on = [google_firestore_database.assessments]
}

# Cloud Run itself is released by scripts/deploy-gcp.py. Terraform owns its
# supporting resources; image revisions and traffic are owned by the release CLI.
resource "google_artifact_registry_repository" "backend" {
  location      = var.region
  repository_id = "home-safety"
  description   = "Versioned Home Safety backend images"
  format        = "DOCKER"
  labels        = local.labels
  docker_config {
    immutable_tags = true
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "backend" {
  for_each  = toset(["groq-api-key", "demo-bearer-token"])
  secret_id = "home-safety-${each.key}"
  labels    = local.labels
  replication {
    auto {}
  }
  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_iam_member" "backend" {
  for_each  = google_secret_manager_secret.backend
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.backend.email}"
}
