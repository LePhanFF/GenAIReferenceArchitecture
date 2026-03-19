###############################################################################
# Dev Environment — GCP GKE
#
# COST OPTIMIZED (GCP is MUCH cheaper than AWS for dev):
#   GKE control plane (zonal):  $0      (FREE — first zonal cluster per project)
#   1x e2-small SPOT:           ~$5/mo  (CPU baseline)
#   Cloud NAT:                  ~$1/mo  (minimal)
#   GPU (when running):         ~$0.23/hr spot (g2-standard-4 L4)
#   GPU (idle):                 $0      (scale-to-zero)
#   ─────────────────────────────────────
#   Total idle:                 ~$6/mo  (vs AWS ~$78/mo)
#
# WHY GCP IS CHEAPER:
# - Free zonal cluster (AWS EKS: $73/mo)
# - Spot L4 GPU: $0.23/hr (AWS g5.xlarge spot: $0.30/hr)
# - e2-small spot: $0.007/hr (AWS t3.small spot: $0.006/hr — similar)
# - Cloud NAT: $1/mo (AWS NAT Gateway: $32/mo)
#
# To destroy: terraform destroy
###############################################################################

locals {
  environment  = "dev"
  cluster_name = "genai-${local.environment}"

  labels = {
    environment = local.environment
    project     = "genai-reference-architecture"
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

  subnet_cidr   = "10.0.0.0/20"
  pods_cidr     = "10.16.0.0/14"
  services_cidr = "10.20.0.0/20"
}

# -----------------------------------------------------------------------------
# GKE Cluster — ZONAL (FREE), ALL SPOT
# -----------------------------------------------------------------------------
module "gke" {
  source = "../../../../modules/gke"

  cluster_name = local.cluster_name
  project_id   = var.project_id
  region       = var.region
  zone         = "a" # COST: Zonal = FREE control plane (regional = $73/mo)
  network      = module.networking.network_name
  subnetwork   = module.networking.subnet_name

  # CPU nodes — SPOT, smallest viable
  cpu_machine_type = "e2-small" # COST: 2 vCPU shared, 2GB — enough for dev
  cpu_spot         = true       # COST: Spot saves 60-91%
  cpu_min_nodes    = 1
  cpu_max_nodes    = 3

  # GPU nodes — SPOT, scale to zero
  # g2-standard-4: 1x L4 GPU, 4 vCPU, 16GB RAM
  gpu_machine_type = "g2-standard-4"
  gpu_max_nodes    = 2 # Cost safety limit for dev

  # NAP limits — cap auto-provisioning
  nap_cpu_limit       = 16
  nap_memory_limit_gb = 64
  gpu_limit           = 2

  labels = local.labels
}
