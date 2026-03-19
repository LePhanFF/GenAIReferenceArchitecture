output "bucket_name" {
  description = "Name of the S3 bucket"
  value       = aws_s3_bucket.artifacts.id
}

output "bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.artifacts.arn
}

output "training_write_policy_arn" {
  description = "ARN of the IAM policy for training cluster write access"
  value       = aws_iam_policy.training_write.arn
}

output "inference_read_policy_arn" {
  description = "ARN of the IAM policy for inference cluster read access"
  value       = aws_iam_policy.inference_read.arn
}
