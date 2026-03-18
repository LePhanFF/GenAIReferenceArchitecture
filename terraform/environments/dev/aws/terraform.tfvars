# Dev environment — AWS
# COST OPTIMIZED for minimum spend

region             = "us-east-1"
kubernetes_version = "1.31"

# GPU instance types (Karpenter picks cheapest available spot)
# g6.xlarge: NVIDIA L4, 24GB VRAM, ~$0.24/hr spot (cheapest)
# g5.xlarge: NVIDIA A10G, 24GB VRAM, ~$0.30/hr spot (fallback)
gpu_instance_types = ["g6.xlarge", "g5.xlarge"]
