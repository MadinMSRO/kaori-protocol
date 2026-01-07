resource "google_bigquery_dataset" "kaori_dataset" {
  dataset_id                  = "kaori_core"
  friendly_name               = "Kaori Protocol Core"
  description                 = "Main dataset for Kaori observations and truth states"
  location                    = "US"
  default_table_expiration_ms = null
}

resource "google_bigquery_table" "raw_observations" {
  dataset_id = google_bigquery_dataset.kaori_dataset.dataset_id
  table_id   = "raw_observations"
  
  schema = <<EOF
[
  {
    "name": "ingest_id",
    "type": "STRING",
    "mode": "REQUIRED"
  },
  {
    "name": "status",
    "type": "STRING",
    "mode": "REQUIRED"
  },
  {
    "name": "raw_payload",
    "type": "JSON",
    "mode": "NULLABLE"
  },
  {
    "name": "file_path",
    "type": "STRING",
    "mode": "REQUIRED"
  },
  {
    "name": "result_truthkey",
    "type": "STRING",
    "mode": "NULLABLE"
  },
  {
    "name": "processing_error",
    "type": "STRING",
    "mode": "NULLABLE"
  }
]
EOF
}

# Note: Silver/Gold tables (TruthStates) will be created by SQLAlchemy 
# if we use the BigQuery dialect, or we can define them here.
# For now, we define the critical persistence layer.
