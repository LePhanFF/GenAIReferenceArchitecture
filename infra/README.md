# Infrastructure

Terraform-managed infrastructure for the GenAI Reference Architecture.

## Cluster Topology

Two separate clusters per environment, split by **purpose**:

```
infra/
  modules/           # Reusable Terraform modules
    eks/             # AWS EKS cluster module
    gke/             # GCP GKE cluster module
    networking/      # VPC/network per cloud
    artifact-store/  # S3/GCS for model artifacts
  clusters/          # Cluster definitions by PURPOSE and ENVIRONMENT
    training/        # GPU-heavy, all spot, training workloads only
      dev/
        aws/
        gcp/
    inference/       # Serving + apps, stable baseline, user-facing
      dev/
        aws/
        gcp/
      qa/            # (future)
      staging/       # (future)
      prod/          # (future)
```

## Why Two Clusters?

| Concern | Training | Inference |
|---------|----------|-----------|
| GPU type | Large (multi-GPU, A100/A10G) | Small (single L4/T4) |
| Spot/Preemptible | 100% (fault-tolerant) | Mixed (stable baseline) |
| Scaling | Jobs run to completion | KEDA scale-to-zero |
| Disk | 100Gi+ (checkpoints) | Smaller (model cache) |
| Blast radius | Training failure = retry | Inference failure = user impact |

## Artifact Store

The `artifact-store` module creates an S3 bucket (AWS) or GCS bucket (GCP) that bridges the two clusters:

- **Training cluster** writes model checkpoints and trained models
- **Inference cluster** reads models for serving
- Versioning enabled for rollback
- Lifecycle policy moves old artifacts to cheaper storage after 90 days

## Getting Started

```bash
# Deploy inference cluster (GCP, cheapest for dev)
cd infra/clusters/inference/dev/gcp
terraform init && terraform apply

# Deploy training cluster
cd infra/clusters/training/dev/gcp
terraform init && terraform apply
```
