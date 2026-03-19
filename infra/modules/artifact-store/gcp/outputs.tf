output "bucket_name" {
  description = "Name of the GCS bucket"
  value       = google_storage_bucket.artifacts.name
}

output "bucket_url" {
  description = "URL of the GCS bucket"
  value       = google_storage_bucket.artifacts.url
}

output "bucket_self_link" {
  description = "Self-link of the GCS bucket"
  value       = google_storage_bucket.artifacts.self_link
}
