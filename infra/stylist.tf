resource "google_project_service" "this" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "firebase.googleapis.com",
    "firebasehosting.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "stylist" {
  location      = var.gcp_region
  repository_id = "${var.name}-stylist"
  format        = "DOCKER"

  cleanup_policies {
    id     = "keep-last-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "${var.name}-gemini-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.this]
}

resource "google_secret_manager_secret_version" "gemini_api_key" {
  secret      = google_secret_manager_secret.gemini_api_key.id
  secret_data = var.gemini_api_key
}

resource "google_service_account" "stylist" {
  account_id   = "${var.name}-stylist"
  display_name = "Outfit checker stylist (Cloud Run)"
}

resource "google_secret_manager_secret_iam_member" "stylist" {
  secret_id = google_secret_manager_secret.gemini_api_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.stylist.member
}

resource "google_cloud_run_v2_service" "stylist" {
  name                = "${var.name}-stylist"
  location            = var.gcp_region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account = google_service_account.stylist.email

    scaling {
      min_instance_count = 0
      max_instance_count = 2
    }

    containers {
      image = var.stylist_image

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      env {
        name  = "GOOGLE_GENAI_USE_ENTERPRISE"
        value = "0"
      }
      env {
        name  = "STYLIST_MODEL"
        value = var.stylist_model
      }
      env {
        name  = "ALLOWED_ORIGINS"
        value = join(",", local.allowed_origins)
      }
      env {
        name = "GOOGLE_API_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gemini_api_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  depends_on = [
    google_project_service.this,
    google_secret_manager_secret_version.gemini_api_key,
    google_secret_manager_secret_iam_member.stylist,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "stylist_public" {
  name     = google_cloud_run_v2_service.stylist.name
  location = google_cloud_run_v2_service.stylist.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_firebase_project" "this" {
  provider   = google-beta
  project    = var.gcp_project
  depends_on = [google_project_service.this]
}

resource "google_firebase_hosting_site" "web" {
  provider = google-beta
  project  = google_firebase_project.this.project
  site_id  = local.hosting_site_id
}
