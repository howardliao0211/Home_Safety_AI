# Domain registration stays outside this state. The serverless NEG targets a
# stable service name, so no Cloud Run resource or revision belongs to Terraform.
resource "google_dns_managed_zone" "api" {
  count       = var.domain_name == "" ? 0 : 1
  name        = "home-safety-api"
  dns_name    = "${var.domain_name}."
  description = "Home Safety phone-test domain"
  depends_on  = [google_project_service.required]
}

resource "google_compute_global_address" "api" {
  count      = var.domain_name == "" ? 0 : 1
  name       = "home-safety-api"
  depends_on = [google_project_service.required]
}

resource "google_dns_record_set" "api" {
  count        = var.domain_name == "" ? 0 : 1
  managed_zone = google_dns_managed_zone.api[0].name
  name         = "api.${var.domain_name}."
  type         = "A"
  ttl          = 300
  rrdatas      = [google_compute_global_address.api[0].address]
}

resource "google_compute_region_network_endpoint_group" "api" {
  count                 = var.domain_name == "" ? 0 : 1
  name                  = "home-safety-api"
  region                = var.region
  network_endpoint_type = "SERVERLESS"
  cloud_run {
    service = local.name
  }
  depends_on = [google_project_service.required]
}

resource "google_compute_backend_service" "api" {
  count                 = var.domain_name == "" ? 0 : 1
  name                  = "home-safety-api"
  protocol              = "HTTP"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  backend {
    group = google_compute_region_network_endpoint_group.api[0].id
  }
}

resource "google_compute_url_map" "api" {
  count           = var.domain_name == "" ? 0 : 1
  name            = "home-safety-api"
  default_service = google_compute_backend_service.api[0].id
}

resource "google_compute_managed_ssl_certificate" "api" {
  count = var.domain_name == "" ? 0 : 1
  name  = "home-safety-api"
  managed {
    domains = ["api.${var.domain_name}"]
  }
  depends_on = [google_project_service.required]
}

resource "google_compute_target_https_proxy" "api" {
  count            = var.domain_name == "" ? 0 : 1
  name             = "home-safety-api"
  url_map          = google_compute_url_map.api[0].id
  ssl_certificates = [google_compute_managed_ssl_certificate.api[0].id]
}

resource "google_compute_global_forwarding_rule" "api" {
  count                 = var.domain_name == "" ? 0 : 1
  name                  = "home-safety-api"
  target                = google_compute_target_https_proxy.api[0].id
  ip_address            = google_compute_global_address.api[0].address
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
}
