# GenAI Reference Architecture — Project Instructions

## What This Is

A production-ready GenAI platform on Kubernetes. GCP-first (AWS secondary), GitOps-driven, cost-optimized with scale-to-zero GPU. Separate training and inference clusters.

## Architecture Principles

- **Platform, not tools** — The infra is the constant; frameworks (LangChain, LlamaIndex, CrewAI) are interchangeable pods
- **Two-cluster split** — Training cluster (GPU, spot, ephemeral) and inference+apps cluster (stable, user-facing). Shared nothing except artifact store.
- **Cost-optimized** — All spot, scale-to-zero GPU, free GKE zonal cluster
- **Framework-agnostic** — Adding a new workload = Dockerfile + K8s manifest + git push. ArgoCD handles the rest.
- **GitOps** — ArgoCD syncs from this repo, no manual kubectl apply
- **GCP first** — Cheaper ($6/mo idle vs AWS $78/mo). AWS configs exist but are secondary.
- **Use official modules** — Reference ai-on-gke/ai-on-eks for cluster infra, don't reinvent

## Repository Layout

```
infra/                    # Terraform — cluster provisioning
  modules/                #   EKS, GKE, networking, artifact-store
  clusters/
    training/dev/         #   Training cluster (GPU, all spot, ephemeral)
    inference/dev/        #   Inference + apps cluster (stable, user-facing)

workloads/                # ArgoCD-managed K8s manifests
  argocd/                 #   App-of-apps, projects, per-cluster applications
  training/base/          #   JupyterLab, training jobs, storage
  inference/base/         #   vLLM, RAG, agent, ML, embedding, pgvector, monitoring
  _template/              #   Copy to add any new workload

services/                 # Application source code (Python)
pipelines/                # Pipeline source code (training, ingestion, preprocessing)
docs/                     # Architecture & operations guides
local-dev/                # DGX Spark (K3s), Docker Compose, KinD
.github/workflows/        # CI/CD
```

## Key Rules

1. **Infra and workloads are separate** — `infra/` provisions clusters, `workloads/` deploys apps. Different lifecycles.
2. **Training and inference don't mix** — Different clusters, different node types, different SLOs.
3. **Artifact store bridges clusters** — Training writes to S3/GCS, inference reads. No cross-cluster networking.
4. **No deploying from CI** — CI builds images. ArgoCD handles deployment.
5. **GPU workloads must have KEDA ScaledObjects** — scale-to-zero on inference cluster.
6. **All services expose /health** — for K8s probes.
7. **Environment variables for config** — no hardcoded URLs or credentials.
8. **Terraform changes go through PR** — plan shown in PR comments.
9. **Framework-agnostic** — Don't couple the platform to any specific AI framework.

## When Adding a New Service/Workload

1. Create `services/<name>/` with `app/`, `Dockerfile`, `requirements.txt`
2. Copy `workloads/_template/` to `workloads/inference/base/<name>/` (or `training/`)
3. Fill in deployment.yaml and service.yaml
4. Add to parent `kustomization.yaml`
5. Add to `.github/workflows/ci.yaml` build matrix
6. `git push` → ArgoCD deploys automatically

See [docs/ADDING_A_WORKLOAD.md](docs/ADDING_A_WORKLOAD.md) for full guide.

## When Adding a New Pipeline

1. Create `pipelines/<name>/` with script, `Dockerfile`, `requirements.txt`
2. Add K8s Job manifest to `workloads/training/base/jobs/` (or `inference/base/jobs/`)
3. Add to `.github/workflows/ci.yaml` pipeline build matrix

## Default Models

- **Dev/Test LLM**: `Qwen/Qwen2.5-1.5B-Instruct` (1.5B params, ~3GB VRAM)
- **Embedding**: `sentence-transformers/all-MiniLM-L6-v2` (CPU, ~100MB)
- Configurable via env vars; swap for larger models in production.

## Local Development

- **DGX Spark (128GB)**: K3s or Docker Compose. See `local-dev/dgx-spark/`.
- **Any machine**: KinD (CPU-only). See `local-dev/kind/`.
- Locally, both training and inference workloads run on the same cluster.
