locals {
  name = "home-safety-demo"
  labels = {
    application = "home-safety-ai"
    environment = "demo"
    managed_by  = "terraform"
  }
  services = toset([
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "firestore.googleapis.com",
    "iam.googleapis.com",
    "iap.googleapis.com",
    "logging.googleapis.com",
    "oslogin.googleapis.com",
    "storage.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_network" "backend" {
  name                    = local.name
  auto_create_subnetworks = false
  depends_on              = [google_project_service.required]
}

resource "google_compute_subnetwork" "backend" {
  name                     = local.name
  region                   = var.region
  network                  = google_compute_network.backend.id
  ip_cidr_range            = "10.42.0.0/24"
  private_ip_google_access = true
}

resource "google_service_account" "backend" {
  account_id   = "home-safety-demo"
  display_name = "Home Safety demo backend"
  depends_on   = [google_project_service.required]
}

resource "google_compute_firewall" "web" {
  name    = "${local.name}-web"
  network = google_compute_network.backend.id

  # Port 80 serves ACME challenges only. All application traffic uses TLS.
  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
  source_ranges           = ["0.0.0.0/0"]
  target_service_accounts = [google_service_account.backend.email]
}

resource "google_compute_firewall" "iap_ssh" {
  name    = "${local.name}-iap-ssh"
  network = google_compute_network.backend.id

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
  source_ranges           = ["35.235.240.0/20"]
  target_service_accounts = [google_service_account.backend.email]
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

resource "google_project_iam_member" "backend_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.backend.email}"
}

resource "google_compute_address" "backend" {
  name       = local.name
  region     = var.region
  depends_on = [google_project_service.required]
}

resource "google_compute_instance" "backend" {
  name                      = local.name
  zone                      = var.zone
  machine_type              = var.machine_type
  allow_stopping_for_update = true
  labels                    = local.labels

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
      size  = 10
      type  = "pd-standard"
    }
  }

  network_interface {
    subnetwork = google_compute_subnetwork.backend.id
    access_config {
      nat_ip = google_compute_address.backend.address
    }
  }

  service_account {
    email  = google_service_account.backend.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    enable-oslogin           = "TRUE"
    block-project-ssh-keys   = "TRUE"
    disable-legacy-endpoints = "TRUE"
  }

  metadata_startup_script = templatefile("${path.module}/templates/startup.sh.tftpl", {
    public_ip         = google_compute_address.backend.address
    certificate_email = var.certificate_email
    project_id        = var.project_id
    photos_bucket     = google_storage_bucket.photos.name
    database_id       = google_firestore_database.assessments.name
  })

  shielded_instance_config {
    enable_secure_boot          = true
    enable_vtpm                 = true
    enable_integrity_monitoring = true
  }

  depends_on = [
    google_compute_firewall.web,
    google_compute_firewall.iap_ssh,
    google_storage_bucket_iam_member.backend_photos,
    google_project_iam_member.backend_database,
    google_project_iam_member.backend_logs,
  ]
}
