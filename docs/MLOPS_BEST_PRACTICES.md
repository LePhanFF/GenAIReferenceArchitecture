# MLOps Best Practices & Tool Landscape

Practical guide covering MLOps maturity, tooling decisions, and implementation patterns for production AI/ML platforms.

---

## 1. MLOps Maturity Levels

### Level 0 — Manual Everything

- Data scientists train models in notebooks
- Manual model deployment (copy weights, restart service)
- No experiment tracking, no versioning, no automated testing
- "It works on my machine" is the deployment strategy

**Where most teams start.** Fast to prototype, impossible to maintain.

### Level 1 — ML Pipeline Automation

- Automated training pipeline (trigger → preprocess → train → evaluate → register)
- Experiment tracking (MLflow/W&B)
- Model versioning and registry
- Data validation before training
- Still manual deployment decisions

**Where this repo currently sits.** Training is automated, but deployment still requires human judgment for promotion decisions.

### Level 2 — CI/CD for ML (Full MLOps)

- Automated retraining on data drift or schedule
- CI/CD pipeline: code change → test → train → evaluate → deploy (canary)
- Automated rollback on quality regression
- Feature monitoring, drift detection, alerting
- A/B testing infrastructure for model comparison

**Where to aim.** The gap from Level 1 to Level 2 is primarily: automated deployment gates, drift detection, and canary rollout infrastructure.

### Maturity Assessment Checklist

| Capability | L0 | L1 | L2 |
|---|---|---|---|
| Reproducible training | No | Yes | Yes |
| Experiment tracking | No | Yes | Yes |
| Automated training pipeline | No | Yes | Yes |
| Model registry | No | Yes | Yes |
| Data validation | No | Partial | Yes |
| Automated deployment | No | No | Yes |
| Drift detection | No | No | Yes |
| Canary/A-B rollout | No | No | Yes |
| Automated rollback | No | No | Yes |

---

## 2. Model Versioning

### DVC (Data Version Control) — Git-Native Data & Model Tracking

DVC extends Git to track large files (datasets, model weights) without bloating the repo. The actual data lives in remote storage (S3, GCS); Git tracks `.dvc` metadata files.

**Best for:** Data versioning, dataset lineage, reproducible pipelines.

```bash
# Initialize DVC in an existing git repo
dvc init

# Track a large dataset
dvc add data/training_data.parquet
git add data/training_data.parquet.dvc data/.gitignore
git commit -m "Track training dataset v1"

# Configure remote storage
dvc remote add -d myremote s3://my-bucket/dvc-store

# Push data to remote
dvc push

# Track model weights
dvc add models/llm-finetuned/
git add models/llm-finetuned.dvc
git commit -m "Register fine-tuned model v2.1"

# Reproduce a pipeline
dvc repro  # Runs stages defined in dvc.yaml

# Switch to a previous version
git checkout v1.0
dvc checkout  # Pulls matching data version
```

**dvc.yaml pipeline definition:**

```yaml
stages:
  preprocess:
    cmd: python src/preprocess.py
    deps:
      - src/preprocess.py
      - data/raw/
    outs:
      - data/processed/

  train:
    cmd: python src/train.py --epochs 10 --lr 0.001
    deps:
      - src/train.py
      - data/processed/
    outs:
      - models/trained/
    metrics:
      - metrics.json:
          cache: false
    plots:
      - plots/loss.csv:
          x: epoch
          y: loss
```

### MLflow Model Registry — Staging to Production Lifecycle

MLflow Model Registry manages the model lifecycle: register versions, transition through stages, track lineage back to the training run.

**Best for:** Model lifecycle management, team collaboration on model promotion.

```python
import mlflow
from mlflow.tracking import MlflowClient

# Log a training run and register the model
with mlflow.start_run() as run:
    mlflow.log_params({"lr": 0.001, "epochs": 10, "model": "llama-3.1-8b"})
    mlflow.log_metrics({"eval_loss": 0.23, "rouge_l": 0.87})

    # Log model artifact and register in one step
    mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=my_model,
        registered_model_name="rag-answer-generator"
    )

client = MlflowClient()

# Transition model through stages
client.transition_model_version_stage(
    name="rag-answer-generator",
    version=3,
    stage="Staging"  # Options: None, Staging, Production, Archived
)

# After validation passes, promote to production
client.transition_model_version_stage(
    name="rag-answer-generator",
    version=3,
    stage="Production"
)

# Query the production model
production_model = client.get_latest_versions(
    "rag-answer-generator", stages=["Production"]
)
print(f"Production model: v{production_model[0].version}")
```

### lakeFS — Data Lake Branching

lakeFS provides Git-like branching for data lakes. Create branches of your entire data lake, experiment, then merge — without copying data.

**Best for:** Data lake experimentation, zero-copy branching, data CI/CD.

```python
import lakefs_client
from lakefs_client.api import branches_api, objects_api

# Create a branch for a training experiment
branches_api.create_branch(
    repository="ml-data",
    branch_creation={"name": "experiment-new-embeddings", "source": "main"}
)

# Write new training data to the branch
objects_api.upload_object(
    repository="ml-data",
    branch="experiment-new-embeddings",
    path="training/v2/data.parquet",
    content=open("new_data.parquet", "rb")
)

# After validation, merge back to main
branches_api.merge_into_branch(
    repository="ml-data",
    source_ref="experiment-new-embeddings",
    destination_branch="main"
)
```

### Recommendation

| Tool | Use Case |
|---|---|
| **MLflow Model Registry** | Model lifecycle (staging → production), team model promotion |
| **DVC** | Dataset versioning, pipeline reproducibility, large file tracking |
| **lakeFS** | If you have a data lake and need branching semantics (less common for LLM apps) |

For this repo: **MLflow for model registry + DVC for data versioning** is the standard combo.

---

## 3. Experiment Tracking

### What to Track

Every training run should capture:

| Category | Examples |
|---|---|
| **Parameters** | Learning rate, batch size, epochs, LoRA rank, model base |
| **Metrics** | Loss, accuracy, ROUGE, BLEU, perplexity, latency |
| **Artifacts** | Model weights, configs, sample outputs, evaluation reports |
| **Environment** | Python version, GPU type, CUDA version, pip freeze |
| **Data lineage** | Dataset version (DVC hash), preprocessing commit, data split |
| **Code version** | Git commit SHA, branch name |

### MLflow vs W&B vs LangFuse

| Feature | MLflow | W&B (Weights & Biases) | LangFuse |
|---|---|---|---|
| **Self-hosted** | Yes (open source) | No (SaaS, enterprise self-host) | Yes (open source) |
| **Experiment tracking** | Strong | Best-in-class | Not its focus |
| **Model registry** | Built-in | Via Registry | No |
| **LLM tracing** | Basic | Via Prompts | Best-in-class |
| **Cost** | Free | Free tier, then paid | Free (self-host) |
| **K8s integration** | Good | Good | Good |
| **Best for** | Full MLOps pipeline | Research teams, visualization | LLM app observability |

**For this repo:** MLflow for training experiments + model registry. LangFuse for LLM inference tracing (prompt/response logging, latency, token costs).

### Code Example: Logging a Training Run with MLflow

```python
import mlflow
import torch
from transformers import AutoModelForCausalLM, TrainingArguments, Trainer

mlflow.set_tracking_uri("http://mlflow.internal:5000")
mlflow.set_experiment("rag-fine-tuning")

with mlflow.start_run(run_name="llama3-lora-r16-lr3e4") as run:
    # Log parameters
    mlflow.log_params({
        "base_model": "meta-llama/Llama-3.1-8B",
        "method": "LoRA",
        "lora_r": 16,
        "lora_alpha": 32,
        "learning_rate": 3e-4,
        "epochs": 3,
        "batch_size": 4,
        "gradient_accumulation": 8,
        "dataset_version": "dvc:abc123",  # DVC hash for lineage
        "dataset_size": 15000,
    })

    # Log environment
    mlflow.log_params({
        "gpu": torch.cuda.get_device_name(0),
        "cuda_version": torch.version.cuda,
        "torch_version": torch.__version__,
    })

    # Training loop (simplified)
    trainer = Trainer(model=model, args=training_args, train_dataset=dataset)
    result = trainer.train()

    # Log metrics
    mlflow.log_metrics({
        "train_loss": result.training_loss,
        "eval_loss": eval_results["eval_loss"],
        "rouge_l": eval_results["rouge_l"],
        "inference_latency_ms": benchmark_latency(),
        "training_time_minutes": result.metrics["train_runtime"] / 60,
        "gpu_cost_usd": calculate_gpu_cost(result.metrics["train_runtime"]),
    })

    # Log artifacts
    mlflow.log_artifact("config.yaml")
    mlflow.log_artifact("eval_samples.json")

    # Register the model
    mlflow.pyfunc.log_model(
        artifact_path="model",
        python_model=model,
        registered_model_name="rag-generator-llama3",
    )

    print(f"Run ID: {run.info.run_id}")
    print(f"Artifact URI: {run.info.artifact_uri}")
```

### LangFuse for LLM Inference Tracing

```python
from langfuse import Langfuse
from langfuse.decorators import observe

langfuse = Langfuse()

@observe()
def rag_pipeline(query: str):
    # Trace the full RAG pipeline
    with langfuse.trace(name="rag-query") as trace:
        # Retrieval step
        with trace.span(name="retrieval") as span:
            docs = vector_store.similarity_search(query, k=5)
            span.update(metadata={"num_docs": len(docs)})

        # Generation step
        with trace.generation(
            name="llm-generation",
            model="llama-3.1-8b",
            input=prompt,
        ) as gen:
            response = llm.generate(prompt)
            gen.update(
                output=response,
                usage={"input_tokens": 500, "output_tokens": 200},
            )

    return response
```

---

## 4. Model Serving Comparison

### Decision Matrix

| Feature | vLLM | KServe | Seldon Core | BentoML |
|---|---|---|---|---|
| **Purpose** | LLM inference | General model serving | General model serving | Model packaging + serving |
| **LLM optimized** | Yes (PagedAttention, continuous batching) | Via custom runtime | No | Partial |
| **K8s native** | Deployment only | Yes (CRDs, Knative) | Yes (CRDs, Istio) | Yes (Yatai operator) |
| **GPU support** | Excellent | Good | Good | Good |
| **Scale to zero** | No | Yes (Knative) | Yes (with HPA) | No |
| **Canary rollout** | Manual (Istio) | Built-in (InferenceService) | Built-in | Manual |
| **Multi-model** | No | Yes (ModelMesh) | Yes | Yes |
| **Complexity** | Low | Medium | High | Low |
| **OpenAI-compatible API** | Yes | No (custom protocol) | No | Configurable |
| **Throughput (LLM)** | Best | Moderate | Moderate | Moderate |
| **Community** | Very active | Active (CNCF) | Declining | Active |

### When to Use Which

**vLLM** — Use for LLM inference workloads. Best throughput, OpenAI-compatible API, simple deployment. This is the default choice for serving LLMs in production.

```yaml
# vLLM Kubernetes Deployment
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-llama3
spec:
  replicas: 2
  selector:
    matchLabels:
      app: vllm-llama3
  template:
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        args:
        - "--model=meta-llama/Llama-3.1-8B-Instruct"
        - "--tensor-parallel-size=1"
        - "--max-model-len=8192"
        - "--gpu-memory-utilization=0.9"
        ports:
        - containerPort: 8000
        resources:
          limits:
            nvidia.com/gpu: 1
            memory: "24Gi"
          requests:
            nvidia.com/gpu: 1
            memory: "16Gi"
```

**KServe** — Use for general model serving (scikit-learn, PyTorch, TensorFlow, XGBoost) or when you need scale-to-zero, canary rollouts, or multi-model serving on K8s.

```yaml
# KServe InferenceService with canary
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: fraud-detector
spec:
  predictor:
    model:
      modelFormat:
        name: sklearn
      storageUri: "s3://models/fraud-detector/v2"
    canaryTrafficPercent: 10
  # Previous version serves 90%
```

**Seldon Core** — Legacy choice, declining community. Only use if already deployed. Migrate to KServe for new projects.

**BentoML** — Use when you need to package models with custom pre/post-processing as a self-contained service. Good for teams that want a framework-agnostic packaging layer.

### Recommendation for This Repo

- **LLM inference:** vLLM (already in use)
- **Embedding models / classifiers:** KServe (if K8s-native scale-to-zero is needed) or direct FastAPI deployment (simpler)
- **Canary rollouts:** Istio VirtualService for traffic splitting (works with any backend)

---

## 5. ML Pipeline Orchestration

### Comparison Table

| Feature | Kubeflow Pipelines | Argo Workflows | Prefect | ZenML |
|---|---|---|---|---|
| **K8s native** | Yes | Yes | No (runs anywhere) | Orchestrator-agnostic |
| **DAG definition** | Python SDK | YAML | Python decorators | Python decorators |
| **UI** | Good | Good | Excellent | Good |
| **GPU scheduling** | Yes | Yes | Via K8s executor | Via orchestrator |
| **Complexity** | High | Medium | Low | Low |
| **Caching** | Built-in | Manual | Built-in | Built-in |
| **Best for** | Full ML platform | K8s workflow automation | Data engineering | MLOps-specific pipelines |
| **Community** | Large (Google) | Very large (CNCF) | Large | Growing |

### Argo Workflows — Training Pipeline as DAG

Argo Workflows is the most flexible K8s-native option. It handles GPU scheduling, retry logic, and artifact passing between steps.

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: training-pipeline-
spec:
  entrypoint: ml-pipeline
  arguments:
    parameters:
    - name: model-name
      value: "llama-3.1-8b"
    - name: dataset-version
      value: "v2.3"
    - name: learning-rate
      value: "3e-4"

  templates:
  - name: ml-pipeline
    dag:
      tasks:
      # Step 1: Validate data quality (runs first)
      - name: validate-data
        template: data-validation
        arguments:
          parameters:
          - name: dataset-version
            value: "{{workflow.parameters.dataset-version}}"

      # Step 2: Preprocess (after validation passes)
      - name: preprocess
        template: preprocess-data
        dependencies: [validate-data]

      # Step 3: Train (GPU job, after preprocessing)
      - name: train
        template: train-model
        dependencies: [preprocess]
        arguments:
          parameters:
          - name: learning-rate
            value: "{{workflow.parameters.learning-rate}}"

      # Step 4: Evaluate (after training)
      - name: evaluate
        template: evaluate-model
        dependencies: [train]

      # Step 5: Register model (only if evaluation passes)
      - name: register
        template: register-model
        dependencies: [evaluate]

  # Data validation step
  - name: data-validation
    container:
      image: ml-pipeline/data-validator:latest
      command: [python, validate.py]
      args: ["--dataset={{inputs.parameters.dataset-version}}"]
    inputs:
      parameters:
      - name: dataset-version

  # Training step (GPU)
  - name: train-model
    retryStrategy:
      limit: 2
      retryPolicy: OnError
    container:
      image: ml-pipeline/trainer:latest
      command: [python, train.py]
      args:
      - "--model={{workflow.parameters.model-name}}"
      - "--lr={{inputs.parameters.learning-rate}}"
      - "--output=/mnt/models/output"
      resources:
        limits:
          nvidia.com/gpu: 1
          memory: "32Gi"
        requests:
          nvidia.com/gpu: 1
          memory: "24Gi"
      volumeMounts:
      - name: model-storage
        mountPath: /mnt/models
    inputs:
      parameters:
      - name: learning-rate
    outputs:
      artifacts:
      - name: model-weights
        path: /mnt/models/output

  # Evaluate step
  - name: evaluate-model
    container:
      image: ml-pipeline/evaluator:latest
      command: [python, evaluate.py]
      args: ["--model-path=/mnt/models/output"]
      volumeMounts:
      - name: model-storage
        mountPath: /mnt/models
    outputs:
      parameters:
      - name: eval-score
        valueFrom:
          path: /tmp/eval_score.txt

  # Register in MLflow
  - name: register-model
    container:
      image: ml-pipeline/registrar:latest
      command: [python, register.py]
      env:
      - name: MLFLOW_TRACKING_URI
        value: "http://mlflow.ml-platform:5000"

  volumes:
  - name: model-storage
    persistentVolumeClaim:
      claimName: training-pvc
```

### Kubeflow Pipelines — Python SDK

```python
from kfp import dsl, compiler

@dsl.component(base_image="python:3.11", packages_to_install=["pandas", "great_expectations"])
def validate_data(dataset_path: str) -> bool:
    import great_expectations as gx
    # Validation logic
    return True

@dsl.component(base_image="nvcr.io/nvidia/pytorch:24.01-py3")
def train_model(dataset_path: str, lr: float, epochs: int) -> str:
    # Training logic
    return "/models/output"

@dsl.pipeline(name="training-pipeline")
def training_pipeline(dataset_path: str, lr: float = 3e-4, epochs: int = 3):
    validate_task = validate_data(dataset_path=dataset_path)
    train_task = train_model(
        dataset_path=dataset_path, lr=lr, epochs=epochs
    ).after(validate_task)
    train_task.set_gpu_limit(1)
    train_task.set_memory_limit("32Gi")

compiler.Compiler().compile(training_pipeline, "pipeline.yaml")
```

---

## 6. Data Quality & Validation

Data quality gates prevent garbage-in-garbage-out. A model trained on corrupted, stale, or biased data will produce confidently wrong answers. Validate before every training run.

### Tool Comparison

| Feature | Great Expectations | Evidently | Pandera |
|---|---|---|---|
| **Focus** | Data validation & testing | ML monitoring & drift | DataFrame schema validation |
| **Best for** | Pipeline data gates | Production monitoring | Type-safe DataFrames |
| **Complexity** | Medium | Low | Low |
| **Output** | HTML reports, JSON | Dashboards, JSON | Exceptions |
| **Integration** | Airflow, Spark, K8s | Grafana, MLflow | Pandas, Polars |

### Code Example: Validate Training Data Before Training

```python
# Using Great Expectations for pre-training data validation
import great_expectations as gx
import pandas as pd

def validate_training_data(data_path: str) -> bool:
    """
    Run data quality checks before training.
    Fails fast if data is corrupt, incomplete, or anomalous.
    """
    context = gx.get_context()

    # Load dataset
    df = pd.read_parquet(data_path)

    # Define expectations
    validator = context.sources.pandas_default.read_dataframe(df)

    # Schema checks
    validator.expect_column_to_exist("prompt")
    validator.expect_column_to_exist("completion")
    validator.expect_column_to_exist("source")

    # Completeness checks
    validator.expect_column_values_to_not_be_null("prompt")
    validator.expect_column_values_to_not_be_null("completion")

    # Volume checks (catch truncated datasets)
    validator.expect_table_row_count_to_be_between(min_value=1000, max_value=500000)

    # Content quality checks
    validator.expect_column_value_lengths_to_be_between(
        "prompt", min_value=10, max_value=10000
    )
    validator.expect_column_value_lengths_to_be_between(
        "completion", min_value=5, max_value=50000
    )

    # Distribution checks (catch data drift)
    validator.expect_column_unique_value_count_to_be_between(
        "source", min_value=3, max_value=50
    )

    # No duplicates
    validator.expect_compound_columns_to_be_unique(["prompt", "completion"])

    results = validator.validate()

    if not results.success:
        failed = [r for r in results.results if not r.success]
        for f in failed:
            print(f"FAILED: {f.expectation_config.expectation_type}")
        raise ValueError(f"Data validation failed: {len(failed)} checks failed")

    print(f"Data validation passed: {len(results.results)} checks OK")
    return True


# Using Pandera for type-safe schema validation
import pandera as pa

training_schema = pa.DataFrameSchema({
    "prompt": pa.Column(str, nullable=False, checks=[
        pa.Check.str_length(min_value=10, max_value=10000),
    ]),
    "completion": pa.Column(str, nullable=False, checks=[
        pa.Check.str_length(min_value=5, max_value=50000),
    ]),
    "source": pa.Column(str, nullable=False),
    "created_at": pa.Column("datetime64[ns]", nullable=False),
    "quality_score": pa.Column(float, checks=[
        pa.Check.in_range(0.0, 1.0),
        pa.Check(lambda s: s.mean() > 0.7, error="Mean quality score too low"),
    ]),
})

# Validate — raises SchemaError if invalid
validated_df = training_schema.validate(df)
```

---

## 7. Drift Detection

### Types of Drift

| Drift Type | What Changed | Example | Detection Method |
|---|---|---|---|
| **Data drift** | Input distribution shifted | Users started asking about a new product not in training data | PSI, KS test, Jensen-Shannon divergence |
| **Concept drift** | Relationship between inputs and outputs changed | Regulatory change made previously correct answers wrong | Monitor prediction quality over time |
| **Prediction drift** | Model output distribution shifted | Model suddenly outputting longer responses | Track output statistics |
| **Embedding drift** | Semantic shift in inputs | Query topics shifted from technical to business questions | Cosine similarity of embedding centroids |

### Detection Methods

**Population Stability Index (PSI)** — Compares two distributions. PSI < 0.1: no drift. PSI 0.1-0.25: moderate drift. PSI > 0.25: significant drift.

```python
import numpy as np

def calculate_psi(reference: np.ndarray, current: np.ndarray, bins: int = 10) -> float:
    """Calculate Population Stability Index between reference and current distributions."""
    # Bin the data
    breakpoints = np.percentile(reference, np.linspace(0, 100, bins + 1))
    breakpoints[-1] = np.inf
    breakpoints[0] = -np.inf

    ref_counts = np.histogram(reference, breakpoints)[0] / len(reference)
    cur_counts = np.histogram(current, breakpoints)[0] / len(current)

    # Avoid division by zero
    ref_counts = np.maximum(ref_counts, 0.0001)
    cur_counts = np.maximum(cur_counts, 0.0001)

    psi = np.sum((cur_counts - ref_counts) * np.log(cur_counts / ref_counts))
    return psi

# Usage
psi_score = calculate_psi(reference_data, current_data)
if psi_score > 0.25:
    trigger_retraining()
```

**Embedding Drift for LLMs** — Compare centroid of embedding distributions.

```python
from scipy.spatial.distance import cosine

def detect_embedding_drift(
    reference_embeddings: np.ndarray,
    current_embeddings: np.ndarray,
    threshold: float = 0.15
) -> bool:
    """Detect drift in embedding space by comparing centroids."""
    ref_centroid = reference_embeddings.mean(axis=0)
    cur_centroid = current_embeddings.mean(axis=0)

    drift_score = cosine(ref_centroid, cur_centroid)
    print(f"Embedding drift score: {drift_score:.4f} (threshold: {threshold})")
    return drift_score > threshold
```

### Evidently Integration Example

```python
from evidently import ColumnMapping
from evidently.report import Report
from evidently.metric_preset import DataDriftPreset, TargetDriftPreset
from evidently.metrics import EmbeddingsDriftMetric

# Data drift report
drift_report = Report(metrics=[
    DataDriftPreset(),
    TargetDriftPreset(),
])

drift_report.run(
    reference_data=reference_df,
    current_data=current_df,
    column_mapping=ColumnMapping(
        target="quality_label",
        numerical_features=["response_length", "latency_ms", "confidence"],
        categorical_features=["model_version", "query_type"],
    )
)

# Extract results programmatically
results = drift_report.as_dict()
dataset_drift = results["metrics"][0]["result"]["dataset_drift"]

if dataset_drift:
    print("DRIFT DETECTED — triggering retraining pipeline")
    # Trigger Argo Workflow
    trigger_argo_workflow("training-pipeline", {
        "reason": "data_drift_detected",
        "drift_score": results["metrics"][0]["result"]["drift_share"],
    })

# Save report for debugging
drift_report.save_html("drift_report.html")
```

### Automated Retraining Trigger Architecture

```
Inference Logs → Kafka → Drift Detector (CronJob, hourly)
                              ↓ drift detected
                         Argo Event → Argo Workflow (retrain)
                              ↓ model registered
                         MLflow → Canary Deploy → Monitor
```

```yaml
# CronJob for drift detection
apiVersion: batch/v1
kind: CronJob
metadata:
  name: drift-detector
spec:
  schedule: "0 */4 * * *"  # Every 4 hours
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: detector
            image: ml-pipeline/drift-detector:latest
            env:
            - name: REFERENCE_DATA_PATH
              value: "s3://ml-data/reference/baseline.parquet"
            - name: INFERENCE_LOG_TABLE
              value: "inference_logs"
            - name: ARGO_WEBHOOK_URL
              value: "http://argo-events.argo:12000/training-trigger"
            - name: PSI_THRESHOLD
              value: "0.25"
          restartPolicy: OnFailure
```

---

## 8. Feature Stores

### Feast Overview

Feast (Feature Store) provides a centralized registry and serving layer for ML features. It solves **training-serving skew** — the gap where features computed differently in training vs inference causes silent model degradation.

**Architecture:**

```
Offline Store (BigQuery/Redshift/S3)
  ↓ materialize
Online Store (Redis/DynamoDB)
  ↓ serve
Inference Service (low-latency feature lookup)
```

```python
# feast feature definition (feature_store.yaml + features.py)
from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32, String
from datetime import timedelta

# Define entity
user = Entity(name="user_id", join_keys=["user_id"])

# Define feature view
user_features = FeatureView(
    name="user_features",
    entities=[user],
    ttl=timedelta(days=1),
    schema=[
        Field(name="avg_query_length", dtype=Float32),
        Field(name="queries_per_day", dtype=Float32),
        Field(name="preferred_language", dtype=String),
        Field(name="subscription_tier", dtype=String),
    ],
    source=FileSource(
        path="data/user_features.parquet",
        timestamp_field="event_timestamp",
    ),
)

# Fetch features for training (point-in-time correct)
training_df = store.get_historical_features(
    entity_df=entity_df,  # DataFrame with user_id + event_timestamp
    features=["user_features:avg_query_length", "user_features:queries_per_day"],
).to_df()

# Fetch features for inference (online, low-latency)
features = store.get_online_features(
    features=["user_features:avg_query_length", "user_features:queries_per_day"],
    entity_rows=[{"user_id": "user_123"}],
).to_dict()
```

### When You Need a Feature Store vs When You Don't

**You need a feature store when:**
- Multiple models share the same features
- Features require complex aggregations (rolling windows, cross-entity joins)
- Training-serving skew is causing production issues
- You need point-in-time correct feature retrieval for training

**You probably don't need one for LLM applications:**
- RAG replaces traditional features — context is retrieved from vector stores, not feature stores
- LLM inputs are primarily text (prompts, documents), not tabular features
- Fine-tuning uses instruction datasets, not feature tables

**For this repo:** A feature store is not needed. RAG retrieval from pgvector replaces the feature lookup pattern. If you later add a recommendation or fraud detection model alongside the LLM, revisit Feast.

---

## 9. CI/CD for ML

### How ML CI/CD Differs from Software CI/CD

| Aspect | Software CI/CD | ML CI/CD |
|---|---|---|
| **Artifact** | Container image | Container image + model weights |
| **Tests** | Unit, integration, e2e | + data validation, model evaluation |
| **Quality gate** | Tests pass | Tests pass + eval metrics above threshold |
| **Deployment** | Blue-green or canary | Canary with quality monitoring (shadow mode first) |
| **Rollback trigger** | Error rate, latency | + quality score degradation, drift detection |
| **Versioning** | Git SHA | Git SHA + model version + dataset version |

### GitHub Actions Pipeline: Full ML CI/CD

```yaml
name: ML Pipeline
on:
  push:
    branches: [main]
    paths:
      - 'models/**'
      - 'training/**'
      - 'data/**'

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - name: Lint
      run: |
        pip install ruff
        ruff check models/ training/
    - name: Unit tests
      run: pytest tests/unit/ -v

  data-validation:
    runs-on: ubuntu-latest
    needs: lint-and-test
    steps:
    - name: Validate training data
      run: python scripts/validate_data.py --dataset s3://data/training/latest

  train:
    runs-on: [self-hosted, gpu]
    needs: data-validation
    steps:
    - name: Train model
      run: |
        python training/train.py \
          --config configs/production.yaml \
          --output /models/output
      env:
        MLFLOW_TRACKING_URI: ${{ secrets.MLFLOW_URI }}

    - name: Upload model artifact
      uses: actions/upload-artifact@v4
      with:
        name: model-weights
        path: /models/output/

  evaluate:
    runs-on: [self-hosted, gpu]
    needs: train
    steps:
    - name: Download model
      uses: actions/download-artifact@v4
      with:
        name: model-weights

    - name: Run evaluation suite
      id: eval
      run: |
        python evaluation/evaluate.py \
          --model-path ./model-weights \
          --benchmark mmlu,humaneval,custom_rag \
          --output eval_results.json

    - name: Check evaluation gate
      run: |
        python scripts/check_eval_gate.py \
          --results eval_results.json \
          --min-rouge-l 0.85 \
          --max-latency-p99-ms 500 \
          --min-accuracy 0.90
      # This step FAILS the pipeline if metrics are below thresholds

  register:
    runs-on: ubuntu-latest
    needs: evaluate
    steps:
    - name: Register model in MLflow
      run: |
        python scripts/register_model.py \
          --model-path ./model-weights \
          --name "rag-generator" \
          --stage "Staging"
      env:
        MLFLOW_TRACKING_URI: ${{ secrets.MLFLOW_URI }}

  deploy-canary:
    runs-on: ubuntu-latest
    needs: register
    environment: production  # Requires manual approval
    steps:
    - name: Deploy canary (5% traffic)
      run: |
        kubectl apply -f k8s/canary-deployment.yaml
        kubectl patch virtualservice model-vs \
          --type merge \
          -p '{"spec":{"http":[{"route":[
            {"destination":{"host":"model-v2","port":{"number":8000}},"weight":5},
            {"destination":{"host":"model-v1","port":{"number":8000}},"weight":95}
          ]}]}}'

    - name: Monitor canary (30 min)
      run: |
        python scripts/monitor_canary.py \
          --duration 1800 \
          --error-threshold 0.01 \
          --latency-p99-threshold 500

    - name: Promote to full traffic
      if: success()
      run: |
        kubectl patch virtualservice model-vs \
          --type merge \
          -p '{"spec":{"http":[{"route":[
            {"destination":{"host":"model-v2","port":{"number":8000}},"weight":100}
          ]}]}}'
```

---

## 10. Notable Open-Source Repos

### MLOps & Pipeline Infrastructure

| Repo | Stars | What It Teaches |
|---|---|---|
| [mlflow/mlflow](https://github.com/mlflow/mlflow) | 19k+ | Experiment tracking, model registry, model serving. The standard MLOps platform. |
| [kubeflow/kubeflow](https://github.com/kubeflow/kubeflow) | 14k+ | Full ML platform on K8s: pipelines, notebooks, training operators, serving. |
| [iterative/dvc](https://github.com/iterative/dvc) | 14k+ | Git-native data/model versioning. Pipeline reproducibility. |
| [zenml-io/zenml](https://github.com/zenml-io/zenml) | 4k+ | Orchestrator-agnostic MLOps framework. Clean abstractions over pipelines. |
| [feast-dev/feast](https://github.com/feast-dev/feast) | 5k+ | Feature store: offline/online serving, point-in-time joins. |

### Model Serving & Inference

| Repo | Stars | What It Teaches |
|---|---|---|
| [vllm-project/vllm](https://github.com/vllm-project/vllm) | 40k+ | LLM inference engine. PagedAttention, continuous batching, tensor parallelism. |
| [kserve/kserve](https://github.com/kserve/kserve) | 3k+ | K8s-native model serving with autoscaling, canary, multi-model. |
| [BentoML/BentoML](https://github.com/BentoML/BentoML) | 7k+ | Model packaging and serving framework. Great for custom inference logic. |
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | 15k+ | Unified API proxy for 100+ LLM providers. Cost tracking, rate limiting, fallbacks. |
| [llm-d](https://github.com/llm-d/llm-d) | New | K8s-native LLM serving with disaggregated prefill/decode. Production LLM infra patterns. |

### Monitoring & Data Quality

| Repo | Stars | What It Teaches |
|---|---|---|
| [evidentlyai/evidently](https://github.com/evidentlyai/evidently) | 5k+ | ML monitoring: data drift, model quality, target drift. Grafana integration. |
| [great-expectations/great_expectations](https://github.com/great-expectations/great_expectations) | 10k+ | Data validation framework. Expectations as tests for data pipelines. |
| [whylabs/whylogs](https://github.com/whylabs/whylogs) | 2k+ | Statistical profiling for data and ML monitoring. Lightweight drift detection. |

### LLM Application Frameworks

| Repo | Stars | What It Teaches |
|---|---|---|
| [langchain-ai/langchain](https://github.com/langchain-ai/langchain) | 95k+ | LLM application framework. Chains, agents, RAG patterns. |
| [langfuse/langfuse](https://github.com/langfuse/langfuse) | 7k+ | LLM observability: tracing, evaluation, prompt management. |
| [infiniflow/ragflow](https://github.com/infiniflow/ragflow) | 30k+ | RAG engine with deep document understanding. Chunking strategies, quality control. |
| [langgenius/dify](https://github.com/langgenius/dify) | 55k+ | LLM app development platform. Visual workflow builder, RAG, agent orchestration. |

### Worth Studying Deeply (Top 5 for Interview Prep)

1. **vLLM** — Read the PagedAttention paper and serving architecture. Understand continuous batching, KV cache management, tensor parallelism. This comes up in every AI infrastructure interview.
2. **MLflow** — Set up locally, log experiments, register models. Be able to describe the full model lifecycle.
3. **Evidently** — Run a drift detection report. Understand PSI, KS test, embedding drift.
4. **KServe** — Understand InferenceService CRD, canary rollouts, scale-to-zero. Compare with raw K8s Deployments.
5. **llm-d** — Newest entrant. Understand disaggregated serving (separate prefill and decode phases). This is the future of LLM serving.

---

## 11. Interview Q&As

### Q1: "Walk me through your MLOps pipeline from training to production."

**Answer:** "Our pipeline has five stages. First, data validation — we run Great Expectations checks on the training dataset to catch schema violations, missing values, and distribution anomalies before any training starts. Second, training — triggered by Argo Workflows, runs on GPU nodes, logs everything to MLflow (hyperparameters, metrics, artifacts, dataset version via DVC hash). Third, evaluation — automated benchmarks: ROUGE-L, latency P99, accuracy on held-out test set. The pipeline fails if metrics drop below our thresholds. Fourth, registration — the model is registered in MLflow Model Registry as 'Staging'. Fifth, deployment — canary rollout via Istio VirtualService: 5% traffic for 30 minutes, monitor error rate and latency, then promote to 100%. We can trigger this pipeline manually, on a schedule, or automatically when our drift detector fires."

### Q2: "How do you handle model versioning and rollback?"

**Answer:** "We version three things independently: code (Git), data (DVC), and model weights (MLflow Model Registry). Every training run records the Git SHA, DVC dataset hash, and produces a model version in MLflow. For rollback, we keep the previous model version running alongside the canary — rollback is just shifting the Istio VirtualService weight back to 100% on the old version. The old model container is still running, so rollback takes seconds, not minutes. For deeper rollback (retrain on previous data), we checkout the Git commit and DVC version, which gives us the exact code and data to reproduce the old model."

### Q3: "How would you detect that a deployed model is degrading in production?"

**Answer:** "Three layers. First, operational monitoring — standard metrics: latency P50/P99, error rate, throughput, GPU utilization via Prometheus/Grafana. Second, data drift detection — we run Evidently reports every 4 hours comparing current inference inputs against the training distribution. We track PSI for numerical features and embedding centroid drift for text inputs. PSI above 0.25 triggers an alert. Third, output quality monitoring — for LLM outputs, we track response length distribution, confidence scores, and run periodic LLM-as-judge evaluations on sampled outputs. If quality drops below threshold, we trigger a retraining pipeline automatically via Argo Events."

### Q4: "You mentioned feature stores — when would you use one for an LLM application?"

**Answer:** "Honestly, for most LLM applications, you don't need a traditional feature store. The RAG pattern replaces feature lookup — instead of computing features, you retrieve relevant documents from a vector store. However, there are cases where a feature store adds value even in LLM apps: if you're personalizing responses using user behavior features (query history, preferences), if you're doing hybrid retrieval that combines structured features with semantic search, or if you have a multi-model system where some models are traditional ML (recommendations, fraud detection) alongside the LLM. In that hybrid case, Feast online serving prevents training-serving skew for the traditional models."

### Q5: "How does CI/CD for ML differ from traditional software CI/CD?"

**Answer:** "Three key differences. First, the quality gate — software CI/CD gates on tests passing. ML CI/CD has an additional evaluation gate where we run the model against benchmarks and check that metrics meet thresholds. A model that passes all unit tests but has low accuracy should not deploy. Second, the artifact — we're not just shipping code in a container, we're shipping code plus model weights. Both need versioning, and the weights can be gigabytes. Third, rollback is harder — in software, rolling back a container is straightforward. In ML, you need to keep the previous model loaded and ready (warm standby), because loading a new model takes minutes due to weight loading. Our canary deployment pattern handles this by keeping both versions running simultaneously."

---

*Last updated: 2026-03-18*
