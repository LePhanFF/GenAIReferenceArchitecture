variable "cluster_name" {
  description = "Name of the EKS cluster"
  type        = string
}

variable "kubernetes_version" {
  description = "Kubernetes version for EKS"
  type        = string
  default     = "1.31"
}

variable "vpc_id" {
  description = "VPC ID where the cluster will be created"
  type        = string
}

variable "subnet_ids" {
  description = "List of subnet IDs for the EKS cluster (private subnets recommended)"
  type        = list(string)
}

variable "cpu_instance_types" {
  description = "Instance types for CPU managed node group. COST: t3.small ($0.021/hr) is enough for dev"
  type        = list(string)
  default     = ["t3.small"]
}

variable "cpu_spot" {
  description = "Use spot instances for CPU nodes. COST: ~70% savings. Safe for dev, disable for prod."
  type        = bool
  default     = true
}

variable "cpu_desired_size" {
  description = "Desired number of CPU nodes"
  type        = number
  default     = 1
}

variable "cpu_min_size" {
  description = "Minimum number of CPU nodes"
  type        = number
  default     = 1
}

variable "cpu_max_size" {
  description = "Maximum number of CPU nodes"
  type        = number
  default     = 3
}

variable "gpu_instance_types" {
  description = "GPU instance types for Karpenter (cheapest A10G/L4 options)"
  type        = list(string)
  default     = ["g5.xlarge", "g6.xlarge"]
}

variable "gpu_limit" {
  description = "Maximum number of GPUs Karpenter can provision (cost safety limit)"
  type        = number
  default     = 4
}

variable "karpenter_version" {
  description = "Karpenter Helm chart version"
  type        = string
  default     = "1.1.1"
}

variable "tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default     = {}
}
