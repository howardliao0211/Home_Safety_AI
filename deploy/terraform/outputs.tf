output "deployment_config" {
  description = "Non-secret inputs consumed by scripts/deploy-gcp.py."
  value = {
    project_id             = var.project_id
    region                 = var.region
    service_name           = "home-safety-demo"
    repository             = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.backend.repository_id}"
    service_account        = google_service_account.backend.email
    photos_bucket          = google_storage_bucket.photos.name
    database_id            = google_firestore_database.assessments.name
    muse_secret            = google_secret_manager_secret.backend["muse-api-key"].secret_id
    annotation_tasks_queue = google_cloud_tasks_queue.annotations.id
    annotation_worker_url  = trimsuffix(var.annotation_worker_url, "/")
    groq_secret            = google_secret_manager_secret.backend["groq-api-key"].secret_id
    demo_secret            = "home-safety-demo-bearer-token"
    api_url                = var.domain_name == "" ? "" : "https://api.${var.domain_name}"
    load_balancer_ip       = try(google_compute_global_address.api[0].address, "")
    dns_zone               = try(google_dns_managed_zone.api[0].name, "")
    certificate_name       = try(google_compute_managed_ssl_certificate.api[0].name, "")
  }
}

output "domain_name_servers" {
  description = "Use these name servers when registering/delegating the domain outside this state."
  value       = try(google_dns_managed_zone.api[0].name_servers, [])
}

output "project_id" {
  value = var.project_id
}

output "photos_bucket" {
  value = google_storage_bucket.photos.name
}

output "firestore_database" {
  value = google_firestore_database.assessments.id
}

output "backend_service_account" {
  value = google_service_account.backend.email
}
