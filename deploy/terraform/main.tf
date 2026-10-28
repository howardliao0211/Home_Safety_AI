locals {
  name = "home-safety-demo"
  labels = {
    application = "home-safety-ai"
    environment = "demo"
    managed_by  = "terraform"
  }
  services = toset([
    "artifactregistry.googleapis.com",
    "cloudtasks.googleapis.com",
    "cloudscheduler.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "identitytoolkit.googleapis.com",
    "firebase.googleapis.com",
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
  for_each  = toset(["groq-api-key", "muse-api-key"])
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

# Dispatch survives Cloud Run request/process lifetimes. Each highlight attempt is
# its own task and Firestore claim; limits admit 12 overlapping attempts per assessment.
resource "google_cloud_tasks_queue" "annotations" {
  name     = var.annotation_queue_name
  location = var.region
  rate_limits {
    max_dispatches_per_second = 20
    max_concurrent_dispatches = 24
  }
  retry_config {
    max_attempts = 5
    min_backoff  = "5s"
    max_backoff  = "60s"
  }
  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "annotation_enqueue" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_service_account_iam_member" "annotation_act_as" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.backend.email}"
}

# Needed for Cloud Tasks to mint OIDC tokens for its HTTP deliveries.
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_service_account_iam_member" "annotation_oidc" {
  service_account_id = google_service_account.backend.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-cloudtasks.iam.gserviceaccount.com"
  depends_on         = [google_project_service.required]
}

# The initial Cloud Run URL is known only after the first release. Set it and
# re-apply Terraform before enabling highlighting in a production revision.
resource "google_cloud_scheduler_job" "annotation_recovery" {
  count     = var.annotation_worker_url == "" ? 0 : 1
  name      = "home-safety-annotation-recovery"
  region    = var.region
  schedule  = "* * * * *"
  time_zone = "Etc/UTC"
  http_target {
    uri         = "${trimsuffix(var.annotation_worker_url, "/")}/internal/annotations/recover"
    http_method = "POST"
    oidc_token {
      service_account_email = google_service_account.backend.email
      audience              = trimsuffix(var.annotation_worker_url, "/")
    }
  }
  depends_on = [google_project_service.required]
}

resource "google_firestore_field" "annotation_dispatch" {
  project    = var.project_id
  database   = google_firestore_database.assessments.name
  collection = "assessments"
  field      = "annotation_dispatch_pending"
  index_config {
    indexes {
      order       = "ASCENDING"
      query_scope = "COLLECTION_GROUP"
    }
  }
}

resource "google_identity_platform_config" "accounts" {
  project = var.project_id
  sign_in {
    allow_duplicate_emails = false
    email {
      enabled           = true
      password_required = true
    }
  }
  depends_on = [google_project_service.required]
}
resource "google_project_iam_member" "backend_auth" {
  project = var.project_id
  role    = "roles/firebaseauth.admin"
  member  = "serviceAccount:${google_service_account.backend.email}"
}
