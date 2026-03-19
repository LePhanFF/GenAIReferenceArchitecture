# Terraform backend configuration
# Uncomment the S3 backend block when ready for team collaboration.
# For local development, Terraform uses a local state file by default.

# terraform {
#   backend "s3" {
#     bucket         = "genai-ref-arch-terraform-state"
#     key            = "dev/training/aws/terraform.tfstate"
#     region         = "us-east-1"
#     encrypt        = true
#     dynamodb_table = "terraform-state-lock"
#   }
# }
