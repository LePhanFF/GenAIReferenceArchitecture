# GenAI Reference Architecture

Production-ready Generative AI platform on Kubernetes. Multi-cloud (AWS EKS + GCP GKE), GitOps-driven, cost-optimized with scale-to-zero GPU inference.

```
                         +------------------+
                         |   GitHub Repo    |
                         |  (this repo)     |
                         +--------+---------+
                                  |
                         ArgoCD GitOps Sync
                                  |
              +-------------------+-------------------+
              |                                       |
     +--------v--------+                    +---------v-------+
     |    AWS EKS       |                    |    GCP GKE      |
     |  (Terraform)     |                    |  (Terraform)    |
     +--------+---------+                    +---------+-------+
              |                                        |
              +-------------------+--------------------+
                                  |
                    +-------------v--------------+
                    |     Kubernetes Cluster      |
                    |                             |
                    |  +-------+  +-----------+  |
                    |  | KEDA  |  | GPU Oper. |  |
                    |  +---+---+  +-----+-----+  |
                    |      |            |         |
                    +------+------------+---------+
                           |
         +-----------------+------------------+
         |                 |                  |
+--------v---+    +--------v---+    +---------v--+
| Inference  |    |    RAG     |    |   Agent    |
| (vLLM+GPU) |    |  Service   |    |  Service   |
| :8001      |    |  :8000     |    |  :8003     |
+--------+---+    +-----+------+    +------+-----+
         |              |                  |
         |        +-----v------+           |
         |        |  pgvector  |           |
         |        |  :5432     |           |
         |        +-----+------+           |
         |              |                  |
    +----v--------------v------------------v----+
    |              Shared Services               |
    |  +------------+       +-----------+       |
    |  | Embedding  |       |    ML     |       |
    |  | :8002      |       |  :8004    |       |
    |  +------------+       +-----------+       |
    +--------------------------------------------+
```

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Inference | vLLM | OpenAI-compatible LLM serving with GPU |
| RAG | LangChain + pgvector | Retrieval-augmented generation |
| Agent | LangChain/LangGraph | Autonomous AI agents with tools |
| Embedding | sentence-transformers | Text embeddings for RAG |
| ML Service | FastAPI + scikit-learn | Classical ML predictions |
| Vector DB | pgvector (PostgreSQL) | Vector similarity search |
| Orchestration | Kubernetes (EKS/GKE/K3s) | Container orchestration |
| IaC | Terraform | Infrastructure provisioning |
| GitOps | ArgoCD | Declarative continuous delivery |
| Autoscaling | KEDA | Event-driven pod autoscaling |
| GPU | NVIDIA GPU Operator | GPU scheduling in K8s |
| CI/CD | GitHub Actions | Build, lint, test, push images |
| Registry | GitHub Container Registry | Docker image storage |
| Pipelines | Python (Unsloth, LangChain, Pandas) | Training, ingestion, preprocessing |

## Services

| Service | Port | Description |
|---------|------|-------------|
| `inference-service` | 8001 | vLLM serving Qwen2.5-1.5B (or any HF model) |
| `rag-service` | 8000 | RAG queries over ingested documents |
| `agent-service` | 8003 | AI agent with tool use |
| `embedding-service` | 8002 | Text embedding via sentence-transformers |
| `ml-service` | 8004 | Classical ML inference |

## Pipelines

| Pipeline | GPU | Description |
|----------|-----|-------------|
| `rag-ingestion` | No | Ingest documents into pgvector |
| `training` | Yes | Fine-tune with Unsloth + LoRA |
| `preprocessing` | No | Clean and transform raw data |

## Cost Optimization

This architecture is designed for minimal cloud spend:

- **Scale-to-zero GPU**: KEDA scales inference pods to 0 when idle. GPU nodes scale down via Cluster Autoscaler. You pay $0 when nobody is using it.
- **Spot/Preemptible instances**: Training jobs use spot instances (60-90% savings).
- **Right-sized models**: Default to Qwen2.5-1.5B (~3GB VRAM) instead of 70B+ models.
- **Shared embedding**: CPU-based embedding service, no GPU needed.
- **pgvector over managed**: Self-hosted pgvector instead of expensive managed vector DBs.

## Quick Start

### Option 1: Docker Compose (fastest, requires NVIDIA GPU)

```bash
cd local-dev/dgx-spark/
docker compose up -d

# Test inference
curl http://localhost:8001/v1/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "Qwen/Qwen2.5-1.5B-Instruct", "prompt": "Hello", "max_tokens": 50}'
```

### Option 2: K3s on DGX Spark (full K8s, local)

```bash
cd local-dev/dgx-spark/
chmod +x k3s-setup.sh
./k3s-setup.sh

# ArgoCD auto-syncs the stack
kubectl get pods -n genai
```

### Option 3: KinD (CPU-only, any machine)

```bash
cd local-dev/kind/
chmod +x setup.sh
./setup.sh
```

### Option 4: Cloud (AWS EKS or GCP GKE)

```bash
# AWS
cd terraform/aws/
terraform init && terraform apply

# GCP
cd terraform/gcp/
terraform init && terraform apply

# ArgoCD syncs automatically from this repo
```

## Recommended LLMs for Development

| Model | Params | VRAM (4-bit) | Use Case |
|-------|--------|-------------|----------|
| **Qwen2.5-1.5B-Instruct** | 1.5B | ~3 GB | **Default for dev** |
| TinyLlama-1.1B | 1.1B | ~2.5 GB | Absolute minimum |
| Phi-3-mini-4k | 3.8B | ~8 GB | Better quality |
| Qwen2.5-7B-Instruct | 7B | ~5 GB | Near-production quality |
| Llama-3.1-70B | 70B | ~40 GB | Production (DGX Spark can run this) |

## Repository Structure

```
GenAIReferenceArchitecture/
|-- services/                    # FastAPI microservices
|   |-- inference-service/       # vLLM wrapper
|   |-- rag-service/             # RAG with LangChain
|   |-- agent-service/           # AI agent
|   |-- embedding-service/       # Text embeddings
|   |-- ml-service/              # Classical ML
|
|-- pipelines/                   # Data & training pipelines
|   |-- rag-ingestion/           # Document ingestion into pgvector
|   |-- training/                # Fine-tuning (Unsloth + LoRA)
|   |-- preprocessing/           # Data cleaning & transformation
|   |-- k8s-jobs/                # K8s Job manifests for pipelines
|
|-- k8s/                         # Kubernetes manifests
|   |-- base/                    # Base Kustomize layer
|
|-- terraform/                   # Infrastructure as Code
|   |-- aws/                     # EKS + node groups + IAM
|   |-- gcp/                     # GKE + node pools + IAM
|
|-- local-dev/                   # Local development setups
|   |-- dgx-spark/               # DGX Spark: K3s or Docker Compose
|   |-- kind/                    # KinD: CPU-only K8s in Docker
|
|-- .github/workflows/           # CI/CD
|   |-- ci.yaml                  # Lint, test, build, push images
|   |-- terraform-plan.yaml      # Terraform plan on PRs
|
|-- CLAUDE.md                    # Claude Code project instructions
|-- README.md                    # This file
```

## GitOps Flow

```
Developer pushes code
        |
        v
GitHub Actions CI -----> Build & push images to ghcr.io
        |
        v
ArgoCD detects change --> Syncs K8s manifests to cluster
        |
        v
Kubernetes applies -----> Rolling update of services
```

Terraform changes go through a separate PR flow with `terraform plan` shown in PR comments.

## Local Development on DGX Spark

The NVIDIA DGX Spark (Grace Blackwell, 128GB unified memory) can run the entire stack locally including GPU inference. See [local-dev/dgx-spark/README.md](local-dev/dgx-spark/README.md) for the full guide.

Key points:
- K3s gives you real Kubernetes locally
- Docker Compose for quick iteration without K8s overhead
- Qwen2.5-1.5B uses only ~3GB of your 128GB, leaving plenty of headroom
- You can run training, inference, and RAG simultaneously

## Running Pipelines

### Ingest Documents

```bash
# Locally
python pipelines/rag-ingestion/ingest.py --source ./docs --source-type directory

# As K8s Job
kubectl apply -f pipelines/k8s-jobs/rag-ingestion-job.yaml
```

### Fine-Tune a Model

```bash
# Locally (requires GPU)
python pipelines/training/train.py \
  --dataset ./data/train.jsonl \
  --output ./output/adapter \
  --model Qwen/Qwen2.5-1.5B-Instruct

# As K8s Job
kubectl apply -f pipelines/k8s-jobs/training-job.yaml
```

### Preprocess Data

```bash
# Locally
python pipelines/preprocessing/preprocess.py \
  --input ./raw/data.csv \
  --output ./processed/train.jsonl

# As K8s Job
kubectl apply -f pipelines/k8s-jobs/preprocessing-job.yaml
```

## Context

This repository is a reference implementation for a GenAI/MLOps platform, built to demonstrate:
- End-to-end LLM serving with scale-to-zero cost optimization
- RAG pipelines with vector search
- AI agents with tool use
- Fine-tuning with LoRA on consumer/workstation hardware
- Multi-cloud Kubernetes with GitOps
- Production-grade CI/CD for ML systems

Built by someone with 15 years of DevOps/infrastructure experience, demonstrating the intersection of infrastructure engineering and AI/ML operations.
