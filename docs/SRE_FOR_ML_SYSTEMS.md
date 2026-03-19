# SRE for ML/GenAI Systems

## 1. How ML SRE Differs from Traditional SRE

| Dimension | Traditional SRE | ML/GenAI SRE |
|-----------|----------------|--------------|
| **Failure mode** | Binary: up or down | Spectrum: model silently returns bad answers |
| **Degradation** | Latency increases, errors spike | Quality degrades with no error signal |
| **Root cause** | Code bug, infra failure | Data drift, model staleness, GPU memory fragmentation, tokenizer mismatch |
| **Rollback** | Deploy previous container image | Rollback model artifact + serving config + feature pipeline |
| **Hardware** | Commodity (CPU/memory) | Scarce GPUs with unique failure modes (ECC errors, NVLink failures, thermal throttling) |
| **Cost** | $0.01-0.10/hour per pod | $3-30/hour per GPU pod |
| **Scaling** | Add pods in seconds | GPU provisioning takes minutes, model loading takes minutes more |
| **Blast radius** | One pod dies, others handle traffic | GPU OOM kills ALL concurrent requests on that GPU |

Key insight: you can have 100% uptime and 0% errors while your model is returning garbage. Traditional monitoring won't catch it. You need **quality SLOs**.

---

## 2. SLOs for ML Systems

### SLO Table

| SLO Category | Metric | Target | How to Measure | Why It Matters |
|-------------|--------|--------|---------------|----------------|
| **Availability** | Inference endpoint up | 99.9% | Synthetic probes every 30s | Basic — is it responding? |
| **Latency (P50)** | Time to first token | < 500ms | Histogram from gateway | UX for streaming |
| **Latency (P99)** | Total response time | < 10s | Histogram from gateway | Tail latency kills UX |
| **Throughput** | Tokens per second per GPU | > 30 tok/s | vLLM metrics | Capacity indicator |
| **Quality** | LLM-as-judge score on canary prompts | > 4.0/5.0 | Scheduled eval job | Catches model degradation |
| **Freshness** | Time since last model update | < 7 days | Model registry metadata | Prevents stale models |
| **Stale-Model Exposure** | % traffic hitting stale model | < 5% | Canary deployment metrics | During rollouts |
| **Error Rate** | Non-2xx responses | < 0.1% | Gateway logs | Catches OOM, timeouts |
| **GPU Utilization** | GPU compute % during inference | 60-85% | DCGM exporter | Under = waste, Over = risk |

### PromQL Queries

```promql
# Availability: inference endpoint success rate (5m window)
1 - (
  sum(rate(http_requests_total{service="vllm", status=~"5.."}[5m]))
  /
  sum(rate(http_requests_total{service="vllm"}[5m]))
)

# P99 Latency: time to complete response
histogram_quantile(0.99,
  sum(rate(http_request_duration_seconds_bucket{service="vllm"}[5m])) by (le)
)

# Throughput: tokens per second across all GPUs
sum(rate(vllm:num_generation_tokens_total[5m]))

# GPU Utilization
avg(DCGM_FI_DEV_GPU_UTIL{namespace="ai-platform"})

# Token throughput per GPU (efficiency)
sum(rate(vllm:num_generation_tokens_total[5m])) by (pod)
/
count(DCGM_FI_DEV_GPU_UTIL{namespace="ai-platform"}) by (pod)

# Error budget burn rate (multi-window)
# Fast burn: 14.4x budget consumption over 1h (pages)
(
  1 - sum(rate(http_requests_total{service="vllm", status=~"2.."}[1h]))
      / sum(rate(http_requests_total{service="vllm"}[1h]))
) > (14.4 * 0.001)  # 14.4x of 0.1% error budget

# Model quality score from eval job (pushed as gauge)
ml_model_quality_score{model="llama-3-70b", eval_type="canary"}
```

---

## 3. Model Rollback Strategies

### Strategy 1: Kubernetes Rollout Undo

Fastest. Rolls back the entire pod spec including the model image/volume.

```bash
# See rollout history
kubectl rollout history deployment/vllm-70b -n ai-platform

# Rollback to previous revision
kubectl rollout undo deployment/vllm-70b -n ai-platform

# Rollback to specific revision
kubectl rollout undo deployment/vllm-70b -n ai-platform --to-revision=3

# Watch rollback progress
kubectl rollout status deployment/vllm-70b -n ai-platform --timeout=600s
```

Limitation: model loading takes 2-10 minutes depending on size. Not instant.

### Strategy 2: MLflow Registry Revert

When models are loaded from a registry (S3/MLflow), change the serving pointer:

```bash
# MLflow: transition previous version back to Production
mlflow models transition-stage \
  --name llama-3-70b-finetuned \
  --version 5 \
  --stage Production

# Archive the bad version
mlflow models transition-stage \
  --name llama-3-70b-finetuned \
  --version 6 \
  --stage Archived

# If using vLLM with model path from ConfigMap:
kubectl patch configmap vllm-config -n ai-platform \
  --type merge \
  -p '{"data":{"MODEL_PATH":"s3://models/llama-3-70b/v5/"}}'

# Restart pods to pick up new model
kubectl rollout restart deployment/vllm-70b -n ai-platform
```

### Strategy 3: KServe Canary Weight Shift

If using KServe, shift traffic instantly without reloading:

```yaml
# Shift 100% traffic to the previous (stable) model
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-3-70b
  namespace: ai-platform
spec:
  predictor:
    model:
      modelFormat:
        name: vLLM
      storageUri: s3://models/llama-3-70b/v5  # Known good version
    canaryTrafficPercent: 0  # 0% to canary = 100% to default
```

```bash
kubectl apply -f inferenceservice-rollback.yaml
```

### Strategy 4: Safe Mode Fallback

When you can't trust any fine-tuned model, fall back to the base model:

```python
# In your API gateway or LiteLLM config
SAFE_MODE = os.getenv("SAFE_MODE", "false") == "true"

async def route_inference(request):
    if SAFE_MODE:
        # Route to base model (always available, known behavior)
        return await call_model("llama-3-70b-base", request)
    else:
        return await call_model("llama-3-70b-finetuned", request)
```

```bash
# Enable safe mode instantly via ConfigMap
kubectl patch configmap api-config -n ai-platform \
  --type merge -p '{"data":{"SAFE_MODE":"true"}}'

# Pods pick up via volume mount (no restart needed if using inotify)
```

### Strategy 5: Automated Rollback via Prometheus Alert

```yaml
# prometheus/rules/model-quality.yaml
groups:
  - name: model-quality
    rules:
      - alert: ModelQualityDegraded
        expr: |
          ml_model_quality_score{eval_type="canary"} < 3.5
        for: 10m
        labels:
          severity: critical
          team: ml-platform
        annotations:
          summary: "Model quality dropped below threshold"
          runbook: "https://runbooks.internal/model-rollback"

      - alert: InferenceLatencySpike
        expr: |
          histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{service="vllm"}[5m])) by (le)) > 15
        for: 5m
        labels:
          severity: warning
```

Alertmanager webhook triggers rollback:

```python
# rollback-controller/main.py (runs as K8s deployment)
from fastapi import FastAPI
from kubernetes import client, config
import logging

app = FastAPI()
config.load_incluster_config()
apps_v1 = client.AppsV1Api()

@app.post("/webhook/alertmanager")
async def handle_alert(payload: dict):
    for alert in payload.get("alerts", []):
        if alert["labels"].get("alertname") == "ModelQualityDegraded":
            if alert["status"] == "firing":
                logging.warning("Model quality degraded — triggering rollback")

                # Rollback to previous revision
                apps_v1.patch_namespaced_deployment(
                    name="vllm-70b",
                    namespace="ai-platform",
                    body={
                        "spec": {
                            "template": {
                                "metadata": {
                                    "annotations": {
                                        "rollback-trigger": alert["startsAt"]
                                    }
                                }
                            }
                        }
                    }
                )

                # OR: enable safe mode
                core_v1 = client.CoreV1Api()
                core_v1.patch_namespaced_config_map(
                    name="api-config",
                    namespace="ai-platform",
                    body={"data": {"SAFE_MODE": "true"}}
                )

    return {"status": "ok"}
```

---

## 4. GPU Failure Handling

### NVIDIA DCGM Health Metrics

Deploy the DCGM exporter to expose GPU health:

```yaml
# k8s/dcgm-exporter.yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: dcgm-exporter
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: dcgm-exporter
  template:
    metadata:
      labels:
        app: dcgm-exporter
    spec:
      containers:
        - name: dcgm-exporter
          image: nvcr.io/nvidia/k8s/dcgm-exporter:3.3.0-3.4.1-ubuntu22.04
          ports:
            - containerPort: 9400
              name: metrics
          securityContext:
            privileged: true
          volumeMounts:
            - name: dcgm-counters
              mountPath: /etc/dcgm-exporter/
          env:
            - name: DCGM_EXPORTER_LISTEN
              value: ":9400"
            - name: DCGM_EXPORTER_KUBERNETES
              value: "true"
      volumes:
        - name: dcgm-counters
          configMap:
            name: dcgm-counters
      tolerations:
        - key: nvidia.com/gpu
          operator: Exists
          effect: NoSchedule
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: dcgm-counters
  namespace: monitoring
data:
  counters.csv: |
    DCGM_FI_DEV_GPU_UTIL, gauge, GPU utilization
    DCGM_FI_DEV_MEM_COPY_UTIL, gauge, Memory utilization
    DCGM_FI_DEV_GPU_TEMP, gauge, GPU temperature
    DCGM_FI_DEV_POWER_USAGE, gauge, Power usage
    DCGM_FI_DEV_ECC_SBE_VOL_TOTAL, counter, Single-bit ECC errors
    DCGM_FI_DEV_ECC_DBE_VOL_TOTAL, counter, Double-bit ECC errors
    DCGM_FI_DEV_XID_ERRORS, gauge, XID errors
    DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL, counter, NVLink errors
    DCGM_FI_DEV_RETIRED_SBE, counter, Retired pages (single-bit)
    DCGM_FI_DEV_RETIRED_DBE, counter, Retired pages (double-bit)
```

### Key GPU Failure Prometheus Alerts

```yaml
# prometheus/rules/gpu-health.yaml
groups:
  - name: gpu-health
    rules:
      # Double-bit ECC error = GPU is unreliable, drain the node
      - alert: GPUDoubleBitECCError
        expr: DCGM_FI_DEV_ECC_DBE_VOL_TOTAL > 0
        for: 0m  # Immediate
        labels:
          severity: critical
        annotations:
          summary: "GPU {{ $labels.gpu }} on {{ $labels.node }} has double-bit ECC errors"
          action: "Drain node and replace GPU"

      # XID 79 = GPU fell off the bus
      - alert: GPUFellOffBus
        expr: DCGM_FI_DEV_XID_ERRORS == 79
        labels:
          severity: critical
        annotations:
          summary: "GPU {{ $labels.gpu }} XID 79 — GPU fell off bus on {{ $labels.node }}"

      # Thermal throttling
      - alert: GPUThermalThrottle
        expr: DCGM_FI_DEV_GPU_TEMP > 85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GPU temp {{ $value }}C on {{ $labels.node }}"

      # NVLink errors (multi-GPU training failure risk)
      - alert: NVLinkErrors
        expr: rate(DCGM_FI_DEV_NVLINK_CRC_FLIT_ERROR_COUNT_TOTAL[5m]) > 0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "NVLink CRC errors on {{ $labels.node }} — multi-GPU communication degraded"

      # GPU memory fragmentation (utilization high but allocations fail)
      - alert: GPUMemoryPressure
        expr: DCGM_FI_DEV_MEM_COPY_UTIL > 95
        for: 10m
        labels:
          severity: warning
```

### Pod Rescheduling on GPU Failure

```yaml
# k8s/vllm-deployment-resilient.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-70b
  namespace: ai-platform
spec:
  replicas: 2
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 0  # Never lose capacity during updates
      maxSurge: 1
  template:
    spec:
      terminationGracePeriodSeconds: 120  # Let in-flight requests complete
      containers:
        - name: vllm
          image: vllm/vllm-openai:latest
          args:
            - "--model=/models/llama-3-70b"
            - "--tensor-parallel-size=4"
            - "--max-model-len=8192"
          resources:
            limits:
              nvidia.com/gpu: "4"
          # Health check that actually tests inference
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 300  # Model loading takes time
            periodSeconds: 30
            failureThreshold: 3
            timeoutSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 300
            periodSeconds: 10
            failureThreshold: 2
          # Startup probe for slow model loading
          startupProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 60
            periodSeconds: 10
            failureThreshold: 60  # Up to 10 minutes to load
      # Spread across GPU nodes
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: vllm-70b
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: vllm-70b-pdb
  namespace: ai-platform
spec:
  minAvailable: 1  # Always keep at least 1 replica running
  selector:
    matchLabels:
      app: vllm-70b
```

### Warm Standby

Keep a pre-loaded model replica that only receives traffic on failover:

```yaml
# k8s/vllm-warm-standby.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-70b-standby
  namespace: ai-platform
spec:
  replicas: 1
  template:
    metadata:
      labels:
        app: vllm-70b
        role: standby  # Excluded from Service selector initially
    spec:
      containers:
        - name: vllm
          image: vllm/vllm-openai:latest
          args:
            - "--model=/models/llama-3-70b"
            - "--tensor-parallel-size=4"
            # Lower batch size to reduce GPU memory, since it's standby
            - "--max-num-seqs=8"
```

Failover script (triggered by alert):

```bash
#!/bin/bash
# Promote standby: add it to the active service
kubectl label pods -l role=standby -n ai-platform role=active --overwrite

# The Service selector matches role=active, so standby now gets traffic
```

---

## 5. Incident Response Playbook: "Model Returning Bad Answers"

### Detection

Bad answers rarely trigger alerts because HTTP 200 is returned with a valid response. Detection sources:

1. **Automated quality probe** — scheduled job sends canary prompts, scores with LLM-as-judge
2. **User reports** — thumbs-down signal, support tickets
3. **Drift detection** — embedding distribution shift of inputs vs training data
4. **Output anomalies** — response length distribution change, entropy spike

### Step 1: Triage (5 minutes)

```bash
# Is it infra? Check pod health
kubectl get pods -n ai-platform -l app=vllm-70b
kubectl top pods -n ai-platform -l app=vllm-70b

# Check GPU health
kubectl exec -n ai-platform deploy/vllm-70b -- nvidia-smi

# Check if model is loaded correctly
curl -s http://vllm-70b.ai-platform:8000/v1/models | jq .

# Check error rates
# (in Grafana, or):
kubectl logs -n ai-platform deploy/vllm-70b --tail=100 | grep -i "error\|OOM\|CUDA"

# Run a canary prompt manually
curl -s http://vllm-70b.ai-platform:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3-70b",
    "messages": [{"role": "user", "content": "What is 2+2? Answer with just the number."}],
    "max_tokens": 10,
    "temperature": 0
  }' | jq '.choices[0].message.content'
```

### Step 2: Classify the Issue (10 minutes)

| Symptom | Likely Cause | Check |
|---------|-------------|-------|
| Gibberish output | Model artifact corruption, wrong tokenizer | Compare model checksum vs registry |
| Correct format but wrong facts | Data drift, stale model | Check training data recency, run eval suite |
| Slow + bad quality | GPU thermal throttling, memory pressure | `nvidia-smi`, DCGM metrics |
| Intermittent bad answers | One replica is bad, load balancer rotates | Test each pod individually |
| All answers identical/repetitive | Temperature stuck at 0, KV cache corruption | Check serving config, restart pod |
| Works for short prompts, fails for long | Context window misconfigured, OOM on long sequences | Check `--max-model-len`, watch GPU memory |

```bash
# Check model artifact integrity
kubectl exec -n ai-platform deploy/vllm-70b -- md5sum /models/llama-3-70b/model*.safetensors

# Compare against model registry
aws s3api head-object --bucket models --key llama-3-70b/v6/model-00001-of-00015.safetensors \
  --query 'Metadata.md5'

# Test individual pods (bypass service)
PODS=$(kubectl get pods -n ai-platform -l app=vllm-70b -o jsonpath='{.items[*].metadata.name}')
for pod in $PODS; do
  echo "Testing $pod..."
  kubectl exec -n ai-platform $pod -- curl -s localhost:8000/v1/chat/completions \
    -d '{"model":"llama-3-70b","messages":[{"role":"user","content":"What is the capital of France?"}],"max_tokens":20,"temperature":0}' \
    | jq '.choices[0].message.content'
done
```

### Step 3: Mitigate (Immediate)

```bash
# Option A: Rollback model (if recent deployment caused it)
kubectl rollout undo deployment/vllm-70b -n ai-platform

# Option B: Enable safe mode (fall back to base model)
kubectl patch configmap api-config -n ai-platform \
  --type merge -p '{"data":{"SAFE_MODE":"true"}}'

# Option C: Scale down bad replicas, scale up good ones
kubectl scale deployment/vllm-70b -n ai-platform --replicas=0
kubectl scale deployment/vllm-70b-standby -n ai-platform --replicas=2
kubectl label pods -n ai-platform -l app=vllm-70b-standby role=active --overwrite

# Option D: If one pod is bad, cordon its node
kubectl cordon <node-with-bad-gpu>
kubectl delete pod <bad-pod> -n ai-platform  # Rescheduled elsewhere
```

### Step 4: Root Cause Analysis

```bash
# Check when quality degraded (query Prometheus for quality score history)
# Did it correlate with a deployment? A data pipeline run? A GPU swap?

# Check model version in each pod
kubectl exec -n ai-platform deploy/vllm-70b -- cat /models/llama-3-70b/config.json | jq '.model_version'

# Check recent deployments
kubectl rollout history deployment/vllm-70b -n ai-platform

# Check if training data pipeline pushed bad data
# (check your Airflow/Prefect DAG run history)

# Check GPU hardware events
kubectl logs -n monitoring daemonset/dcgm-exporter | grep -i "error\|xid\|ecc"
```

### Step 5: Prevention

- Add model checksum verification to deployment pipeline
- Add canary eval stage before promoting model to production
- Add automated rollback on quality score drop (see Section 3, Strategy 5)
- Add RCA to incident postmortem template

---

## 6. Capacity Planning for GPU

### Model VRAM Requirements

| Model | Parameters | FP16 VRAM | INT8 VRAM | INT4 (GPTQ/AWQ) | Min GPU Config |
|-------|-----------|-----------|-----------|------------------|---------------|
| Llama-3-8B | 8B | 16 GB | 8 GB | 5 GB | 1x A10G (24GB) |
| Llama-3-70B | 70B | 140 GB | 70 GB | 38 GB | 4x A100 80GB (TP=4) or 2x A100 (INT8) |
| Mixtral 8x7B | 46.7B | 94 GB | 47 GB | 26 GB | 2x A100 80GB |
| Llama-3-405B | 405B | 810 GB | 405 GB | 220 GB | 8x A100 80GB (INT8) or 8x H100 (FP16) |
| Phi-3-mini | 3.8B | 7.6 GB | 4 GB | 2.5 GB | 1x T4 (16GB) |

**Rule of thumb:** VRAM needed = (parameters x bytes_per_param) + KV cache + overhead

```
FP16:  params * 2 bytes
INT8:  params * 1 byte
INT4:  params * 0.5 bytes
KV cache: ~2 GB per 1000 concurrent tokens for 70B model
Overhead: +10-20% for activations, CUDA kernels
```

### MIG vs Time-Slicing Decision Matrix

| Factor | MIG (Multi-Instance GPU) | Time-Slicing |
|--------|--------------------------|-------------|
| **GPU support** | A100, H100 only | Any NVIDIA GPU |
| **Isolation** | Full: separate memory, compute, L2 cache | None: shared everything |
| **Use case** | Multiple small models on one A100 | Multiple users sharing one GPU |
| **Predictability** | Guaranteed performance per slice | Noisy neighbor, unpredictable latency |
| **Max partitions** | 7 (A100), 7 (H100) | Unlimited (but quality degrades) |
| **When to use** | Production inference for small models | Dev/test, batch jobs |
| **When NOT to use** | Large models that need full GPU | Latency-sensitive production |

```yaml
# MIG example: 3 partitions on A100 (3g.40gb each)
# k8s/mig-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: nvidia-mig-config
data:
  config.yaml: |
    version: v1
    mig-configs:
      all-3g.40gb:
        - device-filter: ["A100-SXM4-80GB"]
          devices: all
          mig-enabled: true
          mig-devices:
            "3g.40gb": 2  # Two 40GB slices from one A100
```

### Burst Capacity with Karpenter

```yaml
# k8s/karpenter-gpu-provisioner.yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: gpu-inference
spec:
  template:
    spec:
      requirements:
        - key: node.kubernetes.io/instance-type
          operator: In
          values:
            - g5.xlarge      # 1x A10G, $1.01/hr
            - g5.2xlarge     # 1x A10G, $1.21/hr
            - p4d.24xlarge   # 8x A100, $32.77/hr
            - g6.xlarge      # 1x L4, ~$0.80/hr
        - key: karpenter.sh/capacity-type
          operator: In
          values:
            - on-demand
            - spot           # 60-70% savings for batch/non-critical
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: gpu-nodes
      taints:
        - key: nvidia.com/gpu
          effect: NoSchedule
  disruption:
    consolidationPolicy: WhenEmpty
    consolidateAfter: 5m  # Don't kill GPU nodes immediately
  limits:
    nvidia.com/gpu: 16  # Max 16 GPUs burst
    cpu: 256
---
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: gpu-nodes
spec:
  amiSelectorTerms:
    - tags:
        karpenter.sh/discovery: "ml-cluster"
        gpu-driver: "installed"  # AMI with NVIDIA drivers pre-installed
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 200Gi  # Model artifacts need space
        volumeType: gp3
        iops: 5000
        throughput: 250
  instanceProfile: "KarpenterNodeInstanceProfile"
```

### Spot vs On-Demand Decision Tree

```
Is the workload latency-sensitive production inference?
  YES → On-Demand (spot interruption = dropped requests)
  NO  → Continue...

Can the workload checkpoint and resume?
  YES → Spot (training with checkpointing, batch inference)
  NO  → Continue...

Is the workload < 1 hour?
  YES → Spot (low interruption probability for short jobs)
  NO  → Continue...

Can you tolerate 2-minute warning interruptions?
  YES → Spot with graceful shutdown handler
  NO  → On-Demand

Mixed strategy:
  - Base capacity: On-Demand (handles steady-state traffic)
  - Burst capacity: Spot (handles spikes, with fallback to smaller/CPU models)
```

---

## 7. Canary Deployments for Models

### Istio VirtualService Weight-Based Routing

```yaml
# k8s/istio-canary.yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: llm-inference
  namespace: ai-platform
spec:
  hosts:
    - llm-inference.ai-platform.svc.cluster.local
  http:
    - match:
        - headers:
            x-canary:
              exact: "true"  # Force canary for testing
      route:
        - destination:
            host: vllm-canary
            port:
              number: 8000
    - route:
        - destination:
            host: vllm-stable
            port:
              number: 8000
          weight: 95
        - destination:
            host: vllm-canary
            port:
              number: 8000
          weight: 5  # Start with 5% traffic
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: llm-inference
  namespace: ai-platform
spec:
  host: vllm-stable
  trafficPolicy:
    connectionPool:
      http:
        maxRequestsPerConnection: 1  # Important for LLM streaming
    outlierDetection:
      consecutive5xxErrors: 3
      interval: 30s
      baseEjectionTime: 60s
```

### KServe InferenceService with Canary

```yaml
# k8s/kserve-canary.yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-3-70b
  namespace: ai-platform
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  predictor:
    # Stable model (default traffic)
    model:
      modelFormat:
        name: vLLM
      runtime: vllm-runtime
      storageUri: s3://models/llama-3-70b/v5  # Known good
      resources:
        limits:
          nvidia.com/gpu: "4"
    # Canary model
    canaryModelSpec:
      modelFormat:
        name: vLLM
      runtime: vllm-runtime
      storageUri: s3://models/llama-3-70b/v6  # New version
      resources:
        limits:
          nvidia.com/gpu: "4"
    canaryTrafficPercent: 10  # 10% to canary
```

### Automated Promotion Criteria

```python
# canary-controller/evaluator.py
"""
Runs every 5 minutes during canary.
Checks quality metrics before promoting.
"""
import httpx
from prometheus_api_client import PrometheusConnect

prom = PrometheusConnect(url="http://prometheus:9090")

PROMOTION_CRITERIA = {
    "error_rate_max": 0.005,           # < 0.5% errors
    "p99_latency_max_seconds": 12,     # < 12s P99
    "quality_score_min": 4.0,          # > 4.0/5.0
    "min_canary_requests": 500,        # At least 500 requests evaluated
    "min_canary_duration_minutes": 30, # At least 30 minutes
}

def check_canary_health() -> dict:
    # Error rate on canary
    error_rate = prom.custom_query(
        'sum(rate(http_requests_total{service="vllm-canary",status=~"5.."}[30m]))'
        '/ sum(rate(http_requests_total{service="vllm-canary"}[30m]))'
    )

    # P99 latency on canary
    p99 = prom.custom_query(
        'histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{service="vllm-canary"}[30m])) by (le))'
    )

    # Quality score (from eval job)
    quality = prom.custom_query(
        'ml_model_quality_score{deployment="canary"}'
    )

    # Request count
    total_requests = prom.custom_query(
        'sum(increase(http_requests_total{service="vllm-canary"}[1h]))'
    )

    return {
        "error_rate": float(error_rate[0]["value"][1]),
        "p99_latency": float(p99[0]["value"][1]),
        "quality_score": float(quality[0]["value"][1]),
        "total_requests": int(float(total_requests[0]["value"][1])),
    }

def should_promote(metrics: dict) -> tuple[bool, str]:
    if metrics["total_requests"] < PROMOTION_CRITERIA["min_canary_requests"]:
        return False, f"Insufficient traffic: {metrics['total_requests']} requests"

    if metrics["error_rate"] > PROMOTION_CRITERIA["error_rate_max"]:
        return False, f"Error rate too high: {metrics['error_rate']:.4f}"

    if metrics["p99_latency"] > PROMOTION_CRITERIA["p99_latency_max_seconds"]:
        return False, f"P99 latency too high: {metrics['p99_latency']:.1f}s"

    if metrics["quality_score"] < PROMOTION_CRITERIA["quality_score_min"]:
        return False, f"Quality score too low: {metrics['quality_score']:.2f}"

    return True, "All criteria met"

def should_rollback(metrics: dict) -> tuple[bool, str]:
    """Immediate rollback conditions (don't wait for evaluation window)."""
    if metrics["error_rate"] > 0.05:  # 5% errors = immediate rollback
        return True, f"Critical error rate: {metrics['error_rate']:.4f}"
    if metrics["p99_latency"] > 30:   # 30s = something is very wrong
        return True, f"Critical latency: {metrics['p99_latency']:.1f}s"
    return False, "No rollback needed"
```

### Progressive Rollout Script

```bash
#!/bin/bash
# canary-promote.sh — gradually increase canary traffic
set -euo pipefail

NAMESPACE="ai-platform"
INFERENCE_SERVICE="llama-3-70b"
WEIGHTS=(5 10 25 50 75 100)
EVAL_WAIT=300  # 5 minutes between steps

for weight in "${WEIGHTS[@]}"; do
  echo "[$(date)] Setting canary traffic to ${weight}%"

  kubectl patch inferenceservice $INFERENCE_SERVICE -n $NAMESPACE \
    --type merge -p "{\"spec\":{\"predictor\":{\"canaryTrafficPercent\":$weight}}}"

  if [ "$weight" -eq 100 ]; then
    echo "[$(date)] Canary promoted to 100%. Done."
    break
  fi

  echo "[$(date)] Waiting ${EVAL_WAIT}s for evaluation..."
  sleep $EVAL_WAIT

  # Check health (call the evaluator API)
  HEALTH=$(curl -s http://canary-controller:8000/check)
  SHOULD_CONTINUE=$(echo $HEALTH | jq -r '.promote')
  SHOULD_ROLLBACK=$(echo $HEALTH | jq -r '.rollback')

  if [ "$SHOULD_ROLLBACK" = "true" ]; then
    echo "[$(date)] ROLLBACK: $(echo $HEALTH | jq -r '.reason')"
    kubectl patch inferenceservice $INFERENCE_SERVICE -n $NAMESPACE \
      --type merge -p '{"spec":{"predictor":{"canaryTrafficPercent":0}}}'
    exit 1
  fi

  if [ "$SHOULD_CONTINUE" != "true" ]; then
    echo "[$(date)] Holding at ${weight}%: $(echo $HEALTH | jq -r '.reason')"
    # Stay at current weight, re-evaluate
    sleep $EVAL_WAIT
  fi
done
```

---

## 8. Chaos Engineering for GPU Workloads

### What to Test and How

| Failure Scenario | How to Inject | What to Validate |
|-----------------|--------------|-----------------|
| **GPU goes offline** | `kubectl cordon <gpu-node>` + delete pod | Pod reschedules, traffic shifts to healthy replicas |
| **NCCL failure** (multi-GPU) | Kill one GPU process in a TP group | Serving pod detects failure, restarts, reloads model |
| **Model artifact corruption** | Replace model file with random bytes, restart pod | Health check catches load failure, pod stays NotReady |
| **OOM kill** | Send prompt with `max_tokens=32768` to small model | 429/503 returned, other requests unaffected |
| **Spot interruption** | `aws ec2 terminate-instances` on spot node | Karpenter provisions replacement, PDB prevents total outage |
| **Network partition** | NetworkPolicy blocking model storage | Pod can't reload model — existing loaded model keeps serving |
| **Redis failure** (rate limiter) | Kill Redis pod | Rate limiter fails open (or closed?), verify behavior |
| **Slow model loading** | Throttle EBS/S3 bandwidth | Startup probe handles slow load, traffic stays on old pods |

### Chaos Scripts

```bash
# Test 1: GPU node failure
# Expectation: PDB prevents all replicas dying, traffic shifts in < 30s

echo "=== Test: GPU Node Failure ==="
NODE=$(kubectl get pods -n ai-platform -l app=vllm-70b -o jsonpath='{.items[0].spec.nodeName}')
echo "Cordoning node: $NODE"
kubectl cordon $NODE

echo "Deleting pod on cordoned node..."
POD=$(kubectl get pods -n ai-platform -l app=vllm-70b --field-selector spec.nodeName=$NODE -o jsonpath='{.items[0].metadata.name}')
kubectl delete pod $POD -n ai-platform

echo "Watching recovery..."
kubectl get pods -n ai-platform -l app=vllm-70b -w &
WATCH_PID=$!

# Send test requests during recovery
for i in $(seq 1 30); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://vllm-70b.ai-platform:8000/v1/models)
  echo "$(date): HTTP $STATUS"
  sleep 2
done

kill $WATCH_PID
kubectl uncordon $NODE
echo "=== Test Complete ==="
```

```bash
# Test 2: OOM simulation
# Send a request designed to exhaust GPU memory
echo "=== Test: GPU OOM ==="
# Create a massive prompt (fill context window)
python3 -c "
import json
msg = 'word ' * 50000  # ~50K tokens
req = {'model': 'llama-3-70b', 'messages': [{'role': 'user', 'content': msg}], 'max_tokens': 4096}
print(json.dumps(req))
" > /tmp/oom-payload.json

# Send it
curl -s -w "\nHTTP: %{http_code}\n" \
  http://vllm-70b.ai-platform:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d @/tmp/oom-payload.json

# Verify other requests still work
curl -s http://vllm-70b.ai-platform:8000/v1/chat/completions \
  -d '{"model":"llama-3-70b","messages":[{"role":"user","content":"Hello"}],"max_tokens":10}' \
  | jq '.choices[0].message.content'

echo "=== Test Complete ==="
```

```bash
# Test 3: Model artifact corruption
echo "=== Test: Model Corruption ==="
# Create a test pod with the model volume
kubectl run corruption-test -n ai-platform \
  --image=busybox \
  --restart=Never \
  --overrides='{
    "spec": {
      "containers": [{
        "name": "corruption-test",
        "image": "busybox",
        "command": ["sh", "-c", "dd if=/dev/urandom of=/models/llama-3-70b/model-00001-of-00015.safetensors bs=1M count=10 && echo CORRUPTED"],
        "volumeMounts": [{"name": "models", "mountPath": "/models"}]
      }],
      "volumes": [{"name": "models", "persistentVolumeClaim": {"claimName": "model-storage"}}]
    }
  }'

# Restart vLLM to trigger model reload
kubectl rollout restart deployment/vllm-70b -n ai-platform

# Watch: pod should fail health check and stay NotReady
kubectl get pods -n ai-platform -l app=vllm-70b -w

# Clean up: restore model from S3
# aws s3 cp s3://models/llama-3-70b/v5/ /models/llama-3-70b/ --recursive
echo "=== Test Complete ==="
```

### Chaos Engineering Checklist

Before running in production:

- [ ] PDB is configured (`minAvailable: 1`)
- [ ] Multiple replicas are running
- [ ] Alerts are configured to fire during test (validates alerting)
- [ ] Runbook exists for each failure mode
- [ ] Rollback procedure is documented and tested
- [ ] Stakeholders are notified ("we're running chaos tests from 2-3pm")
- [ ] Blast radius is limited (test in staging first, then one prod zone)

---

## 9. Monitoring Stack for ML SRE

### Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ vLLM Pods   │────▶│ Prometheus   │────▶│ Grafana          │
│ /metrics    │     │              │     │ (dashboards)     │
└─────────────┘     │              │     └─────────────────┘
                    │              │
┌─────────────┐     │              │     ┌─────────────────┐
│ DCGM        │────▶│              │────▶│ Alertmanager     │
│ Exporter    │     │              │     │ → Slack/PagerDuty│
└─────────────┘     └──────────────┘     └─────────────────┘

┌─────────────┐     ┌──────────────┐
│ LiteLLM     │────▶│ Langfuse     │  ← Trace-level observability
│ (gateway)   │     │              │    (prompt, response, tokens, latency, cost)
└─────────────┘     └──────────────┘

┌─────────────┐     ┌──────────────┐
│ Eval Jobs   │────▶│ Prometheus   │  ← Quality scores as gauges
│ (CronJob)   │     │ Pushgateway  │
└─────────────┘     └──────────────┘
```

### Prometheus ServiceMonitor for vLLM

```yaml
# k8s/monitoring/vllm-servicemonitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: vllm-metrics
  namespace: monitoring
spec:
  selector:
    matchLabels:
      app: vllm-70b
  namespaceSelector:
    matchNames:
      - ai-platform
  endpoints:
    - port: metrics
      interval: 15s
      path: /metrics
```

### Alert Rules

```yaml
# k8s/monitoring/ml-alert-rules.yaml
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: ml-sre-alerts
  namespace: monitoring
spec:
  groups:
    # === Availability ===
    - name: ml-availability
      rules:
        - alert: InferenceEndpointDown
          expr: up{job="vllm"} == 0
          for: 2m
          labels:
            severity: critical
          annotations:
            summary: "vLLM endpoint {{ $labels.instance }} is down"
            runbook: "https://runbooks.internal/vllm-down"

        - alert: AllReplicasUnhealthy
          expr: |
            kube_deployment_status_replicas_available{deployment="vllm-70b"} == 0
          for: 1m
          labels:
            severity: critical
          annotations:
            summary: "All vLLM replicas are down"

    # === Latency ===
    - name: ml-latency
      rules:
        - alert: InferenceP99LatencyHigh
          expr: |
            histogram_quantile(0.99,
              sum(rate(http_request_duration_seconds_bucket{service="vllm"}[5m])) by (le)
            ) > 15
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Inference P99 latency is {{ $value | humanizeDuration }}"

        - alert: TimeToFirstTokenSlow
          expr: |
            histogram_quantile(0.95,
              sum(rate(vllm:time_to_first_token_seconds_bucket[5m])) by (le)
            ) > 2
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Time to first token P95 is {{ $value }}s"

    # === Quality ===
    - name: ml-quality
      rules:
        - alert: ModelQualityDegraded
          expr: ml_model_quality_score{eval_type="canary"} < 3.5
          for: 15m
          labels:
            severity: critical
          annotations:
            summary: "Model quality score dropped to {{ $value }}"
            action: "Check data drift, consider rollback"

        - alert: QualityEvalJobFailed
          expr: |
            time() - ml_eval_last_success_timestamp > 3600
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "Quality eval job hasn't succeeded in > 1 hour"

    # === GPU ===
    - name: ml-gpu
      rules:
        - alert: GPUUtilizationLow
          expr: |
            avg(DCGM_FI_DEV_GPU_UTIL{namespace="ai-platform"}) < 20
          for: 30m
          labels:
            severity: info
          annotations:
            summary: "GPU utilization avg {{ $value }}% — consider scaling down"

        - alert: GPUMemoryExhaustion
          expr: DCGM_FI_DEV_MEM_COPY_UTIL > 95
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "GPU memory at {{ $value }}% on {{ $labels.node }}"

        - alert: GPUECCError
          expr: increase(DCGM_FI_DEV_ECC_DBE_VOL_TOTAL[5m]) > 0
          labels:
            severity: critical
          annotations:
            summary: "Double-bit ECC error on GPU {{ $labels.gpu }} node {{ $labels.node }}"
            action: "Drain node, file hardware replacement"

    # === Throughput ===
    - name: ml-throughput
      rules:
        - alert: TokenThroughputDrop
          expr: |
            sum(rate(vllm:num_generation_tokens_total[5m]))
            < 0.5 * sum(rate(vllm:num_generation_tokens_total[1h]))
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Token throughput dropped 50% from hourly average"

        - alert: RequestQueueBacklog
          expr: vllm:num_requests_waiting > 50
          for: 5m
          labels:
            severity: warning
          annotations:
            summary: "{{ $value }} requests waiting in vLLM queue"

    # === Cost ===
    - name: ml-cost
      rules:
        - alert: DailySpendExceeded
          expr: |
            sum(increase(litellm_spend_total[24h])) > 500
          for: 0m
          labels:
            severity: warning
          annotations:
            summary: "Daily AI spend: ${{ $value | humanize }}"

        - alert: TenantBudgetExhausted
          expr: |
            litellm_team_spend / litellm_team_budget > 0.9
          for: 0m
          labels:
            severity: info
          annotations:
            summary: "Team {{ $labels.team }} at {{ $value | humanizePercentage }} of budget"
```

### Langfuse Integration for Trace-Level Observability

Prometheus tells you WHAT is wrong. Langfuse tells you WHY — it captures every prompt, response, token count, latency, and cost at the trace level.

```python
# In LiteLLM config:
# litellm_settings:
#   success_callback: ["langfuse"]
#   langfuse_public_key: "pk-..."
#   langfuse_secret_key: "sk-..."
#   langfuse_host: "http://langfuse.monitoring.svc:3000"

# Or in custom code:
from langfuse import Langfuse

langfuse = Langfuse(
    public_key="pk-...",
    secret_key="sk-...",
    host="http://langfuse:3000",
)

# Create a trace for each request
trace = langfuse.trace(
    name="chat-completion",
    user_id=user_context.user_id,
    metadata={"team": user_context.team, "tier": user_context.tier},
)

generation = trace.generation(
    name="llm-call",
    model="llama-3-70b",
    input=messages,
    model_parameters={"temperature": 0.7, "max_tokens": 1024},
)

# After inference
generation.end(
    output=response.choices[0].message.content,
    usage={
        "input": response.usage.prompt_tokens,
        "output": response.usage.completion_tokens,
        "total": response.usage.total_tokens,
    },
)

# Score the response (from user feedback or automated eval)
trace.score(name="quality", value=4.5, comment="Accurate response")
```

### Quality Eval CronJob

```yaml
# k8s/monitoring/quality-eval-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: model-quality-eval
  namespace: ai-platform
spec:
  schedule: "*/15 * * * *"  # Every 15 minutes
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: eval
              image: internal/model-evaluator:latest
              env:
                - name: VLLM_ENDPOINT
                  value: "http://vllm-70b:8000"
                - name: PROMETHEUS_PUSHGATEWAY
                  value: "http://pushgateway.monitoring:9091"
                - name: EVAL_PROMPTS_PATH
                  value: "/eval/canary-prompts.json"
              volumeMounts:
                - name: eval-prompts
                  mountPath: /eval
          volumes:
            - name: eval-prompts
              configMap:
                name: canary-eval-prompts
          restartPolicy: OnFailure
```

---

## 10. Interview Q&As

**Q1: You're on-call and get alerted that your LLM API is returning bad answers but all infrastructure metrics look green. How do you investigate?**

Green infra metrics with bad outputs means the model itself is the problem, not the infrastructure. My steps: (1) Run canary prompts manually against each replica to isolate if it's all pods or one. (2) Check model artifact checksums against the registry — corruption during download is common with large models on EFS/S3. (3) Check if a model update was deployed recently — `kubectl rollout history`. (4) Check data pipeline — did a recent training run push a bad model? (5) Check serving config — did someone change temperature, max_tokens, or system prompts? (6) Immediate mitigation: enable safe mode to fall back to the base model while investigating. Traditional SRE instincts to check CPU/memory/network won't help here — it's a quality issue, not an availability issue.

**Q2: How would you define SLOs for an internal LLM serving platform?**

I'd define five SLOs: (1) Availability — 99.9%, measured by synthetic probe success rate every 30s. (2) Latency — P50 time-to-first-token < 500ms, P99 total response < 10s, measured at the gateway. (3) Throughput — tokens per second per GPU above a model-specific baseline (e.g., 30 tok/s for 70B). (4) Quality — canary eval score > 4.0/5.0 using LLM-as-judge on standardized prompts every 15 minutes. (5) Freshness — model updated within 7 days of new training data availability. The quality SLO is the ML-specific one that doesn't exist in traditional SRE. I'd use error budget policies: if quality SLO is burned, freeze model updates and rollback. If availability SLO is burned, freeze infrastructure changes.

**Q3: What's different about capacity planning for GPU inference vs traditional CPU services?**

Three key differences: (1) VRAM is the binding constraint, not CPU or memory. A 70B parameter model in FP16 needs 140GB VRAM — that's 2x A100-80GB minimum, regardless of request volume. You right-size by model requirements first, then scale replicas for throughput. (2) Scaling is slow. GPU node provisioning takes 2-5 minutes, model loading takes another 2-10 minutes. You can't scale reactively like CPU services — you need predictive scaling or warm standbys. (3) Cost is non-linear. An A100 costs $3/hr vs $0.03/hr for a CPU instance. Over-provisioning by 2x costs $100K+/year. I'd use MIG to partition A100s for small models, Karpenter with spot instances for burst/batch, and maintain warm standbys for critical models.

**Q4: How would you implement canary deployments for ML models?**

I'd use KServe InferenceService with canaryTrafficPercent. Deploy the new model version as a canary with 5% traffic. Run automated evaluation: compare error rate, P99 latency, and quality score (LLM-as-judge on canary prompts) between stable and canary. Progressive rollout: 5% to 10% to 25% to 50% to 100%, with 5-minute evaluation at each step. Automated rollback triggers: >5% error rate or quality score drop below 3.5 immediately rolls back to 0% canary. Key ML-specific consideration: you need to evaluate OUTPUT QUALITY, not just latency and errors. A model can have perfect latency and zero errors while returning terrible answers. The canary evaluator needs to score actual responses.

**Q5: Describe your GPU failure monitoring strategy.**

I deploy the NVIDIA DCGM exporter as a DaemonSet on all GPU nodes, exposing metrics to Prometheus. Critical alerts: (1) Double-bit ECC errors (DCGM_FI_DEV_ECC_DBE) — immediate, means the GPU is unreliable, drain the node. (2) XID error 79 — GPU fell off the bus, needs hardware replacement. (3) NVLink CRC errors — multi-GPU communication is degraded, tensor parallelism will be slow or fail. (4) Temperature > 85C for 5 minutes — thermal throttling, check cooling. (5) GPU memory utilization > 95% — OOM risk. For resilience: PodDisruptionBudget ensures at least one replica survives during node drain. TopologySpreadConstraints distribute replicas across nodes. Warm standby replicas with models pre-loaded can be promoted in seconds (just add the service label) vs minutes for cold start.
