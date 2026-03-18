variable "cluster_name" {
  description = "Name of the GKE cluster"
  type        = string
}

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for the cluster"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone suffix (e.g., 'a' for us-central1-a). Set to '' for regional cluster. COST: Zonal = FREE control plane, Regional = $73/mo"
  type        = string
  default     = "a" # Default to zonal for free control plane
}

variable "network" {
  description = "VPC network name or self_link"
  type        = string
}

variable "subnetwork" {
  description = "VPC subnetwork name or self_link"
  type        = string
}

variable "master_ipv4_cidr" {
  description = "CIDR block for the GKE master (must be /28)"
  type        = string
  default     = "172.16.0.0/28"
}

variable "cpu_machine_type" {
  description = "Machine type for CPU node pool. COST: e2-small ($0.017/hr) is enough for dev"
  type        = string
  default     = "e2-small"
}

variable "cpu_spot" {
  description = "Use spot instances for CPU nodes. COST: 60-91% savings. Safe for dev, disable for prod."
  type        = bool
  default     = true
}

variable "cpu_min_nodes" {
  description = "Minimum number of CPU nodes"
  type        = number
  default     = 1
}

variable "cpu_max_nodes" {
  description = "Maximum number of CPU nodes"
  type        = number
  default     = 3
}

variable "gpu_machine_type" {
  description = "Machine type for GPU node pool (must support L4 GPU)"
  type        = string
  default     = "g2-standard-4"
}

variable "gpu_max_nodes" {
  description = "Maximum number of GPU nodes (min is always 0 for scale-to-zero)"
  type        = number
  default     = 2
}

variable "nap_cpu_limit" {
  description = "Maximum vCPUs NAP can auto-provision"
  type        = number
  default     = 16
}

variable "nap_memory_limit_gb" {
  description = "Maximum memory (GB) NAP can auto-provision"
  type        = number
  default     = 64
}

variable "gpu_limit" {
  description = "Maximum number of L4 GPUs (cost safety limit)"
  type        = number
  default     = 4
}

variable "labels" {
  description = "Labels to apply to the cluster"
  type        = map(string)
  default     = {}
}
