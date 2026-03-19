# Cluster Topology: Two-Cluster Architecture

## Why Two Clusters

Training and inference have fundamentally different failure modes and SLO requirements. Mixing them on a single cluster creates blast radius problems:

- **Training crashes** (OOM kills, NCCL timeouts, spot interruptions, gradient explosions) happen regularly and are expected. They should never take down a production API.
- **Spot instance preemptions** are the norm for cost-effective training. A preempted training node is a retry. A preempted inference node is a user-facing outage.
- **Resource contention** between a 70B parameter fine-tuning job and a latency-sensitive inference endpoint is unresolvable. One wants maximum throughput, the other wants minimum latency.

Different SLOs demand different infrastructure:

| Concern | Training Cluster | Inference Cluster |
|---------|-----------------|-------------------|
| Availability SLO | Best-effort | 99.9% |
| Node lifecycle | Ephemeral, spot-only | On-demand baseline + spot |
| Failure response | Retry from checkpoint | Failover, no downtime |
| Scaling pattern | 0 to N to 0 | Always-on baseline + burst |
| Cost when idle | $0 | Minimal (CPU baseline) |

## Training Cluster

**Purpose:** Run all GPU-intensive, long-running, failure-tolerant workloads.

**Node Types:**
- Large GPU instances (A100 80GB, H100 80GB)
- ALL spot/preemptible instances (60-90% cost savings)
- No on-demand nodes needed since all workloads are retryable

**Workloads:**
- Fine-tuning jobs (LoRA, QLoRA, full fine-tune)
- Pretraining runs (multi-node, multi-GPU)
- Data preprocessing and tokenization
- Evaluation and benchmarking jobs
- JupyterLab for interactive research

**Scaling:**
- Scales from 0 nodes when no jobs are queued
- Kueue or Volcano manages job queuing and priority
- Cluster autoscaler provisions nodes on demand
- Scales back to 0 when all jobs complete
- Cost is literally $0 when idle (no persistent GPU nodes)

**Key Properties:**
- No user-facing traffic
- No uptime guarantees
- Checkpointing is mandatory (spot can interrupt at any time)
- All state is ephemeral except what is written to the artifact store

## Inference + Apps Cluster

**Purpose:** Serve production traffic with high availability. Run all user-facing services, APIs, and supporting infrastructure.

**Node Types:**
- CPU on-demand instances as always-on baseline (API servers, databases, monitoring)
- GPU spot instances for inference workloads (vLLM, embedding models)
- GPU on-demand instances as fallback if spot is unavailable (optional, for strict SLOs)

**Workloads:**
- vLLM inference servers (GPU, spot with on-demand fallback)
- RAG service (CPU or GPU depending on embedding)
- Agent services (CPU, calls vLLM internally)
- ML prediction services (CPU or GPU)
- Embedding service (CPU-optimized models like all-MiniLM-L6-v2)
- pgvector database (CPU, persistent storage)
- Monitoring stack (Grafana, Prometheus, LangFuse)
- ArgoCD (GitOps controller)

**Scaling:**
- CPU nodes: always-on, HPA for pod scaling
- GPU nodes: KEDA-driven, scale from 0 based on request queue depth
- Inference pods: HPA based on GPU utilization or request latency

**SLOs:**
- API availability: 99.9%
- P99 latency: defined per service (e.g., 2s for chat completion, 200ms for embedding)
- Error rate: < 0.1%

## Shared Nothing Except Artifacts

The two clusters share **no network, no storage, no state**. They are completely independent Kubernetes clusters that could be in different regions or even different cloud providers.

The only communication channel is the **artifact store** (S3 or GCS):

- Training cluster **writes** model artifacts, evaluation results, and metadata
- Inference cluster **reads** model artifacts and metadata
- No direct API calls between clusters
- No shared databases
- No shared PVCs or NFS mounts
- No VPC peering required (both just need access to the object store)

This shared-nothing architecture means:
- You can destroy and recreate the training cluster without affecting inference
- You can upgrade Kubernetes versions independently
- A security incident in one cluster does not compromise the other
- You can run them on different cloud providers if needed

## Single Cluster for Dev/Local

On a DGX Spark with K3s, a local Kind cluster, or a small dev environment, running two clusters is overkill. Instead, run everything on **one cluster**.

The `workloads/` directory separation still applies:
- Deploy both `workloads/training/` and `workloads/inference/` to the same cluster
- Use namespaces to separate them (`training` namespace, `inference` namespace)
- Use resource quotas to prevent training from starving inference

This works because:
- Dev traffic is just you, so SLOs don't matter
- A single GPU can time-share between training and inference
- Simpler networking and storage setup

**Promotion path:**
- Dev: single cluster, both workload types
- Staging: two separate clusters (validates the split)
- Production: two separate clusters (enforces isolation)

The workload manifests are identical across environments. Only the cluster target changes.

## Environment Matrix

```
               Training Cluster    Inference Cluster
dev            Optional (shared)   Always
qa             No                  Yes
staging        Yes (separate)      Yes (separate)
prod           Yes (separate)      Yes (separate)
```

**Notes:**
- In dev, training workloads run on the same cluster as inference (single cluster mode)
- QA environments typically don't need training capability (they test inference with pre-built artifacts)
- Staging mirrors production topology to validate the two-cluster split
- Production enforces full isolation with separate clusters, IAM, and networking

## Architecture Diagram

```
TRAINING CLUSTER                ARTIFACT STORE              INFERENCE CLUSTER
┌──────────────┐               ┌──────────────┐           ┌──────────────────┐
│ JupyterLab   │               │  S3 / GCS    │           │ vLLM (GPU)       │
│ Training Jobs│──── write ───>│              │──read ───>│ RAG service      │
│ Eval Jobs    │               │ /models/v1/  │           │ Agent service    │
│ Preprocessing│               │ /models/v2/  │           │ ML service       │
│              │               │ /adapters/   │           │ Embedding (CPU)  │
│ ALL SPOT     │               │ /datasets/   │           │ pgvector         │
│ GPU: A100/H100│              │              │           │ Monitoring       │
│ Ephemeral    │               │ Versioned    │           │ KEDA + ArgoCD    │
└──────────────┘               └──────────────┘           └──────────────────┘
     │                                                          │
     │ Scales 0→N→0                              Always-on CPU baseline
     │ $0 when idle                              GPU spot for inference
     │ Best-effort SLO                           99.9% availability SLO
```

## Interview-Ready Explanation

> "We run two separate Kubernetes clusters: one for training, one for inference. The training cluster is all spot instances that scale to zero when idle, so it costs nothing when we're not training. It's designed to crash -- OOM kills, spot preemptions, NCCL timeouts are all expected and handled via checkpointing and retries. The inference cluster is the opposite: it has an on-demand CPU baseline that's always running, with GPU spot instances scaling via KEDA for inference. It targets 99.9% availability.
>
> The two clusters share nothing except an S3 artifact store. Training writes model artifacts, inference reads them. This means a training crash never affects production, we can upgrade clusters independently, and the blast radius of any failure is contained. For local dev on a DGX Spark, we collapse everything to one cluster -- same workload manifests, just deployed to a single target."
