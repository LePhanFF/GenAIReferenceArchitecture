# Official Cloud AI/K8s Blueprints — Don't Reinvent the Wheel

AWS and GCP both maintain official, battle-tested reference architectures for AI on Kubernetes. Use them for infrastructure, layer your application services on top.

---

## AWS: ai-on-eks

**Repo:** https://github.com/awslabs/ai-on-eks
**Docs:** https://awslabs.github.io/ai-on-eks/

### What They Provide

**18 Inference Blueprints:**
| Blueprint | What It Deploys |
|---|---|
| `vllm-rayserve-gpu` | vLLM + Ray Serve on NVIDIA GPUs |
| `vllm-nvidia-triton-server-gpu` | vLLM behind Triton Server |
| `vllm-ray-gpu-deepseek` | DeepSeek model on vLLM + Ray |
| `vllm-llama3.1-405b-trn1` | Llama 3.1 405B on Trainium |
| `vllm-rayserve-inf2` | vLLM on Inferentia2 (cost-optimized) |
| `nvidia-nim` | NVIDIA NIM (managed inference) |
| `nvidia-nim-operator-llama3-8b` | NIM Operator for Llama 3 |
| `nvidia-dynamo` | NVIDIA Dynamo inference engine |
| `llama2-13b-chat-rayserve-inf2` | Llama 2 13B on Inferentia2 |
| `llama3-8b-instruct-rayserve-inf2` | Llama 3 8B on Inferentia2 |
| `mistral-7b-rayserve-inf2` | Mistral 7B on Inferentia2 |
| `stable-diffusion-rayserve-gpu` | Stable Diffusion on GPU |
| `stable-diffusion-xl-base-rayserve-inf2` | SDXL on Inferentia2 |
| `aibrix` | AIBrix inference platform |
| `nvidia-deep-research` | NVIDIA deep research tooling |
| `gradio-ui` | Gradio UI for model demos |
| `inference-charts` | Helm charts for general inference |

**3 Training Blueprints:**
| Blueprint | What It Deploys |
|---|---|
| `llama-lora-finetuning-trn1` | LoRA fine-tuning on Trainium |
| `raytrain-llama2-pretrain-trn1` | Distributed pretraining with Ray |
| `slinky-slurm` | SLURM integration for HPC training |

**Gateway:**
| Blueprint | What It Deploys |
|---|---|
| `envoy-ai-gateway` | Envoy-based AI gateway with multi-model routing, rate limiting |

**Notebooks:**
| Blueprint | What It Deploys |
|---|---|
| `notebooks/` | JupyterHub on EKS |

### When to Use ai-on-eks
- You need a **production-grade EKS cluster** with GPU support → use their Terraform
- You want **vLLM on Ray Serve** with autoscaling → use their inference blueprints
- You need **Trainium/Inferentia2** support → they're the only source
- You want the **Envoy AI Gateway** → more mature than rolling your own

### When NOT to Use ai-on-eks
- You need **GCP support** → AWS only
- You need **RAG, agent services** → they don't provide application services
- You need **LangChain integration** → not covered
- You need **MLOps tooling** → minimal coverage

---

## GCP: ai-on-gke

**Organization:** https://github.com/ai-on-gke
**Tutorials:** https://github.com/ai-on-gke/tutorials-and-examples

### Key Repositories

| Repo | What It Provides |
|---|---|
| `tutorials-and-examples` | 29 tutorials covering inference, training, RAG, fine-tuning |
| `common-infra` | Shared Terraform modules for GKE AI clusters |
| `nvidia-ai-solutions` | NVIDIA GPU integration on GKE |
| `quick-start-guides` | Terraform quick starts |
| `batch-reference-architecture` | Batch processing patterns |
| `scalability-benchmarks` | Performance testing frameworks |
| `tpu-provisioner` | TPU resource management |

### Notable Tutorials (tutorials-and-examples)

| Tutorial | What It Covers |
|---|---|
| `inference-servers/` | General inference server setup |
| `hugging-face-tgi/` | HuggingFace TGI on GKE |
| `ray-serve/` | Ray Serve inference |
| `finetuning-gemma-3-1b-it-on-l4/` | Fine-tuning Gemma 3 on L4 GPUs |
| `mlflow/finetune-gemma/` | MLflow experiment tracking for fine-tuning |
| `langchain-chatbot/` | LangChain chatbot on GKE |
| `llamaindex/rag/` | LlamaIndex RAG pipeline |
| `agentic-llamaindex/rag/` | Agentic RAG patterns |
| `autoscale/` | GPU autoscaling patterns |
| `blue-green-gateway/` | Blue-green deployment for model serving |
| `lora-inference-gateway/` | LoRA adapter routing |
| `nemo-rl-on-gke/` | NVIDIA NeMo reinforcement learning |
| `flyte/` | Flyte workflow orchestration |
| `metaflow/` | Netflix Metaflow on GKE |
| `skypilot/` | SkyPilot job scheduling |
| `workflow-orchestration/` | Workflow orchestration patterns |
| `security/` | Security configurations |
| `confidential-gke/` | Confidential computing |
| `models-as-oci/` | Packaging models as OCI containers |

### When to Use ai-on-gke
- You need **GKE-specific Terraform** → use `common-infra`
- You want **fine-tuning examples** (Gemma on L4) → their tutorials are excellent
- You need **LangChain/LlamaIndex on GKE** → they have examples
- You want **MLflow integration** → they have a fine-tuning example
- You need **blue-green model deployments** → their gateway tutorial
- You want **TPU support** → GCP-specific

### When NOT to Use ai-on-gke
- You need **AWS support** → GCP only
- You need **end-to-end microservices** → tutorials are isolated, not integrated
- You need **production service code** → tutorials are examples, not production-ready
- You need **auth, SRE, migration docs** → not covered

---

## How Your Repo Complements These

```
OFFICIAL BLUEPRINTS (AWS/GCP)          YOUR REPO
──────────────────────────             ─────────────
Infrastructure Terraform     ←→     Infrastructure Terraform (multi-cloud)
Inference blueprints          →     vLLM deployment (simpler, single pattern)
Training blueprints           →     Unsloth LoRA training
                              ←     RAG service (not in theirs)
                              ←     Agent service (not in theirs)
                              ←     ML service (not in theirs)
                              ←     Embedding service (not in theirs)
                              ←     Scientist workflow docs
                              ←     Auth, SRE, MLOps, migration guides
                              ←     Multi-cloud support
                              ←     DGX Spark local dev
                              ←     Cost optimization (KEDA scale-to-zero)
```

### Recommended Hybrid Approach

1. **For EKS infrastructure**: Consider using `terraform-aws-modules/eks` (the community standard) or reference `ai-on-eks` Terraform patterns. More battle-tested than custom modules.

2. **For GKE infrastructure**: Use `ai-on-gke/common-infra` Terraform modules. They handle NAP, GPU drivers, and Workload Identity correctly.

3. **For inference**: Your vLLM setup is correct and simpler. If you need Ray Serve integration or Triton, pull from `ai-on-eks` blueprints.

4. **For your application layer**: This is your unique value — RAG, agents, ML, embedding, pipelines, docs. Neither cloud provides this.

5. **For interview**: Reference these official repos to show you know the ecosystem. "I use the AWS ai-on-eks blueprints for infrastructure and layer our LangChain services on top."

---

## Other Notable Reference Architectures

| Resource | URL | What It Covers |
|---|---|---|
| AWS Well-Architected GenAI Lens | https://docs.aws.amazon.com/wellarchitected/latest/generative-ai-lens/ | Best practices for GenAI on AWS |
| GCP GenAI Architecture Center | https://cloud.google.com/architecture/ai-ml/generative-ai | GCP GenAI patterns |
| NVIDIA NeMo on K8s | https://github.com/NVIDIA/NeMo | End-to-end LLM training framework |
| Kubeflow | https://github.com/kubeflow/kubeflow | Full ML platform on K8s |
| MLflow | https://github.com/mlflow/mlflow | Experiment tracking + model registry |
| KServe | https://github.com/kserve/kserve | Serverless model serving on K8s |
| LiteLLM | https://github.com/BerriAI/litellm | Multi-LLM gateway with auth |
| Dify | https://github.com/langgenius/dify | LLM app development platform |
| RAGFlow | https://github.com/infiniflow/ragflow | Open-source RAG engine |

---

## Interview-Ready Statement

> "I'm familiar with the official AWS ai-on-eks and GCP ai-on-gke blueprints — they're great for infrastructure and inference patterns. For our platform, I use their Terraform patterns for the EKS/GKE cluster setup and Karpenter/NAP configuration, then layer our application services on top — RAG with LangChain, agents with tool calling, embedding services, and ML classification. The official blueprints don't cover the application layer, authentication, or the scientist-to-production workflow, which is where most of the real platform work lives."
