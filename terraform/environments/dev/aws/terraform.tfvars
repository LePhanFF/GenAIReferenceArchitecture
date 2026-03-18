# Dev environment — AWS
# Cheapest GPU region with good spot availability

region             = "us-east-1"
kubernetes_version = "1.31"

# GPU instance types (Karpenter picks cheapest available spot)
# g5.xlarge: NVIDIA A10G, 24GB VRAM, ~$0.40/hr spot
# g6.xlarge: NVIDIA L4, 24GB VRAM, ~$0.35/hr spot
gpu_instance_types = ["g5.xlarge", "g6.xlarge"]
