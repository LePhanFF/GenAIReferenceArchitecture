###############################################################################
# GCP VPC Network for GKE
#
# Simple networking: custom-mode VPC with a single subnet
# GCP handles NAT via Cloud NAT (no fixed instance cost, pay per usage)
# Cloud NAT cost: ~$1/mo per NAT gateway + $0.045/GB
###############################################################################

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# -----------------------------------------------------------------------------
# VPC Network
# -----------------------------------------------------------------------------
resource "google_compute_network" "this" {
  name                    = "${var.name}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false # Custom mode — we define subnets explicitly
  routing_mode            = "REGIONAL"
}

# -----------------------------------------------------------------------------
# Subnet for GKE
# Secondary ranges for pods and services (required by VPC-native GKE)
# -----------------------------------------------------------------------------
resource "google_compute_subnetwork" "gke" {
  name          = "${var.name}-gke-subnet"
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.this.id
  ip_cidr_range = var.subnet_cidr

  # Secondary ranges for GKE pods and services
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = var.pods_cidr
  }

  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = var.services_cidr
  }

  private_ip_google_access = true # Allow nodes to reach Google APIs without public IPs

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# -----------------------------------------------------------------------------
# Cloud Router + Cloud NAT (for private GKE nodes to reach the internet)
# Much cheaper than AWS NAT Gateway — pay only for usage
# -----------------------------------------------------------------------------
resource "google_compute_router" "this" {
  name    = "${var.name}-router"
  project = var.project_id
  region  = var.region
  network = google_compute_network.this.id

  bgp {
    asn = 64514
  }
}

resource "google_compute_router_nat" "this" {
  name    = "${var.name}-nat"
  project = var.project_id
  region  = var.region
  router  = google_compute_router.this.name

  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# -----------------------------------------------------------------------------
# Firewall Rules
# -----------------------------------------------------------------------------

# Allow internal communication within the VPC
resource "google_compute_firewall" "internal" {
  name    = "${var.name}-allow-internal"
  project = var.project_id
  network = google_compute_network.this.id

  allow {
    protocol = "tcp"
  }

  allow {
    protocol = "udp"
  }

  allow {
    protocol = "icmp"
  }

  source_ranges = [var.subnet_cidr, var.pods_cidr, var.services_cidr]
}

# Allow health checks from Google load balancers
resource "google_compute_firewall" "health_checks" {
  name    = "${var.name}-allow-health-checks"
  project = var.project_id
  network = google_compute_network.this.id

  allow {
    protocol = "tcp"
  }

  # Google health check IP ranges
  source_ranges = ["35.191.0.0/16", "130.211.0.0/22"]
}

# -----------------------------------------------------------------------------
# Variables
# -----------------------------------------------------------------------------
variable "name" {
  description = "Name prefix for all resources"
  type        = string
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "subnet_cidr" {
  description = "CIDR range for the GKE subnet"
  type        = string
  default     = "10.0.0.0/20"
}

variable "pods_cidr" {
  description = "Secondary CIDR range for pods"
  type        = string
  default     = "10.16.0.0/14"
}

variable "services_cidr" {
  description = "Secondary CIDR range for services"
  type        = string
  default     = "10.20.0.0/20"
}

# -----------------------------------------------------------------------------
# Outputs
# -----------------------------------------------------------------------------
output "network_name" {
  description = "Name of the VPC network"
  value       = google_compute_network.this.name
}

output "network_self_link" {
  description = "Self link of the VPC network"
  value       = google_compute_network.this.self_link
}

output "subnet_name" {
  description = "Name of the GKE subnet"
  value       = google_compute_subnetwork.gke.name
}

output "subnet_self_link" {
  description = "Self link of the GKE subnet"
  value       = google_compute_subnetwork.gke.self_link
}
