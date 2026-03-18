###############################################################################
# Dev Environment — AWS EKS
#
# Estimated monthly cost (idle):
#   1x t3.medium (CPU baseline):  ~$30
#   1x NAT Gateway:               ~$32
#   EKS control plane:            ~$73
#   Total idle:                   ~$135/mo
#
# GPU cost (when running):
#   g5.xlarge spot:               ~$0.40/hr ($290/mo if 24/7)
#   g6.xlarge spot:               ~$0.35/hr ($252/mo if 24/7)
#   But with scale-to-zero:      $0 when not in use
#
# To destroy: terraform destroy
###############################################################################

locals {
  environment  = "dev"
  cluster_name = "genai-${local.environment}"

  tags = {
    Environment = local.environment
    Project     = "genai-reference-architecture"
    ManagedBy   = "terraform"
  }
}

# -----------------------------------------------------------------------------
# Networking
# -----------------------------------------------------------------------------
module "networking" {
  source = "../../../modules/networking/aws"

  name         = local.cluster_name
  cluster_name = local.cluster_name
  vpc_cidr     = var.vpc_cidr
  az_count     = 2 # 2 AZs is enough for dev

  tags = local.tags
}

# -----------------------------------------------------------------------------
# EKS Cluster
# -----------------------------------------------------------------------------
module "eks" {
  source = "../../../modules/eks"

  cluster_name       = local.cluster_name
  kubernetes_version = var.kubernetes_version
  vpc_id             = module.networking.vpc_id
  subnet_ids         = module.networking.private_subnet_ids

  # CPU nodes — minimal baseline
  cpu_instance_types = ["t3.medium"]
  cpu_desired_size   = 1
  cpu_min_size       = 1
  cpu_max_size       = 3

  # GPU nodes via Karpenter — scale to zero
  # g5.xlarge: A10G 24GB, g6.xlarge: L4 24GB
  # Both are spot instances, Karpenter picks cheapest available
  gpu_instance_types = var.gpu_instance_types
  gpu_limit          = 2 # Max 2 GPUs in dev (cost safety)

  karpenter_version = var.karpenter_version

  tags = local.tags
}
