# Training cluster — AWS (Dev)
# GPU-heavy, all spot, fault-tolerant with checkpointing.

region             = "us-east-1"
kubernetes_version = "1.31"

# GPU instance types (Karpenter picks cheapest available spot)
# g5.12xlarge: 4x NVIDIA A10G, 96GB total VRAM, ~$1.50/hr spot (multi-GPU training)
# g5.xlarge:   1x NVIDIA A10G, 24GB VRAM, ~$0.30/hr spot (single-GPU fine-tuning)
gpu_instance_types = ["g5.12xlarge", "g5.xlarge"]
