variable "bucket_name" {
  description = "Name of the GCS bucket for model artifacts"
  type        = string
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCS bucket location"
  type        = string
  default     = "us-central1"
}

variable "training_service_account" {
  description = "Service account email for the training cluster (write access)"
  type        = string
}

variable "inference_service_account" {
  description = "Service account email for the inference cluster (read access)"
  type        = string
}

variable "labels" {
  description = "Labels to apply to the bucket"
  type        = map(string)
  default     = {}
}
