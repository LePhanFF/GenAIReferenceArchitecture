# References & Official Documentation

Complete list of technologies, official docs, and industry references used in this architecture.

---

## LLM Inference

### vLLM — High-Throughput LLM Serving
- **Docs:** https://docs.vllm.ai
- **GitHub:** https://github.com/vllm-project/vllm
- **Docker Hub:** https://hub.docker.com/r/vllm/vllm-openai
- **Supported Models:** https://docs.vllm.ai/en/latest/models/supported_models.html
- **OpenAI-Compatible API:** https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html
- **Distributed Inference:** https://docs.vllm.ai/en/latest/serving/distributed_serving.html
- **Why vLLM:** PagedAttention for efficient KV-cache management, continuous batching, OpenAI-compatible API makes it a drop-in replacement

### Alternatives (for local dev / DGX Spark)
- **Ollama:** https://ollama.com/ — Simplest local LLM runner, OpenAI-compatible API
- **llama.cpp:** https://github.com/ggerganov/llama.cpp — CPU/GPU inference with GGUF models
- **HuggingFace TGI:** https://github.com/huggingface/text-generation-inference — HuggingFace's production serving

---

## RAG (Retrieval-Augmented Generation)

### LangChain — LLM Application Framework
- **Docs:** https://python.langchain.com/docs/introduction/
- **GitHub:** https://github.com/langchain-ai/langchain
- **RAG Tutorial:** https://python.langchain.com/docs/tutorials/rag/
- **LCEL (Expression Language):** https://python.langchain.com/docs/concepts/lcel/
- **Agents:** https://python.langchain.com/docs/concepts/agents/
- **Tool Calling:** https://python.langchain.com/docs/concepts/tool_calling/
- **Vector Stores:** https://python.langchain.com/docs/integrations/vectorstores/
- **Document Loaders:** https://python.langchain.com/docs/integrations/document_loaders/
- **Text Splitters:** https://python.langchain.com/docs/concepts/text_splitters/
- **Chat Models:** https://python.langchain.com/docs/integrations/chat/
- **LangChain + pgvector:** https://python.langchain.com/docs/integrations/vectorstores/pgvector/

### LangServe — Deploy Chains as APIs
- **Docs:** https://python.langchain.com/docs/langserve/
- **GitHub:** https://github.com/langchain-ai/langserve

### LangSmith — Observability & Evaluation
- **Docs:** https://docs.smith.langchain.com/
- **Tracing:** https://docs.smith.langchain.com/observability
- **Evaluation:** https://docs.smith.langchain.com/evaluation

### LangGraph — Stateful Agent Workflows
- **Docs:** https://langchain-ai.github.io/langgraph/
- **GitHub:** https://github.com/langchain-ai/langgraph

---

## Vector Database

### pgvector — PostgreSQL Vector Extension
- **GitHub:** https://github.com/pgvector/pgvector
- **Docker:** https://hub.docker.com/r/pgvector/pgvector
- **HNSW Indexing:** https://github.com/pgvector/pgvector#hnsw
- **Performance Tuning:** https://github.com/pgvector/pgvector#query-options
- **Why pgvector:** Runs on standard PostgreSQL (no new database to learn), SQL-native, HNSW indexes for fast similarity search, metadata filtering via standard WHERE clauses

### Alternatives (reference only)
- **Pinecone:** https://www.pinecone.io/ — Managed vector DB, serverless option
- **Weaviate:** https://weaviate.io/ — Open-source, supports hybrid search
- **Milvus:** https://milvus.io/ — Open-source, high-scale vector DB
- **Chroma:** https://www.trychroma.com/ — Lightweight, good for prototyping
- **FAISS:** https://github.com/facebookresearch/faiss — Facebook's similarity search library

---

## Embeddings

### sentence-transformers — Text Embedding Models
- **Docs:** https://www.sbert.net/
- **GitHub:** https://github.com/UKPLab/sentence-transformers
- **all-MiniLM-L6-v2:** https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- **Model Benchmarks (MTEB):** https://huggingface.co/spaces/mteb/leaderboard

### HuggingFace Text Embeddings Inference (TEI)
- **GitHub:** https://github.com/huggingface/text-embeddings-inference
- **Docker:** https://github.com/huggingface/text-embeddings-inference#docker
- **Why TEI:** Production-optimized, batching, OpenAI-compatible API

---

## Machine Learning

### scikit-learn — Classical ML
- **Docs:** https://scikit-learn.org/stable/
- **GitHub:** https://github.com/scikit-learn/scikit-learn
- **Pipelines:** https://scikit-learn.org/stable/modules/compose.html
- **TF-IDF:** https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html
- **RandomForest:** https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.RandomForestClassifier.html
- **IsolationForest:** https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.IsolationForest.html

### Pandas — Data Processing
- **Docs:** https://pandas.pydata.org/docs/
- **GitHub:** https://github.com/pandas-dev/pandas
- **Cheat Sheet:** https://pandas.pydata.org/Pandas_Cheat_Sheet.pdf

### DuckDB — Embedded Analytics
- **Docs:** https://duckdb.org/docs/
- **GitHub:** https://github.com/duckdb/duckdb
- **S3/Parquet:** https://duckdb.org/docs/extensions/httpfs/s3api
- **Python API:** https://duckdb.org/docs/api/python/overview

---

## Fine-Tuning

### Unsloth — Fast LoRA Training
- **Docs:** https://unsloth.ai/
- **GitHub:** https://github.com/unslothai/unsloth
- **Qwen2.5 Example:** https://colab.research.google.com/drive/1mvwsIQWDs2EdZxMQEEMdMGiMPmQiDjEl
- **Why Unsloth:** 2-5x faster training, 70% less memory, supports QLoRA

### LoRA / QLoRA
- **LoRA Paper:** https://arxiv.org/abs/2106.09685
- **QLoRA Paper:** https://arxiv.org/abs/2305.14314
- **PEFT Library:** https://github.com/huggingface/peft
- **Transformers Training:** https://huggingface.co/docs/transformers/training

---

## Kubernetes & Infrastructure

### AWS EKS
- **Docs:** https://docs.aws.amazon.com/eks/latest/userguide/
- **Terraform Module:** https://registry.terraform.io/modules/terraform-aws-modules/eks/aws/latest
- **GitHub:** https://github.com/terraform-aws-modules/terraform-aws-eks
- **EKS Best Practices:** https://aws.github.io/aws-eks-best-practices/
- **GPU Instances:** https://aws.amazon.com/ec2/instance-types/#Accelerated_Computing
- **IRSA (IAM Roles for Service Accounts):** https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-accounts.html
- **EBS CSI Driver:** https://docs.aws.amazon.com/eks/latest/userguide/ebs-csi.html

### GCP GKE
- **Docs:** https://cloud.google.com/kubernetes-engine/docs
- **Terraform Module:** https://registry.terraform.io/modules/terraform-google-modules/kubernetes-engine/google/latest
- **GitHub:** https://github.com/terraform-google-modules/terraform-google-kubernetes-engine
- **GKE GPU Guide:** https://cloud.google.com/kubernetes-engine/docs/how-to/gpus
- **Node Auto-Provisioning (NAP):** https://cloud.google.com/kubernetes-engine/docs/how-to/node-auto-provisioning
- **Workload Identity:** https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity
- **GPU Instance Types:** https://cloud.google.com/compute/docs/gpus

### Karpenter — Node Autoscaling (AWS)
- **Docs:** https://karpenter.sh/
- **GitHub:** https://github.com/kubernetes-sigs/karpenter
- **NodePools:** https://karpenter.sh/docs/concepts/nodepools/
- **GPU Scheduling:** https://karpenter.sh/docs/concepts/scheduling/#acceleratorsgpus
- **Consolidation:** https://karpenter.sh/docs/concepts/disruption/#consolidation
- **Spot Instances:** https://karpenter.sh/docs/concepts/nodepools/#speccapacity-type

### ArgoCD — GitOps
- **Docs:** https://argo-cd.readthedocs.io/
- **GitHub:** https://github.com/argoproj/argo-cd
- **Getting Started:** https://argo-cd.readthedocs.io/en/stable/getting_started/
- **Application CRD:** https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/
- **Auto-Sync:** https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/
- **Self-Heal:** https://argo-cd.readthedocs.io/en/stable/user-guide/auto_sync/#automatic-self-healing

### KEDA — Event-Driven Autoscaling
- **Docs:** https://keda.sh/
- **GitHub:** https://github.com/kedacore/keda
- **HTTP Add-on (scale-to-zero):** https://github.com/kedacore/http-add-on
- **Prometheus Scaler:** https://keda.sh/docs/scalers/prometheus/
- **Cron Scaler:** https://keda.sh/docs/scalers/cron/

### NVIDIA GPU Operator
- **Docs:** https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/index.html
- **GitHub:** https://github.com/NVIDIA/gpu-operator
- **K3s Support:** https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/getting-started.html#rancher-kubernetes-engine-2-and-k3s
- **NVIDIA Device Plugin:** https://github.com/NVIDIA/k8s-device-plugin

### K3s — Lightweight Kubernetes
- **Docs:** https://docs.k3s.io/
- **GitHub:** https://github.com/k3s-io/k3s
- **GPU Support:** https://docs.k3s.io/advanced#nvidia-container-runtime-support
- **Quick Start:** https://docs.k3s.io/quick-start

### Terraform
- **Docs:** https://developer.hashicorp.com/terraform/docs
- **AWS Provider:** https://registry.terraform.io/providers/hashicorp/aws/latest/docs
- **Google Provider:** https://registry.terraform.io/providers/hashicorp/google/latest/docs
- **Best Practices:** https://developer.hashicorp.com/terraform/cloud-docs/recommended-practices

### Kustomize
- **Docs:** https://kustomize.io/
- **GitHub:** https://github.com/kubernetes-sigs/kustomize
- **Examples:** https://github.com/kubernetes-sigs/kustomize/tree/master/examples

---

## Application Framework

### FastAPI
- **Docs:** https://fastapi.tiangolo.com/
- **GitHub:** https://github.com/fastapi/fastapi
- **Async:** https://fastapi.tiangolo.com/async/
- **Deployment:** https://fastapi.tiangolo.com/deployment/docker/

### httpx — Async HTTP Client
- **Docs:** https://www.python-httpx.org/
- **GitHub:** https://github.com/encode/httpx

### Pydantic Settings
- **Docs:** https://docs.pydantic.dev/latest/concepts/pydantic_settings/

---

## CI/CD

### GitHub Actions
- **Docs:** https://docs.github.com/en/actions
- **Container Registry (ghcr.io):** https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry
- **Docker Build/Push:** https://github.com/docker/build-push-action

### Infracost — Cloud Cost Estimates
- **Docs:** https://www.infracost.io/docs/
- **GitHub Actions:** https://github.com/infracost/actions

---

## Models (HuggingFace)

| Model | Link | Use In This Repo |
|---|---|---|
| Qwen2.5-1.5B-Instruct | https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct | Default dev LLM for inference |
| Qwen2.5-7B-Instruct | https://huggingface.co/Qwen/Qwen2.5-7B-Instruct | Higher quality option |
| all-MiniLM-L6-v2 | https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 | Embedding model (CPU) |
| TinyLlama-1.1B-Chat | https://huggingface.co/TinyLlama/TinyLlama-1.1B-Chat-v1.0 | Minimum viable LLM |
| Phi-3-mini-4k-instruct | https://huggingface.co/microsoft/Phi-3-mini-4k-instruct | Better quality small model |
| Llama-3.1-70B-Instruct | https://huggingface.co/meta-llama/Llama-3.1-70B-Instruct | Production-grade (DGX Spark) |

---

## GPU Instance Pricing (as of 2025)

### AWS (us-east-1)
| Instance | GPU | VRAM | On-Demand/hr | Spot/hr | Notes |
|---|---|---|---|---|---|
| g5.xlarge | 1x A10G | 24 GB | $1.006 | ~$0.30 | Best value for dev |
| g6.xlarge | 1x L4 | 24 GB | $0.805 | ~$0.24 | Newer, slightly cheaper |
| p4d.24xlarge | 8x A100 | 320 GB | $32.77 | ~$13 | Production training |

### GCP (us-central1)
| Machine | GPU | VRAM | On-Demand/hr | Spot/hr | Notes |
|---|---|---|---|---|---|
| g2-standard-4 | 1x L4 | 24 GB | $0.76 | ~$0.23 | Best value for dev |
| a2-highgpu-1g | 1x A100 | 40 GB | $3.67 | ~$1.10 | Production inference |
| a3-highgpu-8g | 8x H100 | 640 GB | $31.22 | ~$10 | Production training |

---

## Industry Reference Architectures

These are the patterns this repo implements:

| Resource | What It Covers |
|---|---|
| [AWS GenAI Lens (Well-Architected)](https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/generative-ai-lens.html) | AWS best practices for GenAI workloads |
| [GCP GenAI Architecture Center](https://cloud.google.com/architecture/ai-ml/generative-ai) | Google Cloud GenAI reference patterns |
| [NVIDIA NeMo Framework](https://github.com/NVIDIA/NeMo) | NVIDIA's LLM training on K8s |
| [Ray Serve + vLLM](https://docs.ray.io/en/latest/serve/tutorials/vllm-example.html) | Scalable LLM serving pattern |
| [LangChain RAG from Scratch](https://python.langchain.com/docs/tutorials/rag/) | Official RAG implementation guide |
| [ArgoCD Best Practices](https://argo-cd.readthedocs.io/en/stable/user-guide/best_practices/) | GitOps patterns for K8s |
| [EKS Best Practices Guide](https://aws.github.io/aws-eks-best-practices/) | Production EKS configuration |
| [Karpenter GPU Scheduling](https://karpenter.sh/docs/concepts/scheduling/) | GPU node autoscaling patterns |
| [KEDA Scale-to-Zero](https://keda.sh/docs/concepts/) | Event-driven pod autoscaling |
| [MLOps Maturity Model (Microsoft)](https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/mlops-maturity-model) | MLOps maturity levels (vendor-neutral concepts) |

---

## Similar Open-Source Projects

Projects that implement similar patterns (for additional reference):

| Project | Description | Link |
|---|---|---|
| LocalAI | OpenAI-compatible local inference | https://github.com/mudler/LocalAI |
| OpenLLM | Production LLM serving | https://github.com/bentoml/OpenLLM |
| llm-on-k8s (AWS) | LLMs on EKS examples | https://github.com/aws-samples/llm-gateway |
| langchain-serve | Deploy LangChain on K8s | https://github.com/jina-ai/langchain-serve |
| RAGFlow | Open-source RAG engine | https://github.com/infiniflow/ragflow |
| Dify | LLM app development platform | https://github.com/langgenius/dify |
| Haystack | LLM orchestration framework | https://github.com/deepset-ai/haystack |

---

## DGX Spark

- **Product Page:** https://www.nvidia.com/en-us/products/workstations/dgx-spark/
- **Grace Blackwell Architecture:** https://www.nvidia.com/en-us/data-center/grace-blackwell/
- **Jetson/ARM K8s:** https://docs.nvidia.com/jetson/
- **Unified Memory:** NVLink connects Grace CPU + Blackwell GPU with 128GB shared memory pool

---

*Last updated: 2026-03-18*
