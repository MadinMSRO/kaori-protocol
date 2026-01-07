resource "google_cloud_run_service" "kaori_api" {
  name     = "kaori-api"
  location = var.region

  template {
    spec {
      service_account_name = google_service_account.kaori_api_sa.email
      containers {
        image = "gcr.io/${var.project_id}/kaori-api:latest"
        
        env {
          name = "KAORI_ENV"
          value = "production"
        }
        env {
            name = "GCS_BUCKET_NAME"
            value = google_storage_bucket.bronze_layer.name
        }
        env {
            name = "DB_CONNECTION_STRING"
            value = "bigquery://${var.project_id}/kaori_core" 
        }
      }
    }
  }

  traffic {
    percent         = 100
    latest_revision = true
  }
}

output "api_url" {
  value = google_cloud_run_service.kaori_api.status[0].url
}
