###############################################################################
# Artifact Store — GCP Cloud Storage
#
# GCS bucket for model artifacts (checkpoints, trained models, datasets).
# Training cluster writes, inference cluster reads.
###############################################################################

resource "google_storage_bucket" "artifacts" {
  name     = var.bucket_name
  project  = var.project_id
  location = var.region

  uniform_bucket_level_access = true

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type          = "SetStorageClass"
      storage_class = "NEARLINE"
    }
  }

  labels = merge(var.labels, {
    purpose = "model-artifacts"
  })
}

# IAM: training cluster service account can write
resource "google_storage_bucket_iam_member" "training_write" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.training_service_account}"
}

# IAM: inference cluster service account can read
resource "google_storage_bucket_iam_member" "inference_read" {
  bucket = google_storage_bucket.artifacts.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.inference_service_account}"
}
