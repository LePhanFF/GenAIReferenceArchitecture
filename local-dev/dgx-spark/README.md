# DGX Spark — Complete Deployment Guide

Step-by-step guide to deploy the full GenAI Reference Architecture on your NVIDIA DGX Spark.

## Your Hardware

| Spec | Value |
|------|-------|
| Chip | NVIDIA GB10 (Grace Blackwell) |
| GPU | Blackwell GPU (compute capability 10.0+) |
| Memory | 128GB unified (CPU+GPU shared via NVLink) |
| CPU | ARM Grace (10 cores) |
| Architecture | **aarch64 / ARM64** |
| OS | Ubuntu 22.04 (NVIDIA customized) |
| NVIDIA Drivers | Pre-installed |
| CUDA | Pre-installed |

**IMPORTANT — ARM64:** Your DGX Spark is ARM64, not x86_64. Most Docker images have ARM64 builds, but some don't. This guide accounts for that.

---

## Phase 0: Pre-Flight (on your DGX Spark)

Before anything else, SSH into your DGX Spark and verify the basics.

```bash
# Connect to your DGX Spark
ssh your-user@your-dgx-spark-ip

# Or if you're sitting at it directly, open a terminal
```

### 0.1 Verify GPU and Drivers

```bash
# Check NVIDIA drivers are working
nvidia-smi

# You should see something like:
# NVIDIA GB10   128GB unified memory
# Driver Version: 5xx.xx   CUDA Version: 12.x

# Check architecture (should be aarch64)
uname -m
# Expected: aarch64
```

### 0.2 Verify Docker

```bash
# Check Docker is installed
docker --version

# If not installed:
sudo apt-get update
sudo apt-get install -y docker.io
sudo usermod -aG docker $USER
# Log out and back in for group to take effect
newgrp docker
```

### 0.3 Verify NVIDIA Container Toolkit

```bash
# Check if nvidia runtime is available to Docker
docker info | grep -i nvidia

# Test GPU access in Docker
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi

# If the above fails, install NVIDIA Container Toolkit:
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
    sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# Verify again
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

### 0.4 Install Required Tools

```bash
# Install curl, git, jq if not present
sudo apt-get install -y curl git jq

# Install Helm (K8s package manager)
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Install kubectl (will also come with K3s, but useful standalone)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/arm64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/

# Verify
helm version
kubectl version --client
```

---

## Phase 1: Install K3s (Lightweight Kubernetes)

K3s is a certified Kubernetes distribution. Same API, same kubectl, same YAML as EKS/GKE — just lighter weight. Everything you learn here transfers 1:1 to cloud.

```bash
# Install K3s
# --disable traefik: we'll use nginx ingress or port-forward instead
# K3s auto-detects ARM64
curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik" sh -

# Wait for K3s to start (about 30 seconds)
sleep 30

# Set up kubeconfig for your user (so you don't need sudo for kubectl)
mkdir -p $HOME/.kube
sudo cp /etc/rancher/k3s/k3s.yaml $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config
export KUBECONFIG=$HOME/.kube/config

# Add to your shell profile so it persists
echo 'export KUBECONFIG=$HOME/.kube/config' >> ~/.bashrc

# Verify K3s is running
kubectl get nodes
# NAME          STATUS   ROLES                  AGE   VERSION
# dgx-spark    Ready    control-plane,master   30s   v1.30.x+k3s1

# Check system pods are running
kubectl get pods -A
# You should see coredns, local-path-provisioner, metrics-server, etc.
```

### What just happened?
- K3s installed a single-node Kubernetes cluster on your DGX Spark
- It's running containerd (container runtime), CoreDNS (service discovery), and local-path-provisioner (storage)
- You now have a real K8s cluster — same `kubectl` commands work on EKS/GKE

---

## Phase 2: Configure GPU Access in K3s

K3s needs to know about your GPU. We'll configure the NVIDIA container runtime and install the GPU device plugin.

### 2.1 Configure NVIDIA Runtime for Containerd

```bash
# Configure containerd (K3s's container runtime) to use NVIDIA
sudo nvidia-ctk runtime configure \
    --runtime=containerd \
    --config=/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl

# Restart K3s to pick up the new config
sudo systemctl restart k3s

# Wait for restart
sleep 15
kubectl get nodes
# Should show Ready again
```

### 2.2 Install NVIDIA GPU Operator

The GPU Operator manages GPU driver, device plugin, and monitoring in K8s. Since DGX Spark already has drivers, we disable the driver installer.

```bash
# Add NVIDIA Helm repo
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update

# Install GPU Operator
# driver.enabled=false — DGX Spark already has drivers
# toolkit.enabled=false — we configured containerd manually above
helm install gpu-operator nvidia/gpu-operator \
    --namespace gpu-operator --create-namespace \
    --set driver.enabled=false \
    --set toolkit.enabled=false \
    --wait --timeout 10m

# Wait for GPU operator pods to be ready (takes 2-5 minutes)
echo "Waiting for GPU Operator pods..."
kubectl wait --for=condition=Ready pods --all -n gpu-operator --timeout=300s

# Verify GPU is visible to Kubernetes
kubectl get nodes -o json | jq '.items[].status.capacity["nvidia.com/gpu"]'
# Expected: "1"

# If you see null, the device plugin isn't running yet. Check:
kubectl get pods -n gpu-operator
# All pods should be Running or Completed
```

### 2.3 Test GPU in a Pod

```bash
# Run a test pod that uses the GPU
kubectl run gpu-test --rm -it --restart=Never \
    --image=nvidia/cuda:12.6.0-base-ubuntu22.04 \
    --limits="nvidia.com/gpu=1" \
    -- nvidia-smi

# You should see your GPU info inside the pod
# This confirms K8s can schedule GPU workloads

# If this fails with "0/1 nodes are available: Insufficient nvidia.com/gpu"
# the GPU device plugin isn't ready. Wait a few minutes and retry.
```

---

## Phase 3: Clone the Repo

```bash
# Clone the GenAI Reference Architecture repo
cd ~
git clone https://github.com/LePhanFF/GenAIReferenceArchitecture.git
cd GenAIReferenceArchitecture
```

---

## Phase 4: Deploy the Stack (Manual First, Then GitOps)

We'll deploy manually first so you understand each piece, then set up ArgoCD for GitOps.

### 4.1 Create the Namespace

```bash
kubectl apply -f k8s/base/namespace.yaml
# namespace/genai created

# Verify
kubectl get namespaces
```

### 4.2 Create Secrets

The services need database credentials and optionally a HuggingFace token.

```bash
# pgvector database credentials
kubectl create secret generic pgvector-credentials \
    -n genai \
    --from-literal=POSTGRES_USER=postgres \
    --from-literal=POSTGRES_PASSWORD=postgres \
    --from-literal=POSTGRES_DB=ragdb

# HuggingFace token (for downloading models — get one at https://huggingface.co/settings/tokens)
# This is optional if the model is public (Qwen2.5 is public)
kubectl create secret generic hf-token \
    -n genai \
    --from-literal=HF_TOKEN=your-hf-token-here

# Verify secrets were created
kubectl get secrets -n genai
```

### 4.3 Deploy pgvector (Vector Database)

```bash
# Deploy pgvector StatefulSet and Service
kubectl apply -f k8s/base/pgvector/statefulset.yaml -n genai
kubectl apply -f k8s/base/pgvector/service.yaml -n genai

# Watch it come up (wait for Running + 1/1 Ready)
kubectl get pods -n genai -w
# pgvector-0   1/1   Running   0   30s

# Verify pgvector is working
kubectl exec -n genai pgvector-0 -- psql -U postgres -c "SELECT 1;"
# Should return: 1

# Check the vector extension is installed
kubectl exec -n genai pgvector-0 -- psql -U postgres -d ragdb -c "SELECT extname FROM pg_extension;"
# Should include: vector
```

**What you just learned:** StatefulSets for databases, PersistentVolumeClaims, init containers, K8s Services for internal DNS.

### 4.4 Deploy Embedding Service (CPU only)

```bash
# Build the embedding service image
# ARM64 NOTE: This builds natively on your ARM64 Spark — no cross-compile needed
cd ~/GenAIReferenceArchitecture
docker build -t genai/embedding:dev services/embedding/

# Import the image into K3s (K3s uses containerd, not Docker daemon)
# K3s needs images imported via ctr or loaded directly
docker save genai/embedding:dev | sudo k3s ctr images import -

# Deploy
kubectl apply -f k8s/base/embedding/deployment.yaml -n genai
kubectl apply -f k8s/base/embedding/service.yaml -n genai

# Watch it start (takes ~30s to download the model on first run)
kubectl get pods -n genai -w

# Check logs to see model loading
kubectl logs -n genai -l app=embedding-service -f

# Test the embedding service
kubectl port-forward svc/embedding-service -n genai 8002:8002 &
curl http://localhost:8002/health
# {"status": "healthy"}

curl -X POST http://localhost:8002/embed \
    -H "Content-Type: application/json" \
    -d '{"texts": ["Hello world", "Kubernetes rocks"]}'
# Returns embedding vectors (arrays of floats)

# Kill the port-forward
kill %1
```

**What you just learned:** Building container images, importing into K3s, Deployments, Services, port-forwarding, checking logs.

### 4.5 Deploy vLLM Inference (GPU)

This is the GPU workload — the LLM inference server.

```bash
# Check if vLLM has an ARM64 image
# vLLM official image supports ARM64 as of v0.6+
# If it doesn't work, we'll use Ollama as fallback (see Troubleshooting)

# Deploy vLLM
kubectl apply -f k8s/base/inference/deployment.yaml -n genai
kubectl apply -f k8s/base/inference/service.yaml -n genai

# Watch the pod — it will take 1-3 minutes to:
# 1. Pull the vLLM image (~5GB)
# 2. Download Qwen2.5-1.5B from HuggingFace (~3GB, cached after first run)
# 3. Load model into GPU memory
kubectl get pods -n genai -w

# Watch the logs to see model loading progress
kubectl logs -n genai -l app=inference-service -f
# Look for: "INFO: Started server process"

# If the pod is stuck in Pending with "Insufficient nvidia.com/gpu":
kubectl describe pod -n genai -l app=inference-service
# Check the Events section for scheduling issues

# Test inference
kubectl port-forward svc/inference-service -n genai 8001:8000 &

curl http://localhost:8001/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "messages": [{"role": "user", "content": "What is Kubernetes?"}],
        "max_tokens": 100
    }'

kill %1
```

**What you just learned:** GPU resource requests (`nvidia.com/gpu: 1`), readiness/liveness probes, model loading, OpenAI-compatible API.

### 4.6 Deploy RAG Service

```bash
# Build the image
docker build -t genai/rag-service:dev services/rag-service/
docker save genai/rag-service:dev | sudo k3s ctr images import -

# Deploy the ConfigMap (service URLs) and service
kubectl apply -f k8s/base/rag-service/configmap.yaml -n genai
kubectl apply -f k8s/base/rag-service/deployment.yaml -n genai
kubectl apply -f k8s/base/rag-service/service.yaml -n genai

# Watch it come up
kubectl get pods -n genai -w

# Check logs
kubectl logs -n genai -l app=rag-service -f

# Test
kubectl port-forward svc/rag-service -n genai 8000:8000 &

# Health check
curl http://localhost:8000/health

# Ingest a test document
curl -X POST http://localhost:8000/ingest \
    -H "Content-Type: application/json" \
    -d '{
        "text": "Kubernetes is a container orchestration platform. It manages containerized workloads across a cluster of machines. Key concepts include Pods, Deployments, Services, and ConfigMaps.",
        "metadata": {"source": "test", "topic": "kubernetes"}
    }'

# Query the RAG system
curl -X POST http://localhost:8000/query \
    -H "Content-Type: application/json" \
    -d '{"question": "What is Kubernetes?"}'
# Should return an answer citing the ingested document

kill %1
```

**What you just learned:** ConfigMaps for service configuration, inter-service communication via K8s DNS, RAG pipeline (embed → store → retrieve → generate).

### 4.7 Deploy Agent Service

```bash
docker build -t genai/agent-service:dev services/agent-service/
docker save genai/agent-service:dev | sudo k3s ctr images import -

kubectl apply -f k8s/base/agent-service/deployment.yaml -n genai
kubectl apply -f k8s/base/agent-service/service.yaml -n genai

kubectl get pods -n genai -w
```

### 4.8 Deploy ML Service

```bash
docker build -t genai/ml-service:dev services/ml-service/
docker save genai/ml-service:dev | sudo k3s ctr images import -

kubectl apply -f k8s/base/ml-service/deployment.yaml -n genai
kubectl apply -f k8s/base/ml-service/service.yaml -n genai

kubectl get pods -n genai -w
```

### 4.9 Verify Everything Is Running

```bash
# All pods should be Running
kubectl get pods -n genai
# NAME                                READY   STATUS    RESTARTS   AGE
# pgvector-0                         1/1     Running   0          10m
# embedding-service-xxxx             1/1     Running   0          8m
# inference-service-xxxx             1/1     Running   0          5m
# rag-service-xxxx                   1/1     Running   0          3m
# agent-service-xxxx                 1/1     Running   0          2m
# ml-service-xxxx                    1/1     Running   0          1m

# All services should have ClusterIPs
kubectl get svc -n genai

# Check resource usage
kubectl top pods -n genai
kubectl top nodes
```

---

## Phase 5: Set Up ArgoCD (GitOps)

Now that you've deployed manually and understand each piece, let's set up ArgoCD so changes sync automatically from git.

```bash
# Install ArgoCD
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for ArgoCD to be ready (2-3 minutes)
echo "Waiting for ArgoCD..."
kubectl wait --for=condition=Available deployment/argocd-server -n argocd --timeout=300s

# Get the initial admin password
ARGOCD_PW=$(kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d)
echo "ArgoCD Password: $ARGOCD_PW"
# SAVE THIS PASSWORD

# Access the ArgoCD UI
kubectl port-forward svc/argocd-server -n argocd 8080:443 &
echo "ArgoCD UI: https://localhost:8080"
echo "Username: admin"
echo "Password: $ARGOCD_PW"
# Open in your browser, accept the self-signed cert warning
```

### Create the ArgoCD Application

```bash
# This tells ArgoCD to watch your repo and sync k8s/base/ to the cluster
kubectl apply -f k8s/argocd/application.yaml

# Check sync status
kubectl get applications -n argocd
# NAME          SYNC STATUS   HEALTH STATUS
# genai-stack   Synced        Healthy

# From now on:
# 1. You change YAML in the repo
# 2. Push to GitHub
# 3. ArgoCD detects the change (~3 minutes or click "Refresh" in UI)
# 4. ArgoCD applies the change to your cluster
# No more kubectl apply needed!
```

---

## Phase 6: Install KEDA (Scale-to-Zero)

KEDA lets pods scale to zero when there's no traffic — critical for GPU cost savings in cloud, and good practice to learn locally.

```bash
helm repo add kedacore https://kedacore.github.io/charts
helm repo update

helm install keda kedacore/keda \
    --namespace keda --create-namespace \
    --wait --timeout 5m

# Verify
kubectl get pods -n keda
# keda-operator-xxx         1/1   Running
# keda-metrics-apiserver    1/1   Running

# Apply the KEDA ScaledObject for inference (scale to zero after 5min idle)
kubectl apply -f k8s/base/inference/keda-scaledobject.yaml -n genai

# Check the ScaledObject
kubectl get scaledobjects -n genai
```

---

## Phase 7: Test the Full Stack

### Port-forward all services for testing

```bash
# Run all port-forwards in background
kubectl port-forward svc/inference-service -n genai 8001:8000 &
kubectl port-forward svc/embedding-service -n genai 8002:8002 &
kubectl port-forward svc/rag-service -n genai 8000:8000 &
kubectl port-forward svc/agent-service -n genai 8003:8003 &
kubectl port-forward svc/ml-service -n genai 8004:8004 &

echo "All services available:"
echo "  Inference: http://localhost:8001"
echo "  Embedding: http://localhost:8002"
echo "  RAG:       http://localhost:8000"
echo "  Agent:     http://localhost:8003"
echo "  ML:        http://localhost:8004"
```

### Test 1: LLM Inference

```bash
curl http://localhost:8001/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "Qwen/Qwen2.5-1.5B-Instruct",
        "messages": [{"role": "user", "content": "Explain RAG in 2 sentences"}],
        "max_tokens": 150
    }'
```

### Test 2: Embeddings

```bash
curl -X POST http://localhost:8002/embed \
    -H "Content-Type: application/json" \
    -d '{"texts": ["What is Kubernetes?", "Container orchestration platform"]}'
```

### Test 3: RAG Pipeline (Ingest → Query)

```bash
# Ingest some documents
for doc in \
    "Kubernetes uses pods as the smallest deployable unit. A pod can contain one or more containers." \
    "Services in Kubernetes provide stable network endpoints for pods. ClusterIP is the default type." \
    "KEDA enables event-driven autoscaling in Kubernetes, including scale-to-zero for cost savings." \
    "ArgoCD is a GitOps continuous delivery tool. It syncs Kubernetes manifests from a Git repository." \
    "vLLM serves large language models with high throughput using PagedAttention and continuous batching."; do
    curl -s -X POST http://localhost:8000/ingest \
        -H "Content-Type: application/json" \
        -d "{\"text\": \"$doc\", \"metadata\": {\"source\": \"test\"}}"
    echo " ingested"
done

# Now query
curl -X POST http://localhost:8000/query \
    -H "Content-Type: application/json" \
    -d '{"question": "How does autoscaling work in Kubernetes?"}'

curl -X POST http://localhost:8000/query \
    -H "Content-Type: application/json" \
    -d '{"question": "What is ArgoCD and how does it work?"}'
```

### Test 4: Agent (uses RAG + ML tools)

```bash
curl -X POST http://localhost:8003/chat \
    -H "Content-Type: application/json" \
    -d '{"message": "Search the knowledge base for information about vLLM"}'
```

### Test 5: ML Classification

```bash
curl -X POST http://localhost:8004/classify \
    -H "Content-Type: application/json" \
    -d '{"text": "What was our GPU cost last week?"}'
```

### Clean up port-forwards

```bash
# Kill all background port-forwards
kill $(jobs -p) 2>/dev/null
```

---

## Phase 8: K8s Operations Practice

Now that the stack is running, practice the operations skills you need for the interview.

### View resource usage

```bash
# Pod CPU and memory usage
kubectl top pods -n genai

# Node usage (how much of your 128GB is used)
kubectl top nodes

# Detailed pod resource requests vs actual usage
kubectl describe pod -n genai -l app=inference-service | grep -A 5 "Limits\|Requests"
```

### Scale a deployment

```bash
# Scale RAG service to 3 replicas
kubectl scale deployment rag-service -n genai --replicas=3

# Watch pods scale up
kubectl get pods -n genai -w

# Scale back to 1
kubectl scale deployment rag-service -n genai --replicas=1
```

### Rolling update (zero-downtime deployment)

```bash
# Change the image tag to trigger a rolling update
kubectl set image deployment/rag-service -n genai rag-service=genai/rag-service:v2

# Watch the rollout
kubectl rollout status deployment/rag-service -n genai

# Check rollout history
kubectl rollout history deployment/rag-service -n genai

# Rollback if needed
kubectl rollout undo deployment/rag-service -n genai
```

### Debug a pod

```bash
# Get pod logs
kubectl logs -n genai -l app=rag-service --tail=50

# Exec into a running pod
kubectl exec -it -n genai deploy/rag-service -- /bin/bash

# Inside the pod, test connectivity to other services:
# curl http://inference-service:8000/health
# curl http://embedding-service:8002/health
# curl http://pgvector:5432  (will fail, but proves DNS works)
# exit

# Describe pod (events, scheduling decisions, resource usage)
kubectl describe pod -n genai -l app=inference-service
```

### Run a training job

```bash
# Build the training image
docker build -t genai/training:dev pipelines/training/
docker save genai/training:dev | sudo k3s ctr images import -

# Run as a K8s Job (one-off task)
kubectl apply -f pipelines/k8s-jobs/training-job.yaml -n genai

# Watch the job
kubectl get jobs -n genai
kubectl logs -n genai -l job-name=training-job -f

# Clean up
kubectl delete job training-job -n genai
```

### Run RAG ingestion as a Job

```bash
docker build -t genai/rag-ingestion:dev pipelines/rag-ingestion/
docker save genai/rag-ingestion:dev | sudo k3s ctr images import -

kubectl apply -f pipelines/k8s-jobs/rag-ingestion-job.yaml -n genai
kubectl logs -n genai -l job-name=rag-ingestion-job -f
```

---

## Troubleshooting

### GPU not detected in K3s

```bash
# Check NVIDIA driver on the host
nvidia-smi

# Check the GPU operator pods
kubectl get pods -n gpu-operator
# Look for any CrashLoopBackOff or Error states

# Check device plugin logs
kubectl logs -n gpu-operator -l app=nvidia-device-plugin-daemonset

# Check if GPU is allocated
kubectl describe node $(hostname) | grep -A 10 "Allocated resources"
# Look for nvidia.com/gpu in Capacity and Allocatable

# Nuclear option: restart everything
sudo systemctl restart k3s
kubectl rollout restart daemonset -n gpu-operator --all
```

### vLLM won't start on ARM64

If the standard vLLM image doesn't work on ARM64:

```bash
# Option A: Use Ollama instead (ARM64 native, great for dev)
# Remove the vLLM deployment
kubectl delete deployment inference-service -n genai

# Deploy Ollama
kubectl run ollama -n genai \
    --image=ollama/ollama:latest \
    --limits="nvidia.com/gpu=1" \
    --port=11434 \
    --restart=Always

kubectl expose pod ollama -n genai --port=11434 --name=inference-service
kubectl exec -n genai ollama -- ollama pull qwen2.5:1.5b

# Update other services to use Ollama's API
# Ollama is OpenAI-compatible at /v1/chat/completions

# Option B: Build vLLM from source for ARM64
# This takes 30+ minutes but gives you the official vLLM
docker build -t genai/vllm:arm64 \
    --build-arg BASE_IMAGE=nvidia/cuda:12.6.0-devel-ubuntu22.04 \
    -f - . <<'DOCKERFILE'
FROM nvidia/cuda:12.6.0-devel-ubuntu22.04
RUN apt-get update && apt-get install -y python3-pip git
RUN pip3 install vllm
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]
DOCKERFILE
```

### Pod stuck in Pending

```bash
# Check why
kubectl describe pod <pod-name> -n genai

# Common causes:
# "Insufficient nvidia.com/gpu" — GPU is already in use by another pod
# "Insufficient memory" — increase node memory limits
# "no nodes available" — K3s node isn't Ready (kubectl get nodes)
```

### Service can't connect to another service

```bash
# K8s DNS resolves service-name.namespace.svc.cluster.local
# But within the same namespace, just use the service name

# Test from inside a pod
kubectl exec -it -n genai deploy/rag-service -- \
    curl -s http://embedding-service:8002/health

# If DNS isn't working, check CoreDNS
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns
```

### Out of memory

```bash
# Check what's using memory
kubectl top pods -n genai --sort-by=memory

# The DGX Spark has 128GB — if you're running out:
# 1. You're using too large a model (switch to Qwen2.5-1.5B)
# 2. Too many replicas (scale down)
# 3. Memory leak in a service (restart it)
kubectl rollout restart deployment/<service-name> -n genai
```

### Reset everything and start over

```bash
# Delete all GenAI resources
kubectl delete namespace genai

# Uninstall K3s completely
/usr/local/bin/k3s-uninstall.sh

# Start from Phase 1
```

---

## Quick Reference Card

```bash
# ─── Daily Commands ───────────────────────────────────────
kubectl get pods -n genai              # Check all pods
kubectl top pods -n genai              # Resource usage
kubectl logs -n genai -l app=<name>    # View logs
kubectl describe pod <name> -n genai   # Debug a pod

# ─── Port Forwarding ─────────────────────────────────────
kubectl port-forward svc/inference-service -n genai 8001:8000 &
kubectl port-forward svc/rag-service -n genai 8000:8000 &
kubectl port-forward svc/argocd-server -n argocd 8080:443 &

# ─── Scaling ─────────────────────────────────────────────
kubectl scale deployment/<name> -n genai --replicas=N
kubectl get hpa -n genai               # Check autoscalers

# ─── Updates ─────────────────────────────────────────────
kubectl rollout status deployment/<name> -n genai
kubectl rollout undo deployment/<name> -n genai
kubectl rollout history deployment/<name> -n genai

# ─── Debugging ───────────────────────────────────────────
kubectl exec -it -n genai deploy/<name> -- /bin/bash
kubectl get events -n genai --sort-by=.lastTimestamp
kubectl describe node $(hostname) | grep -A 20 "Allocated"

# ─── ArgoCD ──────────────────────────────────────────────
kubectl get applications -n argocd     # Sync status
# Push to GitHub → ArgoCD auto-syncs → no kubectl needed

# ─── Jobs ────────────────────────────────────────────────
kubectl apply -f pipelines/k8s-jobs/<job>.yaml -n genai
kubectl get jobs -n genai
kubectl logs -n genai -l job-name=<job> -f
```

---

## Memory Budget (128GB Unified)

| Component | Memory | GPU? |
|-----------|--------|------|
| K3s system pods | ~1.5 GB | No |
| GPU Operator | ~500 MB | No |
| ArgoCD | ~500 MB | No |
| KEDA | ~200 MB | No |
| vLLM (Qwen2.5-1.5B FP16) | ~3 GB | Yes |
| Embedding (all-MiniLM-L6-v2) | ~500 MB | No |
| pgvector | ~500 MB | No |
| RAG + Agent + ML services | ~1.5 GB | No |
| **Total** | **~8 GB** | |
| **Remaining** | **~120 GB** | |

You can run the full stack and still have 120GB free for:
- Larger models (7B uses ~5GB, 70B uses ~40GB)
- Training jobs (concurrent with inference)
- Data processing (Pandas/DuckDB in-memory)

---

## What Transfers to Cloud

| Skill | Learned on Spark | Works on EKS/GKE? |
|-------|-----------------|-------------------|
| kubectl commands | Yes | **100% same** |
| YAML manifests | Yes | **100% same** |
| Deployments, Services, ConfigMaps | Yes | **100% same** |
| GPU scheduling (nvidia.com/gpu) | Yes | **100% same** |
| ArgoCD GitOps | Yes | **100% same** |
| KEDA autoscaling | Yes | **100% same** |
| K8s Jobs for pipelines | Yes | **100% same** |
| Rolling updates, rollbacks | Yes | **100% same** |
| Pod debugging (logs, exec, describe) | Yes | **100% same** |
| Kustomize overlays | Yes | **100% same** |
| Node scaling (Karpenter/NAP) | No (single node) | Cloud only |
| Load balancers (ALB/NLB) | No (port-forward) | Cloud only |
| IAM/IRSA/Workload Identity | No | Cloud only |

**Everything in the left column is interview-ready after this guide.**
