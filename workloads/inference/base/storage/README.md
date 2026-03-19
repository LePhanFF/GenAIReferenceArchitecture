# Storage Architecture

## Local (DGX Spark / K3s — Single Node)

All storage uses K3s `local-path` provisioner, which creates directories on the host.

```
PVC                    Mount Path                  Size    Used By
─────────────────────  ──────────────────────────  ──────  ────────────────────────────
model-cache-pvc        /root/.cache/huggingface    50Gi    vLLM inference pods
training-data-pvc      /data/training              20Gi    Training jobs, preprocessing
checkpoints-pvc        /checkpoints                20Gi    Training jobs
jupyter-notebooks-pvc  /home/jovyan/notebooks      1Gi     JupyterLab
pgvector PVC           /var/lib/postgresql/data     10Gi    pgvector StatefulSet
```

## Cloud (EKS / GKE)

In production, bulk data moves to object storage. PVCs are only for databases.

```
Storage                     What                         Why Not PVC
──────────────────────────  ───────────────────────────  ──────────────────────────────
s3://models/                Model binaries, LoRA         10x cheaper than EBS
                            adapters                     Survives cluster deletion
                                                         Versioned (DVC, git-lfs)

s3://training-data/         Datasets (JSONL, Parquet)    Same as above
                                                         Can mount via S3 CSI driver

s3://checkpoints/           Training checkpoints         Save every N steps
                            (resume on crash)            Survives spot preemption

EBS gp3 PVC                pgvector data                Database needs block storage
                            (persistent disk)            Low-latency random I/O

HuggingFace Hub             Pull models on first run     Models cached locally after
                            via HF_HOME env var          first download
```

### Why Not Just Use PVCs in Cloud?

| Concern | PVC (EBS/PD) | Object Storage (S3/GCS) |
|---------|-------------|------------------------|
| Cost | $0.08/GB/mo (gp3) | $0.023/GB/mo (S3) — **3.5x cheaper** |
| Cluster deletion | **Lost** (unless snapshot) | Survives |
| Versioning | None | Native + DVC |
| Multi-AZ | **No** — tied to single AZ | Yes |
| Multi-cluster | **No** | Yes |
| Access pattern | Random I/O (good for DB) | Sequential read (good for models/data) |

**Rule of thumb:** Databases use PVCs. Everything else uses S3/GCS in production.

### Cloud Migration Path

To migrate from local PVCs to S3:

1. **Model cache:** Add an init container that downloads from S3 to emptyDir, or use the [Mountpoint for S3 CSI driver](https://github.com/awslabs/mountpoint-s3-csi-driver)
2. **Training data:** Use S3 CSI driver to mount as a filesystem, or download in the Job's init container
3. **Checkpoints:** Configure your training script to save directly to S3 (`--output_dir s3://checkpoints/run-001` with s5cmd or boto3)
4. **pgvector:** Keep on EBS PVC — databases need block storage

---

## GPU Sharing Strategies

### 1. Dedicated (Recommended for LLM Inference)

```
┌─────────────────────────────────┐
│           GPU (Full)            │
│  ┌───────────────────────────┐  │
│  │     vLLM Instance         │  │
│  │  - PagedAttention         │  │
│  │  - KV Cache Management    │  │
│  │  - Continuous Batching    │  │
│  └───────────────────────────┘  │
└─────────────────────────────────┘
```

- One vLLM instance per GPU
- vLLM manages VRAM internally (PagedAttention, KV cache)
- Best throughput and latency
- **This is what our reference architecture uses**

### 2. Time-Sharing (Good for Dev/Experimentation)

```
┌─────────────────────────────────┐
│           GPU (Shared)          │
│  ┌──────────┐  ┌──────────┐    │
│  │  Pod A   │  │  Pod B   │    │
│  │ (active) │  │ (waiting)│    │
│  └──────────┘  └──────────┘    │
│         Round-robin             │
└─────────────────────────────────┘
```

- Multiple pods request `nvidia.com/gpu`, K8s schedules them on the same GPU
- Default: only 1 pod gets the GPU at a time (K8s limitation)
- With NVIDIA GPU Operator time-slicing: pods share via round-robin
- Enable: `kubectl patch -n gpu-operator configmap time-slicing-config ...`

### 3. MPS (Multi-Process Service)

```
┌─────────────────────────────────┐
│           GPU (MPS)             │
│  ┌────────┐ ┌────────┐ ┌────┐  │
│  │ Embed  │ │ Class  │ │ ...│  │
│  │ model  │ │ model  │ │    │  │
│  └────────┘ └────────┘ └────┘  │
│    Simultaneous execution       │
└─────────────────────────────────┘
```

- Multiple CUDA processes share one GPU simultaneously
- Good for small models (embedding, classification) that don't fill VRAM
- **Not good for LLM inference** — VRAM contention causes OOM
- Enable via NVIDIA GPU Operator MPS configuration

### 4. MIG (Multi-Instance GPU) — A100/H100 Only

```
┌─────────────────────────────────┐
│         A100 (MIG Enabled)      │
│  ┌────────┐ ┌────────┐ ┌────┐  │
│  │ 3g.40gb│ │ 2g.20gb│ │1g. │  │
│  │ (vLLM) │ │(embed) │ │10gb│  │
│  └────────┘ └────────┘ └────┘  │
│  Hardware-isolated partitions   │
└─────────────────────────────────┘
```

- Hardware-level GPU partitioning into isolated instances
- Each partition has dedicated VRAM, compute, and memory bandwidth
- True isolation (no noisy neighbor)
- **Not available on DGX Spark** (Blackwell doesn't support MIG in Spark config)

### For Your DGX Spark (Single GPU)

```
RECOMMENDED SCHEDULE:
┌──────────────────────────────────────────────┐
│  9am-5pm:  Inference (vLLM serving)          │
│            KEDA keeps vLLM at 1 replica      │
│            Embedding runs on CPU (no GPU)     │
│            JupyterLab runs on CPU             │
│                                              │
│  Night:    Training (fine-tuning job)         │
│            KEDA scales vLLM to 0             │
│            Training job gets full GPU         │
│            Checkpoints saved to PVC           │
│                                              │
│  Idle:     KEDA scales vLLM to 0             │
│            GPU sits idle (saves power)        │
└──────────────────────────────────────────────┘
```

Key points:
- Run inference **OR** training, never both (1 GPU)
- Use KEDA `ScaledObject` to scale vLLM to zero when no HTTP requests arrive
- Embedding service runs on CPU (sentence-transformers are fast on CPU)
- JupyterLab runs on CPU (calls inference via HTTP API)
- Schedule training jobs for off-hours using CronJob or manual trigger
