resource "google_storage_bucket" "bronze_layer" {
  name          = "kaori-bronze-${random_id.suffix.hex}"
  location      = var.region
  force_destroy = true

  uniform_bucket_level_access = true
  
  versioning {
    enabled = true
  }
}

output "bronze_bucket_name" {
  value = google_storage_bucket.bronze_layer.name
}
