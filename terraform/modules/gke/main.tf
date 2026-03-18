###############################################################################
# GKE Standard Cluster with NAP for GPU Scale-to-Zero
#
# COST OPTIMIZATION:
# - Control plane: FREE (first zonal cluster per project is free)
# - CPU nodes: e2-small SPOT (~$0.007/hr = ~$5/mo)
# - GPU nodes: g2-standard-4 SPOT (~$0.23/hr vs $0.76 on-demand = 70% savings)
# - NAP auto-provisions SPOT nodes for any GPU type
# - All nodes scale to zero when idle
# - Total idle cost: ~$5/mo (1x e2-small spot)
# - GPU cost: $0 when not in use
#
# ZONAL vs REGIONAL:
# - Zonal (us-central1-a): FREE control plane, single zone
# - Regional (us-central1): $0.10/hr = $73/mo, multi-zone HA
# - For dev: USE ZONAL. For prod: switch to regional.
#
# Why Standard + NAP instead of Autopilot:
# - Autopilot has GPU support but less control over node configuration
# - NAP gives us GPU scale-to-zero with explicit resource limits
# - Standard lets us configure NVIDIA drivers and taints precisely
###############################################################################

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# GKE Cluster (Standard mode with NAP)
# -----------------------------------------------------------------------------
resource "google_container_cluster" "this" {
  name     = var.cluster_name
  # COST: Use zonal for FREE control plane (first zonal cluster is free)
  # Set var.zone to null and var.location to region for regional (paid) cluster
  location = var.zone != "" ? "${var.region}-${var.zone}" : var.region
  project  = var.project_id

  # Remove default node pool — we manage our own
  remove_default_node_pool = true
  initial_node_count       = 1

  # Network configuration
  network    = var.network
  subnetwork = var.subnetwork

  # Enable Workload Identity (GKE equivalent of IRSA)
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  # Node Auto-Provisioning (NAP) — creates GPU nodes on demand
  cluster_autoscaling {
    enabled = true

    # CPU limits for auto-provisioned nodes
    resource_limits {
      resource_type = "cpu"
      minimum       = 0
      maximum       = var.nap_cpu_limit
    }

    resource_limits {
      resource_type = "memory"
      minimum       = 0
      maximum       = var.nap_memory_limit_gb
    }

    # GPU limits — controls max GPU spend
    resource_limits {
      resource_type = "nvidia-l4"
      minimum       = 0
      maximum       = var.gpu_limit # Safety limit
    }

    auto_provisioning_defaults {
      # COST: NAP auto-provisions SPOT nodes by default (including GPU)
      management {
        auto_repair  = true
        auto_upgrade = true
      }

      # Disk configuration for auto-provisioned nodes
      disk_size_gb = 100
      disk_type    = "pd-balanced"

      # COST: Use spot for all auto-provisioned nodes (60-91% savings)
      # This means any GPU nodes NAP creates will be spot instances
      provisioning_model = "SPOT"

      # Service account for auto-provisioned nodes
      service_account = google_service_account.gke_nodes.email
      oauth_scopes = [
        "https://www.googleapis.com/auth/cloud-platform",
      ]
    }

    # Autoscaling profile — optimize for cost
    autoscaling_profile = "OPTIMIZE_UTILIZATION"
  }

  # Cluster-level addons
  addons_config {
    gce_persistent_disk_csi_driver_config {
      enabled = true
    }

    gcp_filestore_csi_driver_config {
      enabled = false # Enable if you need shared storage
    }

    horizontal_pod_autoscaling {
      disabled = false
    }

    http_load_balancing {
      disabled = false
    }
  }

  # Release channel
  release_channel {
    channel = "REGULAR"
  }

  # Enable vertical pod autoscaling
  vertical_pod_autoscaling {
    enabled = true
  }

  # Logging and monitoring
  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS"]
    managed_prometheus {
      enabled = true
    }
  }

  # Private cluster config (nodes have no public IPs)
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false # Keep public endpoint for dev
    master_ipv4_cidr_block  = var.master_ipv4_cidr
  }

  # IP allocation for pods and services
  ip_allocation_policy {
    # Use automatic secondary ranges
  }

  deletion_protection = false # Set to true for production

  resource_labels = var.labels
}

# -----------------------------------------------------------------------------
# CPU Node Pool — baseline for system pods
#
# COST OPTIMIZATION:
# - e2-small SPOT: ~$0.007/hr = ~$5/mo (vs e2-medium on-demand ~$25/mo)
# - e2-small: 2 vCPU (shared), 2 GB RAM — sufficient for system pods + services
# - Spot for dev is fine — worst case pods reschedule in seconds
# - For prod: switch to on-demand (spot = false)
# -----------------------------------------------------------------------------
resource "google_container_node_pool" "cpu" {
  name     = "${var.cluster_name}-cpu"
  cluster  = google_container_cluster.this.name
  location = var.zone != "" ? "${var.region}-${var.zone}" : var.region
  project  = var.project_id

  # Scale down to 1 node when idle
  autoscaling {
    min_node_count = var.cpu_min_nodes
    max_node_count = var.cpu_max_nodes
  }

  node_config {
    machine_type = var.cpu_machine_type
    disk_size_gb = 30  # COST: 30GB is enough for dev, saves ~$1/mo per node
    disk_type    = "pd-standard"

    # COST: Spot instances for CPU — 60-91% cheaper
    # For dev: spot is fine (pods reschedule quickly)
    # For prod: set spot = false
    spot = var.cpu_spot

    service_account = google_service_account.gke_nodes.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    labels = {
      "node-type" = "cpu"
      "workload"  = "general"
    }

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# -----------------------------------------------------------------------------
# GPU Node Pool — scales to zero
#
# g2-standard-4: 1x NVIDIA L4 (24GB VRAM), 4 vCPU, 16GB RAM
# Uses spot/preemptible instances for ~65% cost savings
# min_node_count = 0 enables scale-to-zero
#
# Cost: $0 when no GPU pods are scheduled
# -----------------------------------------------------------------------------
resource "google_container_node_pool" "gpu" {
  name     = "${var.cluster_name}-gpu"
  cluster  = google_container_cluster.this.name
  location = var.zone != "" ? "${var.region}-${var.zone}" : var.region
  project  = var.project_id

  # Scale to zero when no GPU pods are pending
  autoscaling {
    min_node_count = 0
    max_node_count = var.gpu_max_nodes
  }

  # Start with zero nodes
  initial_node_count = 0

  node_config {
    machine_type = var.gpu_machine_type

    # SPOT instances — cheapest GPU option (~65% savings)
    spot = true

    disk_size_gb = 100
    disk_type    = "pd-balanced"

    # GPU configuration
    guest_accelerator {
      type  = "nvidia-l4"
      count = 1
      gpu_driver_installation_config {
        gpu_driver_version = "LATEST"
      }
    }

    # Taint GPU nodes so only GPU-requesting pods schedule here
    taint {
      key    = "nvidia.com/gpu"
      value  = "present"
      effect = "NO_SCHEDULE"
    }

    labels = {
      "node-type"   = "gpu"
      "workload"    = "inference"
      "gpu-type"    = "nvidia-l4"
      "spot"        = "true"
    }

    service_account = google_service_account.gke_nodes.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]

    workload_metadata_config {
      mode = "GKE_METADATA"
    }

    shielded_instance_config {
      enable_secure_boot          = true
      enable_integrity_monitoring = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

# -----------------------------------------------------------------------------
# Service Account for GKE Nodes
# -----------------------------------------------------------------------------
resource "google_service_account" "gke_nodes" {
  account_id   = "${var.cluster_name}-nodes"
  display_name = "GKE Node Service Account for ${var.cluster_name}"
  project      = var.project_id
}

# Minimal permissions for nodes
resource "google_project_iam_member" "gke_nodes_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_metric_writer" {
  project = var.project_id
  role    = "roles/monitoring.metricWriter"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_monitoring_viewer" {
  project = var.project_id
  role    = "roles/monitoring.viewer"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}

resource "google_project_iam_member" "gke_nodes_artifact_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.gke_nodes.email}"
}
