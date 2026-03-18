###############################################################################
# Dev Environment — AWS EKS
#
# COST OPTIMIZED:
#   EKS control plane:          $73/mo  (unavoidable, GCP is FREE)
#   1x t3.small SPOT:           ~$5/mo  (was $30 on-demand t3.medium)
#   NAT Gateway:                $0      (skipped — nodes use public subnets)
#   GPU (when running):         ~$0.30/hr spot (g5.xlarge)
#   GPU (idle):                 $0      (Karpenter scale-to-zero)
#   ─────────────────────────────────────
#   Total idle:                 ~$78/mo (was $135 — saved 42%)
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
# Networking — NO NAT gateway for dev (saves $32/mo)
# -----------------------------------------------------------------------------
module "networking" {
  source = "../../../modules/networking/aws"

  name               = local.cluster_name
  cluster_name       = local.cluster_name
  vpc_cidr           = var.vpc_cidr
  az_count           = 2 # 2 AZs is enough for dev
  enable_nat_gateway = false # COST: Save $32/mo — nodes use public subnets

  tags = local.tags
}

# -----------------------------------------------------------------------------
# EKS Cluster — SPOT CPU nodes
# -----------------------------------------------------------------------------
module "eks" {
  source = "../../../modules/eks"

  cluster_name       = local.cluster_name
  kubernetes_version = var.kubernetes_version
  vpc_id             = module.networking.vpc_id
  subnet_ids         = module.networking.private_subnet_ids

  # CPU nodes — SPOT for dev (saves ~70%)
  cpu_instance_types = ["t3.small"] # COST: t3.small ($0.021/hr) vs t3.medium ($0.042)
  cpu_spot           = true         # COST: SPOT saves another ~70%
  cpu_desired_size   = 1
  cpu_min_size       = 1
  cpu_max_size       = 3

  # GPU nodes via Karpenter — SPOT, scale to zero
  # g5.xlarge: A10G 24GB, g6.xlarge: L4 24GB
  # Karpenter picks cheapest available spot
  gpu_instance_types = var.gpu_instance_types
  gpu_limit          = 2 # Max 2 GPUs in dev (cost safety)

  karpenter_version = var.karpenter_version

  tags = local.tags
}
