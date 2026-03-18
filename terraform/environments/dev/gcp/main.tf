###############################################################################
# Dev Environment — GCP GKE
#
# Estimated monthly cost (idle):
#   1x e2-medium (CPU baseline):  ~$25
#   Cloud NAT:                    ~$1 + data
#   GKE control plane (free):     $0 (free tier for 1 zonal/regional cluster)
#   Total idle:                   ~$26/mo
#
# GPU cost (when running):
#   g2-standard-4 spot (L4):     ~$0.35/hr ($252/mo if 24/7)
#   With scale-to-zero:          $0 when not in use
#
# GCP is significantly cheaper than AWS for dev (no EKS control plane fee)
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
  source = "../../../modules/networking/gcp"

  name       = local.cluster_name
  project_id = var.project_id
  region     = var.region

  subnet_cidr   = "10.0.0.0/20"
  pods_cidr     = "10.16.0.0/14"
  services_cidr = "10.20.0.0/20"
}

# -----------------------------------------------------------------------------
# GKE Cluster
# -----------------------------------------------------------------------------
module "gke" {
  source = "../../../modules/gke"

  cluster_name = local.cluster_name
  project_id   = var.project_id
  region       = var.region
  network      = module.networking.network_name
  subnetwork   = module.networking.subnet_name

  # CPU nodes — minimal baseline
  cpu_machine_type = "e2-medium"
  cpu_min_nodes    = 1
  cpu_max_nodes    = 3

  # GPU nodes — scale to zero
  # g2-standard-4: 1x L4 GPU, 4 vCPU, 16GB RAM
  gpu_machine_type = "g2-standard-4"
  gpu_max_nodes    = 2 # Cost safety limit for dev

  # NAP limits — cap auto-provisioning
  nap_cpu_limit       = 16
  nap_memory_limit_gb = 64
  gpu_limit           = 2

  labels = local.labels
}
