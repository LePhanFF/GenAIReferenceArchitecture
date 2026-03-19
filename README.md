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

This architecture is designed for **minimum possible cloud spend**:

### Monthly Idle Cost Comparison

| | GCP (recommended for dev) | AWS |
|---|---|---|
| Control plane | **$0** (free zonal cluster) | $73 (EKS) |
| CPU node (1x spot) | ~$5 (e2-small spot) | ~$5 (t3.small spot) |
| NAT | ~$1 (Cloud NAT) | **$0** (skipped, public subnets) |
| GPU (idle) | **$0** (scale-to-zero) | **$0** (scale-to-zero) |
| **Total idle** | **~$6/mo** | **~$78/mo** |

### GPU Cost When Running

| Cloud | Instance | GPU | Spot Price | On-Demand | Savings |
|---|---|---|---|---|---|
| GCP | g2-standard-4 | 1x L4 24GB | **$0.23/hr** | $0.76/hr | 70% |
| AWS | g6.xlarge | 1x L4 24GB | **$0.24/hr** | $0.80/hr | 70% |
| AWS | g5.xlarge | 1x A10G 24GB | **$0.30/hr** | $1.01/hr | 70% |

### Cost Strategies Used
- **Scale-to-zero GPU**: KEDA scales inference pods to 0 → GPU nodes drain via Karpenter/NAP → $0 GPU cost when idle
- **ALL spot instances**: CPU and GPU nodes use spot/preemptible (60-91% savings)
- **Free GKE control plane**: Zonal cluster (first one free per GCP project)
- **No NAT gateway on AWS**: Dev uses public subnets (saves $32/mo)
- **Smallest viable model**: Qwen2.5-1.5B (~3GB VRAM) instead of 70B+
- **CPU-only embedding**: all-MiniLM-L6-v2 runs on CPU (no GPU needed)
- **Self-hosted pgvector**: Free, vs Pinecone ($70+/mo)

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
# GCP inference cluster (recommended — $6/mo idle)
cd infra/clusters/inference/dev/gcp/
terraform init && terraform apply

# GCP training cluster (separate, all spot)
cd infra/clusters/training/dev/gcp/
terraform init && terraform apply

# AWS inference cluster ($78/mo idle)
cd infra/clusters/inference/dev/aws/
terraform init && terraform apply

# ArgoCD syncs workloads automatically from this repo
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
|
|-- infra/                         # Terraform — cluster provisioning
|   |-- modules/                   #   Reusable modules (EKS, GKE, networking, artifact-store)
|   |-- clusters/
|       |-- training/              #   GPU-heavy, all spot, ephemeral (training + eval)
|       |   |-- dev/aws/  dev/gcp/
|       |-- inference/             #   Serving + apps, stable baseline, user-facing
|           |-- dev/aws/  dev/gcp/
|           |-- qa/  staging/  prod/   (future)
|
|-- workloads/                     # ArgoCD-managed K8s manifests (framework-agnostic)
|   |-- argocd/                    #   App-of-apps, projects, per-cluster applications
|   |-- training/                  #   Workloads for training cluster
|   |   |-- base/                  #     JupyterLab, training jobs, storage PVCs
|   |   |-- overlays/dev/
|   |-- inference/                 #   Workloads for inference + apps cluster
|   |   |-- base/                  #     vLLM, RAG, agent, ML, embedding, pgvector, monitoring
|   |   |-- overlays/dev/
|   |-- _template/                 #   Copy to add any new workload (framework-agnostic)
|
|-- services/                      # Application source code (Python FastAPI)
|   |-- rag-service/               #   LangChain RAG (or swap for LlamaIndex, etc.)
|   |-- agent-service/             #   LangChain agent (or swap for CrewAI, etc.)
|   |-- ml-service/                #   scikit-learn classification + anomaly detection
|   |-- embedding/                 #   sentence-transformers (CPU)
|   |-- inference/                 #   vLLM config (no custom code)
|
|-- pipelines/                     # Pipeline source code (Dockerfiles + scripts)
|   |-- training/                  #   Unsloth LoRA fine-tuning
|   |-- rag-ingestion/             #   Document ingestion into pgvector
|   |-- preprocessing/             #   Pandas data cleaning
|
|-- docs/                          # Architecture & operations guides
|-- local-dev/                     # DGX Spark (K3s) + Docker Compose + KinD
|-- .github/workflows/             # CI/CD (build images, terraform plan)
```

### Two-Cluster Architecture

Training and inference are **separate clusters** — a training crash never affects production.
They share nothing except the **artifact store** (S3/GCS).

```
TRAINING CLUSTER ──write──→ ARTIFACT STORE ──read──→ INFERENCE CLUSTER
(GPU, spot, ephemeral)     (S3/GCS, versioned)     (GPU+CPU, stable, user-facing)
```

See [docs/CLUSTER_TOPOLOGY.md](docs/CLUSTER_TOPOLOGY.md) and [docs/ARTIFACT_PIPELINE.md](docs/ARTIFACT_PIPELINE.md).

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

## Official Documentation & References

See [REFERENCES.md](REFERENCES.md) for the complete list. Key links:

### Core Technologies
| Technology | Docs | GitHub |
|---|---|---|
| vLLM | [docs.vllm.ai](https://docs.vllm.ai) | [vllm-project/vllm](https://github.com/vllm-project/vllm) |
| LangChain | [python.langchain.com](https://python.langchain.com/docs/introduction/) | [langchain-ai/langchain](https://github.com/langchain-ai/langchain) |
| LangServe | [langchain.com/langserve](https://python.langchain.com/docs/langserve/) | [langchain-ai/langserve](https://github.com/langchain-ai/langserve) |
| LangSmith | [smith.langchain.com](https://docs.smith.langchain.com/) | — |
| pgvector | — | [pgvector/pgvector](https://github.com/pgvector/pgvector) |
| Unsloth | [unsloth.ai](https://unsloth.ai/) | [unslothai/unsloth](https://github.com/unslothai/unsloth) |
| sentence-transformers | [sbert.net](https://www.sbert.net/) | [UKPLab/sentence-transformers](https://github.com/UKPLab/sentence-transformers) |
| FastAPI | [fastapi.tiangolo.com](https://fastapi.tiangolo.com/) | [fastapi/fastapi](https://github.com/fastapi/fastapi) |
| scikit-learn | [scikit-learn.org](https://scikit-learn.org/stable/) | [scikit-learn/scikit-learn](https://github.com/scikit-learn/scikit-learn) |

### Infrastructure
| Technology | Docs | GitHub |
|---|---|---|
| Terraform AWS EKS | [registry.terraform.io/modules/terraform-aws-modules/eks](https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest) | [terraform-aws-modules/terraform-aws-eks](https://github.com/terraform-aws-modules/terraform-aws-eks) |
| Terraform GCP GKE | [registry.terraform.io/modules/terraform-google-modules/kubernetes-engine](https://registry.terraform.io/modules/terraform-google-modules/kubernetes-engine/google/latest) | [terraform-google-modules/terraform-google-kubernetes-engine](https://github.com/terraform-google-modules/terraform-google-kubernetes-engine) |
| Karpenter | [karpenter.sh](https://karpenter.sh/) | [kubernetes-sigs/karpenter](https://github.com/kubernetes-sigs/karpenter) |
| ArgoCD | [argo-cd.readthedocs.io](https://argo-cd.readthedocs.io/) | [argoproj/argo-cd](https://github.com/argoproj/argo-cd) |
| KEDA | [keda.sh](https://keda.sh/) | [kedacore/keda](https://github.com/kedacore/keda) |
| NVIDIA GPU Operator | [docs.nvidia.com/datacenter/cloud-native/gpu-operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/index.html) | [NVIDIA/gpu-operator](https://github.com/NVIDIA/gpu-operator) |
| K3s | [k3s.io](https://k3s.io/) | [k3s-io/k3s](https://github.com/k3s-io/k3s) |
| Kustomize | [kustomize.io](https://kustomize.io/) | [kubernetes-sigs/kustomize](https://github.com/kubernetes-sigs/kustomize) |

### Models Used
| Model | HuggingFace | Params | Purpose |
|---|---|---|---|
| Qwen2.5-1.5B-Instruct | [Qwen/Qwen2.5-1.5B-Instruct](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct) | 1.5B | Default dev LLM |
| all-MiniLM-L6-v2 | [sentence-transformers/all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | 22M | Embedding model |
| TinyLlama-1.1B | [TinyLlama/TinyLlama-1.1B-Chat-v1.0](https://huggingface.co/TinyLlama/TinyLlama-1.1B-Chat-v1.0) | 1.1B | Minimum viable LLM |
| Phi-3-mini-4k | [microsoft/Phi-3-mini-4k-instruct](https://huggingface.co/microsoft/Phi-3-mini-4k-instruct) | 3.8B | Better quality option |

### Industry Reference Architectures
| Resource | Description |
|---|---|
| [AWS GenAI Lens](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html) | AWS Well-Architected Framework for GenAI |
| [GCP GenAI Architecture](https://cloud.google.com/architecture/ai-ml/generative-ai) | Google Cloud GenAI reference patterns |
| [NVIDIA NeMo on K8s](https://github.com/NVIDIA/NeMo) | NVIDIA's LLM training framework |
| [Ray Serve LLM](https://docs.ray.io/en/latest/serve/tutorials/vllm-example.html) | Ray + vLLM serving pattern |
| [LangChain RAG Tutorial](https://python.langchain.com/docs/tutorials/rag/) | Official LangChain RAG guide |
| [Karpenter GPU Best Practices](https://karpenter.sh/docs/concepts/nodepools/) | GPU NodePool configuration |
| [KEDA HTTP Scaler](https://keda.sh/docs/scalers/http/) | Scale-to-zero for HTTP workloads |
