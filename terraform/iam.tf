resource "google_service_account" "kaori_api_sa" {
  account_id   = "kaori-api-sa"
  display_name = "Kaori API Service Account"
}

resource "google_project_iam_member" "api_bq_editor" {
  project = var.project_id
  role    = "roles/bigquery.dataEditor"
  member  = "serviceAccount:${google_service_account.kaori_api_sa.email}"
}

resource "google_project_iam_member" "api_storage_admin" {
  project = var.project_id
  role    = "roles/storage.objectAdmin"
  member  = "serviceAccount:${google_service_account.kaori_api_sa.email}"
}

resource "google_project_iam_member" "api_run_invoker" {
    project = var.project_id
    role = "roles/run.invoker"
    member = "allUsers" # Public API
}
