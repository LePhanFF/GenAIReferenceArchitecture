# DGX Spark Local Development Setup

Run the full GenAI Reference Architecture locally on an NVIDIA DGX Spark (Grace Blackwell, 128GB unified memory).

## Hardware

| Spec | Value |
|------|-------|
| GPU | NVIDIA Blackwell (GB10) |
| Memory | 128GB unified (CPU+GPU shared) |
| CPU | ARM Grace (10 cores) |
| Architecture | aarch64 / ARM64 |
| NVLink | CPU-GPU unified memory |

With 128GB unified memory, the DGX Spark can run models that would normally require a multi-GPU setup on discrete GPUs. However, for **stack testing**, use the smallest viable model.

## Recommended LLMs for Local Dev

| Model | Params | VRAM (4-bit) | Quality | Recommendation |
|-------|--------|-------------|---------|----------------|
| **Qwen2.5-1.5B-Instruct** | 1.5B | ~3 GB | Good for testing | **Use this for dev** |
| TinyLlama-1.1B | 1.1B | ~2.5 GB | Minimal | Absolute minimum, lower quality |
| Phi-3-mini-4k | 3.8B | ~8 GB | Better | Good balance if you want better responses |
| Qwen2.5-7B-Instruct | 7B | ~5 GB | Strong | If you need real quality |
| Llama-3.1-70B | 70B | ~40 GB | Excellent | Possible on DGX Spark but overkill for testing |

**Recommendation:** Start with `Qwen/Qwen2.5-1.5B-Instruct`. It loads in seconds, uses minimal memory, and is sufficient to validate the entire RAG/agent/inference pipeline. Upgrade to 7B+ only when testing response quality.

## Option 1: K3s (Lightweight Kubernetes)

Best for testing the full K8s-native stack locally. Matches production closely.

### Install K3s

```bash
# Run the setup script
chmod +x k3s-setup.sh
./k3s-setup.sh
```

The script will:
1. Install K3s (ARM64-compatible)
2. Install NVIDIA GPU Operator (for GPU scheduling in K8s)
3. Install ArgoCD (for GitOps)
4. Install KEDA (for autoscaling)
5. Configure ArgoCD to sync from this repo

### Verify

```bash
# Check K3s
kubectl get nodes
kubectl get pods -A

# Verify GPU is visible
kubectl get nodes -o json | jq '.items[].status.capacity["nvidia.com/gpu"]'

# Check ArgoCD
kubectl get applications -n argocd
```

### Deploy the Stack

ArgoCD will auto-sync from the repo. To manually apply:

```bash
kubectl apply -k k8s/base/
```

### Access Services

```bash
# Port-forward inference
kubectl port-forward svc/inference-service -n genai 8001:8001

# Port-forward RAG
kubectl port-forward svc/rag-service -n genai 8000:8000

# Port-forward ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

## Option 2: Docker Compose (No K8s)

Faster setup, no Kubernetes overhead. Good for quick iteration on services.

```bash
cd local-dev/dgx-spark/
docker compose up -d
```

Services available at:
- Inference (vLLM): http://localhost:8001
- RAG Service: http://localhost:8000
- Agent Service: http://localhost:8003
- Embedding Service: http://localhost:8002
- ML Service: http://localhost:8004
- pgvector: localhost:5432

## Testing the Stack

### Test Inference (vLLM)

```bash
curl http://localhost:8001/v1/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-1.5B-Instruct",
    "prompt": "Explain Kubernetes in one sentence:",
    "max_tokens": 100
  }'
```

### Test Embedding

```bash
curl http://localhost:8002/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Hello world", "Kubernetes is an orchestrator"]}'
```

### Test RAG (after ingesting documents)

```bash
# First, ingest some documents
python pipelines/rag-ingestion/ingest.py \
  --source ./sample-docs/ \
  --source-type directory

# Then query
curl http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What is the architecture of this system?"}'
```

### Test Agent

```bash
curl http://localhost:8003/agent/run \
  -H "Content-Type: application/json" \
  -d '{"input": "Search for information about GPU scheduling in Kubernetes"}'
```

### Run a Training Job Locally

```bash
python pipelines/training/train.py \
  --dataset ./sample-data/train.jsonl \
  --output ./output/adapter \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --epochs 1 \
  --batch-size 2
```

## Networking Notes

- All services communicate via `localhost` in Docker Compose mode
- In K3s mode, services use K8s DNS: `<service>.<namespace>.svc.cluster.local`
- The DGX Spark runs Ubuntu, so all standard Linux networking applies
- No ingress controller needed for local dev — use `kubectl port-forward`

## Memory Budget (128GB)

| Component | Memory |
|-----------|--------|
| K3s system | ~1 GB |
| GPU Operator | ~500 MB |
| ArgoCD | ~500 MB |
| KEDA | ~200 MB |
| vLLM (Qwen2.5-1.5B) | ~3 GB |
| Embedding model | ~500 MB |
| pgvector | ~500 MB |
| RAG + Agent + ML services | ~1.5 GB |
| **Total** | **~8 GB** |

You have over 100GB of headroom. This means you can:
- Run larger models (7B, 13B, even 70B)
- Run multiple model replicas
- Process large datasets in-memory
- Run training jobs concurrently with inference

## Troubleshooting

### GPU Not Detected in K3s
```bash
# Check NVIDIA driver
nvidia-smi

# Reinstall GPU operator
helm upgrade --install gpu-operator nvidia/gpu-operator \
  --namespace gpu-operator --create-namespace \
  --set driver.enabled=false
```

### vLLM Out of Memory
```bash
# Reduce model size or use quantization
# In docker-compose.yaml or deployment, set:
#   --max-model-len 1024
#   --gpu-memory-utilization 0.8
```

### K3s Won't Start
```bash
# Check logs
journalctl -u k3s -f

# Reset and reinstall
/usr/local/bin/k3s-uninstall.sh
./k3s-setup.sh
```
