# GenAI Reference Architecture — Project Instructions

## What This Is

A production-ready GenAI platform on Kubernetes. Multi-cloud (AWS EKS + GCP GKE), GitOps-driven, cost-optimized with scale-to-zero GPU inference.

## Architecture Principles

- **Simple over clever** — straightforward FastAPI services, standard K8s patterns
- **Cost-optimized** — GPU workloads scale to zero when idle, spot instances for training
- **Smallest viable model** — default to Qwen2.5-1.5B-Instruct for dev/test (~3GB VRAM)
- **GitOps** — ArgoCD syncs from this repo, no manual kubectl apply in production
- **Multi-cloud** — Terraform for both AWS EKS and GCP GKE, same K8s manifests

## Tech Stack

- **Services**: Python FastAPI microservices (inference, RAG, agent, embedding, ML)
- **Inference**: vLLM (OpenAI-compatible API)
- **RAG**: LangChain + pgvector
- **Training**: Unsloth + LoRA (Qwen2.5-1.5B default)
- **Infrastructure**: Terraform (AWS EKS, GCP GKE)
- **GitOps**: ArgoCD
- **Autoscaling**: KEDA (event-driven, scale-to-zero)
- **GPU**: NVIDIA GPU Operator
- **CI/CD**: GitHub Actions (lint, test, build, push to ghcr.io)
- **Local dev**: K3s on DGX Spark, Docker Compose, or KinD

## Repository Layout

```
services/           # FastAPI microservices
pipelines/          # Data & training pipelines (ingest, train, preprocess)
k8s/                # Kubernetes manifests (Kustomize)
terraform/          # IaC (aws/, gcp/)
local-dev/          # Local dev setups (dgx-spark/, kind/)
.github/workflows/  # CI/CD
```

## Key Rules

1. **No deploying from CI** — CI builds and pushes images. ArgoCD handles deployment.
2. **GPU workloads must have KEDA ScaledObjects** — everything scales to zero.
3. **All services expose /health** — for K8s liveness/readiness probes.
4. **Environment variables for config** — no hardcoded URLs or credentials.
5. **Secrets via K8s Secrets or external-secrets** — never in code or manifests.
6. **Dockerfiles use multi-stage builds** where possible to keep images small.
7. **Python services use FastAPI** — consistent across all services.
8. **Terraform changes go through PR** — plan shown in PR comments.

## Default Model

- **Dev/Test**: `Qwen/Qwen2.5-1.5B-Instruct` (1.5B params, ~3GB VRAM)
- **Embedding**: `sentence-transformers/all-MiniLM-L6-v2` (CPU, ~100MB)
- These are configurable via environment variables; swap for larger models in production.

## Local Development

- **DGX Spark (128GB)**: Use K3s or Docker Compose. Full GPU support. See `local-dev/dgx-spark/`.
- **Any machine**: Use KinD (CPU-only). See `local-dev/kind/`.

## When Adding a New Service

1. Create `services/<name>/` with `app/`, `Dockerfile`, `requirements.txt`
2. Add K8s manifests in `k8s/base/<name>/` (deployment, service)
3. Add to `k8s/base/kustomization.yaml`
4. Add to `.github/workflows/ci.yaml` build matrix
5. Add to `local-dev/dgx-spark/docker-compose.yaml`

## When Adding a New Pipeline

1. Create `pipelines/<name>/` with script, `Dockerfile`, `requirements.txt`
2. Add K8s Job manifest in `pipelines/k8s-jobs/`
3. Add to `.github/workflows/ci.yaml` pipeline build matrix
