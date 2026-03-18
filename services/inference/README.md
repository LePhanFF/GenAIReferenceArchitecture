# Inference Service (vLLM)

No custom application code needed. vLLM is deployed directly as a container.

## Production Deployment (EKS/GKE with GPU)

Deploy vLLM with Qwen2.5-1.5B-Instruct using the official container image:

```yaml
# K8s Deployment container spec
containers:
  - name: vllm
    image: vllm/vllm-openai:v0.6.6
    args:
      - "--model"
      - "Qwen/Qwen2.5-1.5B-Instruct"
      - "--host"
      - "0.0.0.0"
      - "--port"
      - "8000"
      - "--max-model-len"
      - "4096"
      - "--dtype"
      - "float16"
      - "--gpu-memory-utilization"
      - "0.90"
      - "--enforce-eager"
    ports:
      - containerPort: 8000
    resources:
      limits:
        nvidia.com/gpu: 1
        memory: "8Gi"
      requests:
        nvidia.com/gpu: 1
        memory: "4Gi"
    readinessProbe:
      httpGet:
        path: /health
        port: 8000
      initialDelaySeconds: 30
      periodSeconds: 10
    livenessProbe:
      httpGet:
        path: /health
        port: 8000
      initialDelaySeconds: 60
      periodSeconds: 30
```

## Docker Run (for local testing with GPU)

```bash
docker run --gpus all -p 8000:8000 \
  vllm/vllm-openai:v0.6.6 \
  --model Qwen/Qwen2.5-1.5B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 4096 \
  --dtype float16 \
  --gpu-memory-utilization 0.90
```

## DGX Spark / Local Dev (no datacenter GPU)

For development on DGX Spark or machines without datacenter GPUs,
use Ollama or llama.cpp instead of vLLM:

### Option A: Ollama

```bash
# Install and run
ollama serve &
ollama pull qwen2.5:1.5b

# Ollama exposes an OpenAI-compatible API at localhost:11434/v1
# Set VLLM_BASE_URL=http://localhost:11434/v1 in other services
```

### Option B: llama.cpp (server mode)

```bash
# Download GGUF model
wget https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf

# Run llama.cpp server (OpenAI-compatible)
./llama-server \
  -m qwen2.5-1.5b-instruct-q4_k_m.gguf \
  --host 0.0.0.0 \
  --port 8000 \
  -c 4096 \
  -ngl 99
```

## API Endpoints (OpenAI-compatible)

All options above expose the same OpenAI-compatible API:

```
POST /v1/chat/completions   # Chat completion
POST /v1/completions         # Text completion
GET  /v1/models              # List models
GET  /health                 # Health check
```

## Testing the Endpoint

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Qwen/Qwen2.5-1.5B-Instruct",
    "messages": [{"role": "user", "content": "Hello!"}],
    "max_tokens": 128,
    "temperature": 0.1
  }'
```

## Resource Requirements

| Model | VRAM | RAM | Disk |
|-------|------|-----|------|
| Qwen2.5-1.5B (FP16) | ~3 GB | 4 GB | 3 GB |
| Qwen2.5-1.5B (Q4_K_M) | ~1.2 GB | 2 GB | 1 GB |

Qwen2.5-1.5B is intentionally the smallest viable model for this
reference architecture, keeping GPU costs low while demonstrating
the full platform patterns.
