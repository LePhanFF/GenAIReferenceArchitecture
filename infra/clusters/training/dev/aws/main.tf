###############################################################################
# Training Cluster — AWS EKS (Dev)
#
# Training cluster: GPU-heavy, all spot, ephemeral workloads.
# Training jobs are fault-tolerant with checkpointing, so 100% spot is safe.
#
# COST OPTIMIZED:
#   EKS control plane:          $73/mo  (unavoidable, GCP is FREE)
#   1x t3.small SPOT:           ~$5/mo  (CPU baseline for scheduling)
#   NAT Gateway:                $0      (skipped — nodes use public subnets)
#   GPU (when training):        ~$1.50/hr spot (g5.12xlarge, 4x A10G)
#   GPU (idle):                 $0      (Karpenter scale-to-zero)
#   ─────────────────────────────────────
#   Total idle:                 ~$78/mo
#
# No KEDA needed — training jobs run to completion (K8s Jobs, not Deployments).
# Karpenter picks cheapest available multi-GPU spot instances.
#
# To destroy: terraform destroy
###############################################################################

locals {
  environment  = "dev"
  cluster_name = "genai-training-${local.environment}"

  tags = {
    Environment = local.environment
    Project     = "genai-reference-architecture"
    Purpose     = "training"
    ManagedBy   = "terraform"
  }
}

# -----------------------------------------------------------------------------
# Networking — NO NAT gateway for dev (saves $32/mo)
# -----------------------------------------------------------------------------
module "networking" {
  source = "../../../../modules/networking/aws"

  name               = local.cluster_name
  cluster_name       = local.cluster_name
  vpc_cidr           = var.vpc_cidr
  az_count           = 2
  enable_nat_gateway = false

  tags = local.tags
}

# -----------------------------------------------------------------------------
# EKS Cluster — SPOT CPU nodes, large GPU instances for training
# -----------------------------------------------------------------------------
module "eks" {
  source = "../../../../modules/eks"

  cluster_name       = local.cluster_name
  kubernetes_version = var.kubernetes_version
  vpc_id             = module.networking.vpc_id
  subnet_ids         = module.networking.private_subnet_ids

  # CPU nodes — SPOT for dev
  cpu_instance_types = ["t3.small"]
  cpu_spot           = true
  cpu_desired_size   = 1
  cpu_min_size       = 1
  cpu_max_size       = 2

  # GPU nodes via Karpenter — SPOT, larger instances for training
  # g5.12xlarge: 4x A10G (96GB total VRAM), good for distributed training
  # g5.xlarge: 1x A10G (24GB VRAM), for single-GPU fine-tuning
  gpu_instance_types = var.gpu_instance_types
  gpu_limit          = 4 # Max 4 GPUs in dev (cost safety)

  karpenter_version = var.karpenter_version

  tags = local.tags
}
