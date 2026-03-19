# Artifact Pipeline: Model Flow from Training to Production

## What Are Artifacts

Artifacts are the outputs of the training pipeline that the inference pipeline consumes. They are the **only** thing that crosses the boundary between the training cluster and the inference cluster.

**Artifacts include:**
- Model weights (full model checkpoints, safetensors format)
- LoRA adapters (small delta weights, typically 10-100MB)
- Tokenizer configurations (tokenizer.json, special_tokens_map.json)
- Evaluation results (accuracy, latency benchmarks, safety scores)
- Training metrics (loss curves, learning rate schedules)

**NOT artifacts (these stay on the training cluster):**
- Training data and datasets
- Training code and notebooks
- Intermediate checkpoints (only the final/best checkpoint is promoted)
- Training logs (stored in the training cluster's monitoring stack)

## The Flow

```
Scientist trains in JupyterLab (training cluster)
    |
    v
Training Job saves checkpoint to PVC
    |
    v
Evaluation Job validates quality (accuracy, latency, safety)
    |
    v
Publish Job copies artifact to S3/GCS with version tag
    |   s3://genai-artifacts/models/qwen2.5-1.5b-lora-v3/
    v
Inference cluster picks up new version:
  Option A: Update deployment env var MODEL_VERSION=v3, ArgoCD syncs
  Option B: Init container pulls latest from S3 on pod start
  Option C: vLLM --lora-modules flag pointing to S3 path
    |
    v
Canary rollout: 5% --> 25% --> 100% traffic
    |
    v
Monitor in LangFuse + Grafana
```

### Step-by-Step Detail

**1. Training:** A scientist launches a fine-tuning job (via JupyterLab or a scheduled pipeline). The job runs on spot GPU nodes in the training cluster. Checkpoints are saved to a PVC every N steps for fault tolerance.

**2. Checkpointing:** When training completes (or the best checkpoint is identified), the final model is saved to a PVC on the training cluster. This is a local operation, fast and reliable.

**3. Evaluation:** An evaluation job runs automatically (or manually) against the checkpoint. It measures:
- Task accuracy (domain-specific benchmarks)
- Inference latency (tokens/second on target hardware)
- Safety checks (toxicity, hallucination rate)
- Comparison against the current production model

**4. Publishing:** If evaluation passes thresholds, a publish job copies the artifact to the shared S3/GCS bucket with a version tag. It also updates `metadata/versions.json` with the new version's metrics.

**5. Deployment:** The inference cluster picks up the new version through one of three mechanisms:
- **Option A (GitOps):** Update the `MODEL_VERSION` env var in the deployment manifest, push to git, ArgoCD syncs the change. Most controlled, full audit trail.
- **Option B (Init container):** Pods have an init container that checks `metadata/latest.json` and pulls the corresponding model on startup. Requires pod restart to pick up new versions.
- **Option C (vLLM hot-reload):** vLLM supports `--lora-modules` pointing to S3 paths. New adapters can be loaded without pod restart. Best for LoRA adapters.

**6. Canary:** Traffic shifts gradually (5% then 25% then 100%) while monitoring error rates, latency, and quality metrics. Automated rollback if metrics degrade.

**7. Monitoring:** LangFuse tracks LLM-specific metrics (hallucination rate, user feedback, token usage). Grafana tracks infrastructure metrics (latency, throughput, GPU utilization).

## Artifact Store Structure

```
s3://genai-artifacts/
  models/
    qwen2.5-1.5b-base/               # Base model weights
      config.json
      model.safetensors
      tokenizer.json
    qwen2.5-1.5b-lora-v1/            # LoRA adapter v1
      adapter_config.json
      adapter_model.safetensors
    qwen2.5-1.5b-lora-v2/            # LoRA adapter v2 (staging)
      adapter_config.json
      adapter_model.safetensors
    qwen2.5-1.5b-lora-v3/            # LoRA adapter v3 (production)
      adapter_config.json
      adapter_model.safetensors
  embeddings/
    all-MiniLM-L6-v2/                # Embedding model
      config.json
      model.onnx
  evaluations/
    v1-eval-results.json              # Eval metrics for v1
    v2-eval-results.json              # Eval metrics for v2
    v3-eval-results.json              # Eval metrics for v3
  metadata/
    latest.json                       # Points to current production version
    versions.json                     # Version history with metrics
```

### Example: `metadata/latest.json`

```json
{
  "production": {
    "model": "qwen2.5-1.5b-lora-v3",
    "path": "s3://genai-artifacts/models/qwen2.5-1.5b-lora-v3/",
    "promoted_at": "2026-03-15T10:30:00Z",
    "promoted_by": "training-pipeline-run-42"
  },
  "staging": {
    "model": "qwen2.5-1.5b-lora-v4",
    "path": "s3://genai-artifacts/models/qwen2.5-1.5b-lora-v4/",
    "promoted_at": "2026-03-18T08:00:00Z",
    "promoted_by": "training-pipeline-run-55"
  }
}
```

### Example: `metadata/versions.json`

```json
{
  "versions": [
    {
      "version": "v3",
      "path": "s3://genai-artifacts/models/qwen2.5-1.5b-lora-v3/",
      "created_at": "2026-03-15T09:00:00Z",
      "eval_results": "s3://genai-artifacts/evaluations/v3-eval-results.json",
      "metrics": {
        "accuracy": 0.87,
        "latency_p99_ms": 450,
        "safety_score": 0.95
      },
      "status": "production"
    },
    {
      "version": "v2",
      "path": "s3://genai-artifacts/models/qwen2.5-1.5b-lora-v2/",
      "created_at": "2026-03-10T14:00:00Z",
      "metrics": {
        "accuracy": 0.84,
        "latency_p99_ms": 460,
        "safety_score": 0.93
      },
      "status": "retired"
    }
  ]
}
```

## IAM / Access Control

Strict least-privilege access ensures the training cluster cannot interfere with production inference, and the inference cluster cannot write artifacts.

| Principal | Bucket Access | Permissions |
|-----------|--------------|-------------|
| Training cluster service account | `s3://genai-artifacts/*` | Read + Write |
| Inference cluster service account | `s3://genai-artifacts/*` | Read-only |
| CI/CD pipeline | `s3://genai-artifacts/metadata/*` | Read + Write (for promotion) |
| Developers | `s3://genai-artifacts/*` | Read-only (via assume-role) |

**Implementation:**
- On AWS: IRSA (IAM Roles for Service Accounts) with separate IAM roles per cluster
- On GCP: Workload Identity with separate GCP service accounts per cluster
- No cross-cluster network access needed -- both clusters independently access the object store

**Why read-only for inference:**
- Prevents a compromised inference pod from poisoning the model store
- All writes go through the training pipeline, which includes evaluation gates
- Rollback is an update to `metadata/latest.json`, which only CI/CD can write

## Version Management

### Versioning Strategy

Each artifact gets a monotonically increasing version tag (v1, v2, v3...). Versions are immutable once published -- you never overwrite a version, you create a new one.

```
Train v3 --> Evaluate v3 --> Publish v3 --> Promote v3 to staging --> Promote v3 to production
```

### Promotion Flow

1. **Training publishes** a new version to the artifact store (e.g., v4)
2. **Evaluation validates** v4 meets quality thresholds
3. **Promote to staging:** update `metadata/latest.json` staging pointer to v4
4. **Soak in staging:** run for 24-48 hours, monitor metrics
5. **Promote to production:** update `metadata/latest.json` production pointer to v4
6. **Canary rollout:** gradual traffic shift with automated rollback

### Rollback

Rollback is updating `metadata/latest.json` to point to the previous version. Since all versions are immutable and retained in S3, rollback is:

```bash
# Update latest.json to point back to v2
aws s3 cp metadata/latest.json s3://genai-artifacts/metadata/latest.json
# Restart inference pods (or wait for init container to pick up change)
kubectl rollout restart deployment/vllm -n inference
```

Total rollback time: under 5 minutes (dominated by model loading).

### MLflow Integration (Optional)

For teams already using MLflow, the version management can be delegated to MLflow Model Registry:

- Register each artifact as an MLflow model version
- Use MLflow stages: `None` --> `Staging` --> `Production` --> `Archived`
- MLflow provides a UI for comparing versions and promoting
- The artifact store (S3) remains the source of truth for the actual weights

## Interview-Ready Explanation

> "Our artifact pipeline is the bridge between training and inference. When a training job completes, it runs an evaluation suite -- accuracy, latency, safety checks. If it passes, the model artifact gets published to S3 with a version tag. The inference cluster reads from that same S3 bucket, read-only.
>
> Deployment is GitOps: we update a MODEL_VERSION env var in the deployment manifest, push to git, and ArgoCD rolls it out with a canary strategy. For LoRA adapters specifically, vLLM can hot-load them without a pod restart, which gives us sub-minute deployment for adapter swaps.
>
> Rollback is trivial -- we update the version pointer back to the previous version and restart pods. Every version is immutable in S3, so we can always go back. The whole thing is secured with IRSA: the training cluster gets read-write, the inference cluster gets read-only, so a compromised inference pod can't poison the model store."
