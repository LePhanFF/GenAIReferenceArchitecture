###############################################################################
# Training Cluster — GCP GKE (Dev)
#
# Training cluster: GPU-heavy, all spot, ephemeral workloads.
# Training jobs are fault-tolerant with checkpointing, so 100% spot is safe.
#
# COST OPTIMIZED:
#   GKE control plane (zonal):  $0      (FREE — first zonal cluster per project)
#   1x e2-small SPOT:           ~$5/mo  (CPU baseline for scheduling)
#   Cloud NAT:                  ~$1/mo  (minimal)
#   GPU (when training):        ~$0.70/hr spot (g2-standard-8 L4)
#   GPU (idle):                 $0      (scale-to-zero)
#   ─────────────────────────────────────
#   Total idle:                 ~$6/mo
#
# No KEDA needed — training jobs run to completion (K8s Jobs, not Deployments).
# Larger disk for model checkpoints (100Gi).
#
# To destroy: terraform destroy
###############################################################################

locals {
  environment  = "dev"
  cluster_name = "genai-training-${local.environment}"

  labels = {
    environment = local.environment
    project     = "genai-reference-architecture"
    purpose     = "training"
    managed-by  = "terraform"
  }
}

# -----------------------------------------------------------------------------
# Networking
# -----------------------------------------------------------------------------
module "networking" {
  source = "../../../../modules/networking/gcp"

  name       = local.cluster_name
  project_id = var.project_id
  region     = var.region

  subnet_cidr   = "10.1.0.0/20"
  pods_cidr     = "10.24.0.0/14"
  services_cidr = "10.28.0.0/20"
}

# -----------------------------------------------------------------------------
# GKE Cluster — ZONAL (FREE), ALL SPOT, training-optimized
# -----------------------------------------------------------------------------
module "gke" {
  source = "../../../../modules/gke"

  cluster_name = local.cluster_name
  project_id   = var.project_id
  region       = var.region
  zone         = "a" # COST: Zonal = FREE control plane

  network    = module.networking.network_name
  subnetwork = module.networking.subnet_name

  # CPU nodes — SPOT, smallest viable (just for scheduling/monitoring)
  cpu_machine_type = "e2-small"
  cpu_spot         = true
  cpu_min_nodes    = 1
  cpu_max_nodes    = 2

  # GPU nodes — SPOT, larger for training
  # g2-standard-8: 1x L4 GPU, 8 vCPU, 32GB RAM (more CPU/RAM for data loading)
  gpu_machine_type = "g2-standard-8"
  gpu_max_nodes    = 4 # Training needs more GPU concurrency

  # NAP limits — higher for training workloads
  nap_cpu_limit       = 32
  nap_memory_limit_gb = 128
  gpu_limit           = 4

  labels = local.labels
}
