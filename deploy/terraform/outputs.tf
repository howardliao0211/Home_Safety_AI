output "project_id" {
  value = var.project_id
}

output "backend_ip" {
  value = google_compute_address.backend.address
}

output "backend_url" {
  description = "HTTPS endpoint; application routes require a deployed backend."
  value       = "https://${google_compute_address.backend.address}"
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

output "ssh_command" {
  description = "Use the same Google account used for provisioning."
  value       = "gcloud compute ssh ${google_compute_instance.backend.name} --project=${var.project_id} --zone=${var.zone} --tunnel-through-iap"
}
