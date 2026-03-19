# Scientist-to-Production Workflow

How data scientists and ML engineers work day-to-day on this platform, what they change, how they measure things, and where DevOps/MLOps fits in. Written for someone with deep infrastructure experience who needs to understand the scientist side of the house.

---

## 1. The Two Roles and How They Interact

```
SCIENTIST (Data Scientist / ML Engineer)         DEVOPS / MLOPS ENGINEER
─────────────────────────────────────────         ──────────────────────────
Experiments in JupyterLab                         Provides the platform (K3s/EKS)
Writes Python (LangChain, PyTorch, sklearn)       Writes Terraform, K8s YAML, Dockerfiles
Measures: accuracy, latency, cost/token           Measures: uptime, throughput, cost
Changes: prompts, models, hyperparameters         Changes: infra, scaling, pipelines
Outputs: notebooks -> scripts -> services         Outputs: clusters, CI/CD, monitoring
Thinks in: experiments, hypotheses, metrics       Thinks in: SLOs, capacity, reliability
```

### The Feedback Loop

This is the core dynamic. Neither role works in isolation -- they form a continuous loop:

```
 ┌──────────────────────────────────────────────────────────────────┐
 │                                                                  │
 │   SCIENTIST discovers                   DEVOPS makes it          │
 │   something in Jupyter   ──────────>    production-ready         │
 │                                              │                   │
 │                                              │                   │
 │                                              v                   │
 │   SCIENTIST investigates  <──────────   MONITORING reveals       │
 │   root cause in Jupyter                 new issues               │
 │                                                                  │
 └──────────────────────────────────────────────────────────────────┘
```

**Concrete example from this platform:**

1. Scientist tests a new RAG prompt template in JupyterLab, gets better answers
2. Scientist updates `services/rag-service/app/chains.py` with the new prompt
3. DevOps CI/CD (GitHub Actions) lints, tests, builds Docker image
4. ArgoCD auto-syncs the new image to K3s -- rolling update, zero downtime
5. Grafana shows p95 latency spiked (new prompt generates longer answers)
6. Scientist opens Jupyter, experiments with `max_tokens` and prompt constraints
7. Loop repeats

### What Scientists Do NOT Touch

Scientists generally avoid (and expect DevOps to handle):

- Kubernetes YAML (deployments, services, ingress)
- Docker image optimization (multi-stage builds, layer caching)
- CI/CD pipeline configuration (GitHub Actions workflows)
- Terraform / infrastructure provisioning
- Monitoring stack setup (Prometheus, Grafana, ServiceMonitors)
- Secrets management (K8s Secrets, external secret stores)
- Network policies, RBAC, security hardening
- Cost optimization (KEDA, spot instances, right-sizing)

### What DevOps Does NOT Touch

DevOps generally avoids (and expects scientists to own):

- Model selection and hyperparameter tuning
- Prompt engineering and chain design
- Training data curation and labeling
- Evaluation metrics and quality benchmarks
- LangChain/LlamaIndex chain logic
- Experiment tracking (W&B runs, LangFuse traces)
- Research paper implementation

---

## 2. JupyterLab to Service Promotion Workflow

This is the most common workflow in the platform. A scientist has an idea, validates it in Jupyter, then promotes it to a production service.

### Stage 1: Explore in JupyterLab

The scientist opens JupyterLab. On this platform, Jupyter runs as a pod inside the K3s cluster (`k8s/base/jupyter/deployment.yaml`), so it has direct network access to all services via K8s DNS.

```bash
# Access JupyterLab (token is "genai", set in the deployment)
kubectl port-forward svc/jupyter -n genai 8888:8888
# Open http://localhost:8888
```

Here is what a real notebook session looks like:

```python
# ============================================================
# Cell 1: Connect to platform services (K8s DNS just works)
# ============================================================
import os
import httpx

# These env vars are pre-set in the Jupyter deployment
# (see k8s/base/jupyter/deployment.yaml)
VLLM_BASE_URL = os.getenv("VLLM_BASE_URL", "http://inference:8000/v1")
EMBEDDING_URL = os.getenv("EMBEDDING_URL", "http://embedding:8000")
PGVECTOR_HOST = os.getenv("PGVECTOR_HOST", "pgvector")

# Quick health check -- are services up?
for name, url in [("vLLM", "http://inference:8000/health"),
                   ("Embedding", f"{EMBEDDING_URL}/health")]:
    try:
        r = httpx.get(url, timeout=5)
        print(f"{name}: {r.json()['status']}")
    except Exception as e:
        print(f"{name}: DOWN ({e})")
```

```python
# ============================================================
# Cell 2: Test the current RAG chain (baseline)
# ============================================================
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

llm = ChatOpenAI(
    base_url=VLLM_BASE_URL,
    api_key="not-needed",
    model="Qwen/Qwen2.5-1.5B-Instruct",
    temperature=0.1,
    max_tokens=512,
)

# Test a simple question
response = llm.invoke("What is retrieval-augmented generation?")
print(response.content)
```

```python
# ============================================================
# Cell 3: Try a different retrieval strategy
# ============================================================
# The current chain uses basic similarity search (top-5).
# Scientist wants to test: multi-query retriever (generates
# multiple search queries from one question for better recall).

from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_community.vectorstores.pgvector import PGVector

# Connect to the same pgvector used by rag-service
vectorstore = PGVector(
    connection="postgresql+psycopg://postgres:postgres@pgvector:5432/vectordb",
    collection_name="documents",
    embedding_function=embedding_client,  # RemoteEmbeddings from Cell 1
)

# Current approach: simple similarity
baseline_retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

# New approach: multi-query (LLM generates 3 variations of the question)
multi_query_retriever = MultiQueryRetriever.from_llm(
    retriever=baseline_retriever,
    llm=llm,
)
```

```python
# ============================================================
# Cell 4: Compare results side-by-side
# ============================================================
import time

test_questions = [
    "How does the embedding service handle batch requests?",
    "What GPU resources does vLLM need?",
    "How is data ingested into the knowledge base?",
]

for q in test_questions:
    print(f"\n{'='*60}")
    print(f"Q: {q}")

    # Baseline
    t0 = time.time()
    baseline_docs = baseline_retriever.invoke(q)
    baseline_time = time.time() - t0
    print(f"\nBaseline ({baseline_time:.2f}s): {len(baseline_docs)} docs")
    for d in baseline_docs[:2]:
        print(f"  - {d.page_content[:80]}...")

    # Multi-query
    t0 = time.time()
    mq_docs = multi_query_retriever.invoke(q)
    mq_time = time.time() - t0
    print(f"\nMulti-query ({mq_time:.2f}s): {len(mq_docs)} docs")
    for d in mq_docs[:2]:
        print(f"  - {d.page_content[:80]}...")
```

```python
# ============================================================
# Cell 5: Measure quality and plot latency distribution
# ============================================================
import matplotlib.pyplot as plt
import numpy as np

# Run 50 queries, measure latency for each approach
baseline_latencies = []
multiquery_latencies = []

for q in test_questions * 15:  # Repeat for statistical significance
    t0 = time.time()
    baseline_retriever.invoke(q)
    baseline_latencies.append(time.time() - t0)

    t0 = time.time()
    multi_query_retriever.invoke(q)
    multiquery_latencies.append(time.time() - t0)

fig, axes = plt.subplots(1, 2, figsize=(14, 5))

axes[0].hist(baseline_latencies, bins=20, alpha=0.7, label='Baseline')
axes[0].hist(multiquery_latencies, bins=20, alpha=0.7, label='Multi-query')
axes[0].set_xlabel('Latency (seconds)')
axes[0].set_title('Retrieval Latency Distribution')
axes[0].legend()

# Box plot
axes[1].boxplot([baseline_latencies, multiquery_latencies],
                labels=['Baseline', 'Multi-query'])
axes[1].set_ylabel('Latency (seconds)')
axes[1].set_title('Latency Comparison')

plt.tight_layout()
plt.show()

print(f"Baseline  - p50: {np.percentile(baseline_latencies, 50):.3f}s, "
      f"p95: {np.percentile(baseline_latencies, 95):.3f}s")
print(f"Multi-Q   - p50: {np.percentile(multiquery_latencies, 50):.3f}s, "
      f"p95: {np.percentile(multiquery_latencies, 95):.3f}s")
```

**Key observation:** The scientist is iterating fast. Each cell takes seconds to run. They are testing hypotheses, comparing approaches, and measuring results -- all without touching any infrastructure.

### Stage 2: Extract to Script

Once the notebook produces a winner, the scientist extracts the core logic into a Python module. This is where messy notebook code becomes production code.

**What changes during extraction:**

| Notebook Code | Production Code |
|---|---|
| `print()` statements | `logger.info()` with structured logging |
| Hardcoded values | `Settings` class with env var overrides |
| No error handling | `try/except` with meaningful error responses |
| Inline embedding client | `RemoteEmbeddings` class (see `main.py`) |
| No metrics | Prometheus histograms and counters |
| No health checks | `/health` endpoint for K8s probes |

The file mapping for this example:

```
notebooks/rag_multi_query_experiment.ipynb

    Extracted to:

services/rag-service/app/chains.py    <-- chain logic (already exists, gets updated)
services/rag-service/app/config.py    <-- new config parameters
services/rag-service/app/main.py      <-- endpoint changes
```

Here is what the scientist actually changes in `chains.py` (from this repo):

```python
# BEFORE (current code in services/rag-service/app/chains.py):
def create_rag_chain(embedding: Embeddings):
    vectorstore = create_vectorstore(embedding)
    retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": settings.retrieval_top_k},
    )
    # ... rest of chain

# AFTER (scientist's improvement):
def create_rag_chain(embedding: Embeddings):
    vectorstore = create_vectorstore(embedding)
    base_retriever = vectorstore.as_retriever(
        search_type="similarity",
        search_kwargs={"k": settings.retrieval_top_k},
    )

    # Multi-query retriever: generates 3 query variations for better recall
    if settings.use_multi_query:
        llm = create_llm()
        retriever = MultiQueryRetriever.from_llm(
            retriever=base_retriever,
            llm=llm,
        )
    else:
        retriever = base_retriever

    # ... rest of chain
```

And in `config.py`:

```python
# Scientist adds one new parameter
use_multi_query: bool = True  # Toggle multi-query retrieval
```

### Stage 3: Test Locally

Before pushing, the scientist tests the service locally:

```bash
# From the repo root
cd services/rag-service

# Start with docker-compose (talks to real cluster services via port-forward)
# Or just run directly:
RAG_VLLM_BASE_URL=http://localhost:8000/v1 \
RAG_EMBEDDING_URL=http://localhost:8002 \
RAG_PGVECTOR_HOST=localhost \
uvicorn app.main:app --host 0.0.0.0 --port 8080

# Test it
curl -X POST http://localhost:8080/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How does the embedding service work?"}'
```

### Stage 4: Push and ArgoCD Deploys

```bash
git add services/rag-service/app/chains.py services/rag-service/app/config.py
git commit -m "feat(rag): add multi-query retriever for improved recall

Tested in Jupyter: multi-query retrieval improves doc relevance by ~15%
at a cost of ~2x retrieval latency (acceptable, still under 500ms p95)"
git push origin main
```

What happens automatically (defined in `.github/workflows/ci.yaml` and `k8s/argocd/application.yaml`):

```
git push
    |
    v
GitHub Actions CI (.github/workflows/ci.yaml)
    1. ruff check .                    (lint)
    2. ruff format --check .           (format)
    3. pytest tests/                   (unit tests)
    4. docker build + push             (ghcr.io/lehph/genai-rag-service:latest)
    |
    v
ArgoCD (k8s/argocd/application.yaml)
    - Watches: main branch, k8s/overlays/dev path
    - Auto-sync: enabled (automated.prune + selfHeal)
    - Detects image tag change -> rolling update
    - Zero downtime: K8s rolling update strategy
    |
    v
RAG service pods restart with new code
Prometheus scrapes new pod -> Grafana shows metrics
```

### Stage 5: Monitor in LangFuse + Grafana

After deployment, both roles check different things:

**Scientist checks LangFuse** (`kubectl port-forward svc/langfuse -n genai 3000:3000`):

```python
# To send traces to LangFuse, add the callback handler:
from langfuse.callback import CallbackHandler

langfuse_handler = CallbackHandler(
    public_key="pk-...",
    secret_key="sk-...",
    host="http://langfuse:3000"  # K8s DNS
)

# Every chain invocation is now traced:
chain.invoke(input, config={"callbacks": [langfuse_handler]})

# In LangFuse UI, scientist sees:
# - Trace waterfall: embedding -> retrieval -> generation (time breakdown)
# - Token usage per request (input tokens from context, output tokens from answer)
# - Cost per trace (tokens * model pricing)
# - Quality scores (if evaluation pipeline is set up)
```

**DevOps checks Grafana** (`kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80`):

The platform includes a pre-built dashboard (see `k8s/base/monitoring/prometheus-stack.yaml`):

- **Row 1**: vLLM active requests, waiting requests (queue depth)
- **Row 2**: vLLM latency (p50/p95/p99), time-to-first-token
- **Row 3**: GPU KV cache usage (gauge, red at >90%)
- **Row 4**: RAG query latency, retrieval vs generation time, token rates

**If metrics degrade after deployment:**

```bash
# DevOps: quick rollback via ArgoCD
argocd app rollback genai-platform

# Or revert the git commit (ArgoCD will auto-sync the revert)
git revert HEAD
git push

# Scientist: investigate in Jupyter
# - Why did latency spike? Multi-query adds 3x LLM calls for query generation
# - Solution: cache generated queries, or reduce from 3 to 2 variations
```

---

## 3. How Scientists Train and Fine-Tune Models

This platform supports the full training lifecycle, from raw data to a LoRA adapter running in production on vLLM.

### 3.1 Data Preparation

```
Raw Data (CSV/JSON/Parquet)                      WHERE IT LIVES
    |                                            ──────────────
    v
Jupyter: explore, clean, analyze (Pandas)        JupyterLab pod (notebooks PVC)
    |
    v
pipelines/preprocessing/preprocess.py            Git repo (extracted script)
    |
    v
K8s Job: kubectl apply -f preprocessing-job.yaml Runs in cluster (CPU, no GPU)
    |                                            Image: ghcr.io/lehph/genai-preprocessing
    v
Clean data in S3 (s3://genai-data/processed/)   Or training-data PVC
```

**What the scientist does in Jupyter for data prep:**

```python
# ============================================================
# Cell 1: Load and explore raw data
# ============================================================
import pandas as pd

df = pd.read_csv("/home/jovyan/notebooks/data/raw_qa_pairs.csv")
print(f"Shape: {df.shape}")
print(f"Columns: {df.columns.tolist()}")
print(f"Sample:\n{df.head()}")

# Check for problems
print(f"\nNull counts:\n{df.isnull().sum()}")
print(f"\nDuplicate rows: {df.duplicated().sum()}")
print(f"\nText length stats:\n{df['instruction'].str.len().describe()}")
```

```python
# ============================================================
# Cell 2: Clean and filter
# ============================================================
# Remove very short instructions (likely noise)
df = df[df['instruction'].str.len() >= 20]

# Remove duplicates
df = df.drop_duplicates(subset=['instruction'])

# Remove rows where output is empty
df = df.dropna(subset=['output'])

print(f"After cleaning: {len(df)} rows")
```

```python
# ============================================================
# Cell 3: Format for training
# ============================================================
# The training script (pipelines/training/train.py) expects this format:
#   {"instruction": "...", "input": "...", "output": "..."}

# Verify format
sample = df.iloc[0]
print(f"instruction: {sample['instruction'][:100]}")
print(f"input: {sample.get('input', 'N/A')}")
print(f"output: {sample['output'][:100]}")

# Export
df.to_json("/home/jovyan/notebooks/data/train.jsonl",
           orient="records", lines=True, force_ascii=False)
print(f"Saved {len(df)} examples to train.jsonl")
```

Once the scientist is happy with the data cleaning logic, they extract it into `pipelines/preprocessing/preprocess.py` (already exists in this repo). The preprocessing pipeline handles:

- Loading from local files or S3
- Dropping null rows
- Cleaning text (whitespace normalization, null byte removal)
- Filtering by minimum text length
- Deduplication
- Random sampling (for quick experiments)
- Saving to JSONL/CSV/Parquet (local or S3)

**Running as a K8s Job** (`pipelines/k8s-jobs/preprocessing-job.yaml`):

```bash
# Edit the Job YAML to point to your data
kubectl apply -f pipelines/k8s-jobs/preprocessing-job.yaml

# Watch it run
kubectl logs -f job/data-preprocessing -n genai

# Check output
# Job writes to: s3://genai-data/processed/train.jsonl
```

### 3.2 Fine-Tuning (LoRA)

This is where the scientist spends most of their iteration time. The goal: adapt a pre-trained model to perform better on your specific task.

**What scientists actually change between experiments:**

| Parameter | Typical Range | Impact | What Scientist Thinks |
|---|---|---|---|
| **Base model** | Qwen2.5-1.5B -> 7B -> 72B | Bigger = smarter but slower, more VRAM | "Can the small model handle this, or do I need 7B?" |
| **LoRA rank (r)** | 4, 8, 16, 32, 64 | Higher = more trainable params, more capacity | "r=16 worked, let me try r=32 to see if quality improves" |
| **LoRA alpha** | Usually 2x rank | Scaling factor for LoRA weights | "Keep at 2x rank, not worth tuning" |
| **Learning rate** | 1e-5 to 5e-4 | Most impactful hyperparameter | "Too high = unstable loss; too low = no learning" |
| **Epochs** | 1-5 | More = overfitting risk | "Loss still dropping at epoch 2, try 3" |
| **Batch size** | 1-16 | Larger = smoother gradients, more VRAM | "4 fits in VRAM with gradient accumulation" |
| **Dataset** | Varies | Garbage in, garbage out | "Added 200 more examples, fixed 50 bad labels" |
| **Prompt template** | Custom format | How input/output is structured | "ChatML vs Alpaca format?" |
| **Max seq length** | 512-8192 | Longer = more context, more VRAM | "2048 is enough for our use case" |

**Typical experiment session in Jupyter:**

```python
# ============================================================
# Cell 1: Load model with Unsloth (4-bit quantized)
# ============================================================
from unsloth import FastLanguageModel

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="Qwen/Qwen2.5-1.5B-Instruct",
    max_seq_length=2048,
    dtype=None,          # auto-detect (bf16 on Ampere+, fp16 otherwise)
    load_in_4bit=True,   # 4-bit quantization: 1.5B model fits in ~1.5GB VRAM
)

# Check VRAM usage
import torch
print(f"VRAM used: {torch.cuda.memory_allocated() / 1e9:.2f} GB")
print(f"VRAM total: {torch.cuda.get_device_properties(0).total_mem / 1e9:.2f} GB")
```

```python
# ============================================================
# Cell 2: Apply LoRA adapter
# ============================================================
model = FastLanguageModel.get_peft_model(
    model,
    r=16,               # LoRA rank -- scientist tries 8, 16, 32
    lora_alpha=32,       # Scaling factor (2x rank)
    lora_dropout=0.05,
    target_modules=[     # Which layers to adapt
        "q_proj", "k_proj", "v_proj", "o_proj",   # Attention
        "gate_proj", "up_proj", "down_proj",       # MLP (FFN)
    ],
    bias="none",
    use_gradient_checkpointing="unsloth",  # Saves VRAM
)

# How many parameters are trainable?
trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
total = sum(p.numel() for p in model.parameters())
print(f"Trainable: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")
# Output: Trainable: 6,815,744 / 1,543,714,816 (0.44%)
# Only 0.44% of parameters are trained -- this is why LoRA is fast and cheap
```

```python
# ============================================================
# Cell 3: Load training data
# ============================================================
from datasets import load_dataset

dataset = load_dataset("json", data_files="./data/train.jsonl", split="train")
print(f"Training examples: {len(dataset)}")
print(f"Sample: {dataset[0]}")

# Format for training (matches format_instruction in train.py)
def format_instruction(example):
    parts = []
    parts.append(f"### Instruction:\n{example['instruction']}")
    if example.get("input"):
        parts.append(f"### Input:\n{example['input']}")
    parts.append(f"### Response:\n{example['output']}")
    return "\n\n".join(parts)

# Preview
print(format_instruction(dataset[0]))
```

```python
# ============================================================
# Cell 4: Train with SFTTrainer
# ============================================================
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    formatting_func=format_instruction,
    max_seq_length=2048,
    args=TrainingArguments(
        output_dir="./checkpoints",
        per_device_train_batch_size=4,         # <-- scientist tweaks
        gradient_accumulation_steps=4,          # Effective batch = 4*4 = 16
        num_train_epochs=2,                     # <-- scientist tweaks
        learning_rate=2e-4,                     # <-- most important knob
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,                       # Print loss every 10 steps
        save_strategy="epoch",
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        optim="adamw_8bit",                     # 8-bit optimizer saves VRAM
        seed=42,
    ),
)

# This is the actual training loop
# On DGX Spark with 1.5B model, ~500 examples takes 5-15 minutes
trainer.train()
```

```python
# ============================================================
# Cell 5: Evaluate the trained model
# ============================================================
# Quick sanity check: does it answer better now?
FastLanguageModel.for_inference(model)

test_questions = [
    "How do I configure the RAG service?",
    "What embedding model does the platform use?",
    "How does KEDA scale-to-zero work?",
]

for q in test_questions:
    inputs = tokenizer(
        format_instruction({"instruction": q, "input": "", "output": ""}),
        return_tensors="pt"
    ).to("cuda")

    outputs = model.generate(**inputs, max_new_tokens=256, temperature=0.1)
    answer = tokenizer.decode(outputs[0], skip_special_tokens=True)
    print(f"Q: {q}")
    print(f"A: {answer.split('### Response:')[-1].strip()}\n")
```

```python
# ============================================================
# Cell 6: Save the adapter (if happy with results)
# ============================================================
# Save ONLY the LoRA adapter weights (not the full model)
# Adapter is ~25MB vs full model at ~3GB
model.save_pretrained("./checkpoints/lora-adapter-v3")
tokenizer.save_pretrained("./checkpoints/lora-adapter-v3")

print("Adapter saved. Ready for production.")
```

**How the scientist decides what to change next:**

```
Run 1: lr=2e-4, epochs=1, r=16  -> loss=1.82  -> "Loss high, try more epochs"
Run 2: lr=2e-4, epochs=3, r=16  -> loss=0.95  -> "Better, but overfitting at epoch 3"
Run 3: lr=2e-4, epochs=2, r=16  -> loss=1.05  -> "Sweet spot. Try higher rank"
Run 4: lr=2e-4, epochs=2, r=32  -> loss=0.98  -> "Slightly better, worth the VRAM"
Run 5: lr=1e-4, epochs=2, r=32  -> loss=1.10  -> "Lower LR = slower convergence"
Run 6: lr=3e-4, epochs=2, r=32  -> loss=0.92  -> "Winner! Best loss so far"
                                                   ^^^^^^^^^^^^^^^^^^^^^^^^
                                    Scientist picks this one for production
```

This is tracked in **Weights & Biases** (if WANDB_PROJECT is set in the training config) or manually in a spreadsheet.

### 3.3 Promote to Production

```
Jupyter (experiment with adapter)
    |
    | Extract to parameterized script
    v
pipelines/training/train.py
    |
    | Run as K8s Job with GPU
    v
kubectl apply -f pipelines/k8s-jobs/training-job.yaml
    |
    | K8s Job runs on GPU node:
    |   - Downloads base model from HuggingFace
    |   - Downloads dataset from S3
    |   - Trains LoRA adapter
    |   - Uploads adapter to S3
    v
S3: s3://genai-data/adapters/lora-adapter-v3/
    |
    | Update vLLM to load the adapter
    v
Update inference deployment args:
    --lora-modules my-adapter=s3://genai-data/adapters/lora-adapter-v3/
    |
    | ArgoCD deploys
    v
vLLM serves base model + LoRA adapter
    |
    | Monitor quality
    v
LangFuse + Grafana verify quality didn't degrade
```

The training K8s Job (`pipelines/k8s-jobs/training-job.yaml`) is already configured with:

- GPU request: `nvidia.com/gpu: "1"`
- Spot instance tolerations (cost savings)
- Configurable via environment variables (model, LoRA rank, epochs, etc.)
- S3 upload for the trained adapter
- Shared memory volume for GPU tensor operations

---

## 4. How Scientists Measure Things

Scientists live and die by metrics. Here is what they measure, why, and how.

### 4.1 RAG Quality Metrics

These metrics answer: "Is the RAG system returning good answers?"

**Retrieval metrics** (is the right information being found?):

```python
# ============================================================
# Precision@K: Of the K docs retrieved, how many are relevant?
# ============================================================
def precision_at_k(retrieved_docs, relevant_doc_ids, k=5):
    retrieved_ids = [d.metadata.get("doc_id") for d in retrieved_docs[:k]]
    relevant_retrieved = len(set(retrieved_ids) & set(relevant_doc_ids))
    return relevant_retrieved / k

# Example: retrieved 5 docs, 3 are relevant -> precision = 0.6


# ============================================================
# Recall@K: Of all relevant docs, how many did we find?
# ============================================================
def recall_at_k(retrieved_docs, relevant_doc_ids, k=5):
    retrieved_ids = [d.metadata.get("doc_id") for d in retrieved_docs[:k]]
    relevant_retrieved = len(set(retrieved_ids) & set(relevant_doc_ids))
    return relevant_retrieved / len(relevant_doc_ids)

# Example: 10 relevant docs exist, we found 3 of them -> recall = 0.3


# ============================================================
# MRR (Mean Reciprocal Rank): How high is the first relevant doc?
# ============================================================
def mrr(retrieved_docs, relevant_doc_ids):
    for i, doc in enumerate(retrieved_docs, 1):
        if doc.metadata.get("doc_id") in relevant_doc_ids:
            return 1.0 / i
    return 0.0

# Example: first relevant doc is at position 3 -> MRR = 0.33
```

**Generation metrics** (is the answer good?):

```python
# ============================================================
# Automated metrics (quick but imperfect)
# ============================================================
from rouge_score import rouge_scorer

scorer = rouge_scorer.RougeScorer(['rouge1', 'rougeL'], use_stemmer=True)

reference = "The embedding service uses all-MiniLM-L6-v2."
generated = "The platform uses the all-MiniLM-L6-v2 sentence transformer model."

scores = scorer.score(reference, generated)
print(f"ROUGE-1: {scores['rouge1'].fmeasure:.3f}")  # Unigram overlap
print(f"ROUGE-L: {scores['rougeL'].fmeasure:.3f}")  # Longest common subsequence


# ============================================================
# LLM-as-Judge (better quality, uses your own vLLM)
# ============================================================
judge_prompt = """Rate the following answer on faithfulness (1-5).
Does the answer accurately reflect the provided context?
Do NOT reward answers that add information not in the context.

Context: {context}
Question: {question}
Answer: {answer}

Score (1-5):"""

judge_response = llm.invoke(
    judge_prompt.format(
        context="The embedding service runs all-MiniLM-L6-v2 on CPU.",
        question="What embedding model is used?",
        answer=generated,
    )
)
# Parse score from response
```

**Faithfulness** (does the answer match the context?):

This is the most important RAG metric. A high-faithfulness answer only uses information from the retrieved documents. A low-faithfulness answer hallucinates.

```python
# ============================================================
# Faithfulness check via LLM-as-judge
# ============================================================
faithfulness_prompt = """Given the context and the answer, determine if
every claim in the answer is supported by the context.

Context:
{context}

Answer:
{answer}

For each claim in the answer, state whether it is SUPPORTED or UNSUPPORTED.
Then give an overall faithfulness score from 0.0 to 1.0."""

# Run this on every query in your eval dataset
# Track the score over time in LangFuse
```

### 4.2 LLM Quality Metrics (Training)

These metrics answer: "Did fine-tuning make the model better?"

| Metric | What It Means | Good Values | How to Get It |
|---|---|---|---|
| **Training loss** | How well model fits training data | Decreasing, then plateaus | `trainer.train()` logs it |
| **Eval loss** | How well model generalizes | Close to training loss | Set `eval_dataset` in trainer |
| **Perplexity** | How "surprised" the model is by text | Lower = better, exp(loss) | `math.exp(eval_loss)` |
| **Task accuracy** | Correct answers on held-out set | Depends on task, >80% is good | Run inference on test set |
| **MMLU** | General knowledge benchmark | Baseline comparison | `lm-eval --model vllm --tasks mmlu` |
| **TTFT** | Time to first token | <500ms for interactive | vLLM metrics: `vllm:time_to_first_token_seconds` |
| **Tokens/sec** | Generation throughput | >30 tok/s for Qwen-1.5B | vLLM metrics: `vllm:avg_generation_throughput_toks_per_s` |

```python
# ============================================================
# Compare before/after fine-tuning
# ============================================================
import math

# Before fine-tuning (base model eval loss)
base_eval_loss = 2.35
print(f"Base model perplexity: {math.exp(base_eval_loss):.1f}")   # 10.5

# After fine-tuning (LoRA adapter eval loss)
finetuned_eval_loss = 1.05
print(f"Fine-tuned perplexity: {math.exp(finetuned_eval_loss):.1f}")  # 2.9

# Lower perplexity = model is more confident and accurate on your domain
# But watch for overfitting: if train_loss << eval_loss, you overfit
```

### 4.3 What Scientists and DevOps Look At in Grafana

The platform ships a pre-built Grafana dashboard (`k8s/base/monitoring/prometheus-stack.yaml`). Here is what each panel means and who cares about it:

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ROW 1: vLLM Request Health                              WHO WATCHES   │
│                                                                        │
│ ┌─────────────────────┐ ┌─────────────────────┐ ┌──────────────────┐  │
│ │ Active Requests     │ │ Waiting (Queued)     │ │ GPU KV Cache %   │  │
│ │ vllm:num_requests_  │ │ vllm:num_requests_   │ │ vllm:gpu_cache_  │  │
│ │ running             │ │ waiting              │ │ usage_perc       │  │
│ │                     │ │                      │ │                  │  │
│ │ DevOps: "Are we     │ │ DevOps: "Need more   │ │ Both: ">90% =   │  │
│ │  under load?"       │ │  replicas?"          │ │  add capacity"   │  │
│ └─────────────────────┘ └──────────────────────┘ └──────────────────┘  │
│                                                                        │
│ ROW 2: Latency                                                        │
│                                                                        │
│ ┌─────────────────────────────────────┐ ┌──────────────────────────┐   │
│ │ vLLM Latency (p50/p95/p99)         │ │ TTFT (time to first      │   │
│ │ vllm:e2e_request_latency_seconds   │ │ token)                   │   │
│ │                                     │ │                          │   │
│ │ Both: "Is the model fast enough?"   │ │ Scientist: "User         │   │
│ │ DevOps: "Did latency spike after    │ │  experience metric"      │   │
│ │  deployment?"                       │ │                          │   │
│ └─────────────────────────────────────┘ └──────────────────────────┘   │
│                                                                        │
│ ROW 3: RAG-Specific Metrics                                           │
│                                                                        │
│ ┌─────────────────────────────────────┐ ┌──────────────────────────┐   │
│ │ RAG Query Latency (p95)            │ │ Token Usage Rate          │   │
│ │ rag_query_duration_seconds         │ │ rag_tokens_total          │   │
│ │ rag_retrieval_duration_seconds     │ │ (input vs output)         │   │
│ │ rag_generation_duration_seconds    │ │                           │   │
│ │                                     │ │ Scientist: "Is context    │   │
│ │ Both: "Where is the bottleneck?    │ │  too large? Wasting       │   │
│ │  Retrieval or generation?"         │ │  tokens?"                 │   │
│ └─────────────────────────────────────┘ └──────────────────────────┘   │
│                                                                        │
│ ROW 4: Cost (add via OpenCost)                                        │
│                                                                        │
│ ┌─────────────────────────────────────┐ ┌──────────────────────────┐   │
│ │ GPU Utilization %                  │ │ Cost per Query             │   │
│ │ DCGM_FI_DEV_GPU_UTIL              │ │ tokens * $/token           │   │
│ │                                     │ │                           │   │
│ │ DevOps: "Are we wasting GPU?"      │ │ Both: "Can we afford      │   │
│ │ "Utilization <30% = overpaying"    │ │  this at scale?"          │   │
│ └─────────────────────────────────────┘ └──────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

**Key PromQL queries scientists ask DevOps to add:**

```promql
# Request rate (queries per second)
rate(rag_queries_total{status="success"}[5m])

# Error rate
rate(rag_queries_total{status="error"}[5m])
  / rate(rag_queries_total[5m])

# P95 total query latency
histogram_quantile(0.95,
  rate(rag_query_duration_seconds_bucket[5m]))

# P95 retrieval latency (is pgvector slow?)
histogram_quantile(0.95,
  rate(rag_retrieval_duration_seconds_bucket[5m]))

# P95 generation latency (is vLLM slow?)
histogram_quantile(0.95,
  rate(rag_generation_duration_seconds_bucket[5m]))

# Token usage rate (for cost estimation)
rate(rag_tokens_total{type="input"}[5m])
rate(rag_tokens_total{type="output"}[5m])
```

---

## 5. Where DevOps/MLOps Comes In

For every scientist activity, there is a DevOps counterpart that makes it possible. This table maps them using actual components from this platform:

| Scientist Activity | DevOps/MLOps Provides | Platform Component |
|---|---|---|
| Opens JupyterLab | K8s Deployment, PVC for notebooks, env vars for service discovery | `k8s/base/jupyter/deployment.yaml`, `jupyter/pvc.yaml` |
| Calls vLLM from notebook | vLLM Deployment with GPU, model caching PVC, health probes | `k8s/base/inference/deployment.yaml`, `storage/model-cache-pvc.yaml` |
| Calls embedding service | Embedding Deployment (CPU), Service for DNS | `k8s/base/embedding/deployment.yaml`, `embedding/service.yaml` |
| Queries pgvector | StatefulSet with persistent storage | `k8s/base/pgvector/statefulset.yaml` |
| Runs experiments | Monitoring (Prometheus), ServiceMonitors for scraping | `k8s/base/monitoring/prometheus-stack.yaml` |
| Needs training data | Storage PVCs, S3 integration | `k8s/base/storage/training-data-pvc.yaml` |
| Trains a model (LoRA) | K8s Job with GPU, spot tolerations, shared memory | `pipelines/k8s-jobs/training-job.yaml` |
| Preprocesses data | K8s Job (CPU), S3 read/write | `pipelines/k8s-jobs/preprocessing-job.yaml` |
| Ingests docs for RAG | K8s Job, embedding service access, pgvector access | `pipelines/k8s-jobs/rag-ingestion-job.yaml` |
| Evaluates model quality | LangFuse deployment, PostgreSQL for trace storage | `k8s/base/monitoring/langfuse.yaml` |
| Promotes code to service | CI/CD (GitHub Actions), Docker builds, image registry | `.github/workflows/ci.yaml` |
| Deploys new model/code | ArgoCD auto-sync, Kustomize overlays, rolling updates | `k8s/argocd/application.yaml`, `k8s/overlays/dev/` |
| Model degrades | Alertmanager (Slack/PagerDuty), ArgoCD rollback | Prometheus alerting rules, ArgoCD UI |
| Needs more GPU | KEDA scale-to-zero, GPU node tolerations | `k8s/base/inference/keda-scaledobject.yaml` |
| Costs too high | KEDA scale-to-zero (no traffic = no GPU cost), OpenCost | `k8s/base/monitoring/opencost.yaml`, KEDA ScaledObject |

### DevOps Responsibilities Mapped to This Platform

**Platform provisioning:**

```
Terraform (terraform/)
    |-- EKS/K3s cluster with GPU node pools
    |-- S3 buckets for data and artifacts
    |-- Networking (VPC, subnets, security groups)
    |-- IAM roles for pod identity (S3 access)

Kubernetes manifests (k8s/)
    |-- base/: all deployments, services, storage, monitoring
    |-- overlays/dev/: dev-specific resource limits
    |-- argocd/: GitOps application definition
```

**Day-2 operations (what DevOps monitors daily):**

```
1. GPU utilization      -> Are we wasting money? Scale down if <30%
2. Pod restarts         -> OOMKilled? Increase memory limits
3. KEDA scaling events  -> Is scale-to-zero working? Cold start latency OK?
4. ArgoCD sync status   -> All apps healthy? Any sync failures?
5. PVC usage            -> Model cache filling up? Notebooks PVC full?
6. S3 costs             -> Training data growing? Old checkpoints to delete?
7. vLLM queue depth     -> Requests waiting? Need more replicas?
```

---

## 6. The Complete Lifecycle Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         EXPERIMENT (Scientist)                          │
│                                                                         │
│  JupyterLab pod (k8s/base/jupyter/)                                    │
│    |-- Connect to vLLM, embedding, pgvector via K8s DNS                │
│    |-- Test new prompts, retrieval strategies, models                   │
│    |-- Measure: accuracy, latency, cost per query                      │
│    |-- Winner found -> extract notebook code to Python module           │
│                                                                         │
│  Training (pipelines/training/train.py)                                │
│    |-- Fine-tune with Unsloth + LoRA (K8s Job with GPU)                │
│    |-- Hyperparameter sweep: lr, rank, epochs, data                    │
│    |-- Evaluate: loss, perplexity, task accuracy                       │
│    |-- Save adapter to S3                                              │
│                                                                         │
│  Files changed:                                                        │
│    services/rag-service/app/chains.py    (new chain logic)             │
│    services/rag-service/app/config.py    (new parameters)              │
│    pipelines/training/train.py           (training improvements)       │
│    k8s/base/inference/deployment.yaml    (new model/adapter)           │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ git push
                             v
┌─────────────────────────────────────────────────────────────────────────┐
│                         BUILD (CI/CD)                                   │
│                                                                         │
│  GitHub Actions (.github/workflows/ci.yaml)                            │
│    |-- ruff check . (lint)                                              │
│    |-- ruff format --check . (formatting)                               │
│    |-- pytest tests/ (unit tests)                                       │
│    |-- docker build + push to ghcr.io                                  │
│          ghcr.io/lehph/genai-rag-service:latest                        │
│          ghcr.io/lehph/genai-rag-service:<sha>                         │
└────────────────────────────┬────────────────────────────────────────────┘
                             │ ArgoCD detects new image
                             v
┌─────────────────────────────────────────────────────────────────────────┐
│                         DEPLOY (GitOps)                                 │
│                                                                         │
│  ArgoCD (k8s/argocd/application.yaml)                                  │
│    |-- Watches: main branch, k8s/overlays/dev path                     │
│    |-- Auto-sync: prune + selfHeal enabled                             │
│    |-- Kustomize overlay applied (dev resource limits)                  │
│    |-- Rolling update: zero downtime                                    │
│    |-- Retry: 3 attempts with exponential backoff                      │
└────────────────────────────┬────────────────────────────────────────────┘
                             │
                             v
┌─────────────────────────────────────────────────────────────────────────┐
│                         MONITOR (Both Roles)                            │
│                                                                         │
│  Prometheus + Grafana (k8s/base/monitoring/)                           │
│    |-- ServiceMonitors scrape: vLLM, RAG service, embedding service    │
│    |-- Pre-built dashboard: latency, throughput, GPU cache, tokens     │
│    |-- DevOps watches: uptime, error rate, GPU utilization, cost       │
│                                                                         │
│  LangFuse (k8s/base/monitoring/langfuse.yaml)                          │
│    |-- Trace logging: every chain step visualized                      │
│    |-- Token tracking: input/output tokens per request                 │
│    |-- Latency breakdown: embed -> retrieve -> generate                │
│    |-- Scientist watches: faithfulness, relevance, quality scores      │
│                                                                         │
│  OpenCost (k8s/base/monitoring/opencost.yaml)                          │
│    |-- Per-pod cost attribution                                        │
│    |-- GPU cost tracking                                               │
│    |-- Both watch: total platform cost, cost per query                 │
│                                                                         │
│  If alert fires or quality drops:                                      │
│    |-- DevOps: ArgoCD rollback, scale up, investigate infra            │
│    |-- Scientist: open JupyterLab, investigate model/data              │
│    |-- Back to EXPERIMENT                                              │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 7. Example: End-to-End Scenario

**Scenario: "The RAG system is returning low-quality answers for financial questions."**

This walks through exactly what happens, who does what, and which files/tools are involved.

### Step 1: Scientist detects the problem in LangFuse

```
LangFuse Dashboard (http://localhost:3000)
  |-- Filter traces by: tag="financial"
  |-- Faithfulness scores: 0.55 average (should be >0.8)
  |-- Common pattern: retrieved docs are about general topics,
      not financial-specific documents
```

### Step 2: Scientist investigates in JupyterLab

```python
# Cell 1: Reproduce the problem
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores.pgvector import PGVector

llm = ChatOpenAI(base_url="http://inference:8000/v1",
                 api_key="not-needed",
                 model="Qwen/Qwen2.5-1.5B-Instruct")

vectorstore = PGVector(
    connection="postgresql+psycopg://postgres:postgres@pgvector:5432/vectordb",
    collection_name="documents",
    embedding_function=current_embedding,  # all-MiniLM-L6-v2
)

retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

# Test with financial queries
docs = retriever.invoke("What is the impact of rising interest rates on bond prices?")
for d in docs:
    print(f"Score: N/A | Source: {d.metadata.get('source', '?')}")
    print(f"Content: {d.page_content[:100]}...\n")

# FINDING: Retrieved docs are about general economics, not bonds/rates
# The embedding model (all-MiniLM-L6-v2) doesn't understand financial jargon
```

### Step 3: Scientist tests a domain-specific embedding model

```python
# Cell 2: Try a finance-aware embedding model
# bge-small-en-v1.5 has better domain coverage
from sentence_transformers import SentenceTransformer

# Test embedding similarity
model_current = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
model_new = SentenceTransformer("BAAI/bge-small-en-v1.5")

query = "impact of rising interest rates on bond prices"
doc_relevant = "When central banks raise interest rates, existing bond prices fall..."
doc_irrelevant = "The economy grew by 3% in the second quarter..."

# Compare cosine similarity
import numpy as np

def cosine_sim(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

for name, model in [("MiniLM", model_current), ("BGE-small", model_new)]:
    q_emb = model.encode(query)
    rel_emb = model.encode(doc_relevant)
    irr_emb = model.encode(doc_irrelevant)
    print(f"{name}:")
    print(f"  Relevant doc similarity:   {cosine_sim(q_emb, rel_emb):.3f}")
    print(f"  Irrelevant doc similarity: {cosine_sim(q_emb, irr_emb):.3f}")
    print(f"  Gap: {cosine_sim(q_emb, rel_emb) - cosine_sim(q_emb, irr_emb):.3f}\n")

# FINDING: BGE-small has a larger gap (0.15 vs 0.08) -- better at distinguishing
```

### Step 4: Scientist tests the full RAG pipeline with new embeddings

```python
# Cell 3: Re-embed financial docs with new model, test RAG quality
# (in Jupyter, using a temporary collection)

from langchain_community.embeddings import HuggingFaceEmbeddings

new_embedding = HuggingFaceEmbeddings(model_name="BAAI/bge-small-en-v1.5")

# Create a test collection with the new embeddings
test_vectorstore = PGVector.from_documents(
    documents=financial_docs,  # loaded earlier
    embedding=new_embedding,
    connection="postgresql+psycopg://postgres:postgres@pgvector:5432/vectordb",
    collection_name="documents_bge_test",
    pre_delete_collection=True,  # clean test collection
)

# Test retrieval quality
test_retriever = test_vectorstore.as_retriever(search_kwargs={"k": 5})
docs = test_retriever.invoke("impact of rising interest rates on bond prices")

# Check: are the retrieved docs more relevant now?
for d in docs:
    print(f"Source: {d.metadata.get('source', '?')}")
    print(f"Content: {d.page_content[:100]}...\n")

# FINDING: Much better retrieval -- financial docs are now top-ranked
```

### Step 5: Scientist confirms quality improvement

```python
# Cell 4: Run full evaluation
eval_questions = [
    ("What is the impact of rising interest rates?",
     "bond prices fall"),
    ("How does inflation affect stock markets?",
     "purchasing power decreases"),
    # ... 50 more eval pairs
]

# LLM-as-judge evaluation
scores_old = evaluate_rag(eval_questions, old_retriever, llm)
scores_new = evaluate_rag(eval_questions, test_retriever, llm)

print(f"Faithfulness (old): {np.mean(scores_old['faithfulness']):.2f}")  # 0.60
print(f"Faithfulness (new): {np.mean(scores_new['faithfulness']):.2f}")  # 0.85
print(f"Relevance (old):    {np.mean(scores_old['relevance']):.2f}")     # 0.55
print(f"Relevance (new):    {np.mean(scores_new['relevance']):.2f}")     # 0.82

# DECISION: Ship the new embedding model
```

### Step 6: DevOps updates the embedding service

```python
# File: services/embedding/app/main.py
# Change line 21:
MODEL_NAME = "BAAI/bge-small-en-v1.5"  # was "sentence-transformers/all-MiniLM-L6-v2"
```

```python
# File: services/rag-service/app/config.py
# Update embedding dimension:
embedding_dimension: int = 384  # bge-small-en-v1.5 is also 384-dim (same as MiniLM)
```

### Step 7: DevOps pushes, CI builds, ArgoCD deploys

```bash
git add services/embedding/app/main.py services/rag-service/app/config.py
git commit -m "feat(embedding): switch to bge-small-en-v1.5 for better domain coverage

Scientist evaluation shows faithfulness improvement: 0.60 -> 0.85
on financial question eval set. Same embedding dimension (384), no
schema changes needed in pgvector."
git push
```

CI pipeline:
1. Lint passes
2. Tests pass
3. Docker build: `ghcr.io/lehph/genai-embedding:latest` (with new model)
4. ArgoCD auto-syncs -> rolling update on embedding service

### Step 8: Re-run ingestion to re-embed all documents

```bash
# All existing documents need new embeddings (different model = different vectors)
# This is a one-time cost, run as a K8s Job:
kubectl apply -f pipelines/k8s-jobs/rag-ingestion-job.yaml -n genai

# Watch progress:
kubectl logs -f job/rag-ingestion -n genai

# This takes 5-30 minutes depending on document volume
```

### Step 9: Both monitor the results

**Scientist (LangFuse):**
- Faithfulness scores rise from 0.60 to 0.85 over the next hour
- Token usage stays the same (same model size)
- No new error patterns

**DevOps (Grafana):**
- Embedding service latency: similar (bge-small is same size as MiniLM)
- RAG query latency: unchanged
- Error rate: 0% during rollout (rolling update worked)
- No pod restarts or OOMKills

### Step 10: Done

```
RESULT: Financial query faithfulness improved from 0.60 to 0.85
COST: 0 (same model size, same infra)
TIME: ~2 hours (scientist investigation + DevOps deployment)
RISK: Low (same embedding dimension, rolling update, easy rollback)
```

---

## 8. Interview-Ready Explanations

Five explanations you should be able to give fluently, with specific references to this platform.

### Q1: "How do scientists train models on your platform?"

> "Scientists start in JupyterLab, which runs as a pod inside the K3s cluster with direct access to all services. They explore data with Pandas, test different model configurations using Unsloth for efficient LoRA fine-tuning, and evaluate results -- all in notebooks.
>
> When they find a winning configuration, they extract the logic into our parameterized training script at `pipelines/training/train.py`. That script runs as a K8s Job with GPU resources, reads data from S3, and saves the LoRA adapter back to S3.
>
> The key thing scientists tune: learning rate, LoRA rank, number of epochs, and the training dataset itself. LoRA means we only train 0.5% of the model's parameters, so a fine-tuning run takes minutes on a single GPU, not hours on a cluster.
>
> To deploy the adapter, we update the vLLM deployment to load it alongside the base model. vLLM supports hot-loading LoRA adapters, so you can serve multiple adapters from one base model."

### Q2: "How do you promote code from experimentation to production?"

> "We have a five-stage promotion workflow: Explore in Jupyter, Extract to Script, Test Locally, Push to Git, and Monitor.
>
> A scientist experiments in JupyterLab -- testing prompts, retrieval strategies, or model parameters. Once they find something that works, they extract the notebook code into the service module. For example, a new RAG chain goes from a notebook into `services/rag-service/app/chains.py`.
>
> During extraction, they add error handling, structured logging, Prometheus metrics, and configuration via environment variables. Then they test locally by running the FastAPI service directly.
>
> On `git push`, GitHub Actions runs linting, tests, and builds a Docker image. ArgoCD watches the repo and auto-syncs -- it applies the Kustomize overlay and does a rolling update. Zero downtime, automatic rollback on failure.
>
> After deployment, the scientist checks LangFuse for quality metrics while I check Grafana for latency and error rates. If anything degrades, ArgoCD can roll back in seconds."

### Q3: "How do you measure LLM quality?"

> "We measure at three levels: retrieval quality, generation quality, and operational quality.
>
> For retrieval, we track Precision@K and Recall@K -- are we finding the right documents? We run evaluation datasets through the retriever and measure these automatically.
>
> For generation, we use LLM-as-judge for faithfulness -- does the answer stick to the retrieved context, or does it hallucinate? We also track ROUGE scores against reference answers. LangFuse stores all traces so scientists can inspect individual query flows and see the exact retrieved context alongside the generated answer.
>
> For operations, Prometheus scrapes custom metrics from the RAG service: query latency broken down into retrieval time and generation time, token usage rates for cost tracking, and error rates. These feed into a Grafana dashboard with p50/p95/p99 latency panels, GPU KV cache utilization, and request throughput.
>
> The most important metric is faithfulness -- a RAG system that hallucinates is worse than one that says 'I don't know.' We run automated faithfulness evaluations weekly and alert if scores drop below threshold."

### Q4: "How do DevOps and ML engineers collaborate?"

> "We own complementary halves of the same system. The scientist owns what runs inside the container -- the Python code, the model, the chain logic, the prompts. I own everything around it -- the cluster, the deployments, the CI/CD, the monitoring stack, the scaling policies.
>
> Concretely: when a scientist needs JupyterLab, I provide a K8s Deployment with a PVC for notebooks, environment variables for service discovery, and resource limits that prevent one person's experiment from starving the cluster. When they need to train a model, I provide a K8s Job template with GPU resources, spot instance tolerations for cost savings, and shared memory volumes for tensor operations.
>
> The feedback loop is continuous. The scientist changes a prompt, pushes, and ArgoCD deploys it. I see latency spike in Grafana and we investigate together. Maybe the new prompt generates longer answers -- I update the max_tokens in the vLLM config, or the scientist tightens the prompt. Neither of us can ship improvements alone.
>
> The key enabler is GitOps. Everything is in one repo -- the scientist's Python code and my Kubernetes manifests. One `git push` triggers the whole pipeline. No tickets, no handoffs, no 'throw it over the wall.'"

### Q5: "What happens when a model degrades in production?"

> "We detect degradation through two channels: Prometheus alerts for operational issues, and LangFuse for quality issues.
>
> If Prometheus detects high error rates or latency spikes, Alertmanager fires to Slack. I check Grafana -- is it a GPU issue (KV cache full, OOMKilled), an infra issue (pod scheduling, network), or a load issue (more traffic than capacity)? For infra issues, I fix the K8s configuration. For load issues, I adjust KEDA scaling parameters or add GPU capacity.
>
> If LangFuse detects quality degradation -- faithfulness scores dropping, relevance dropping -- the scientist investigates. They open JupyterLab, reproduce the failing queries, inspect the retrieved documents, and figure out what changed. Maybe the knowledge base needs new documents, maybe the embedding model does not understand a new domain, maybe a training data issue caused the fine-tuned model to regress.
>
> For immediate remediation, ArgoCD supports one-click rollback to any previous sync. If we shipped a bad model or a bad prompt change, we revert the git commit and ArgoCD auto-syncs the rollback. The old pods come up, the new pods drain -- zero downtime.
>
> Long-term, we track quality metrics over time in LangFuse to catch gradual degradation. Models can drift as user behavior changes, and the RAG knowledge base goes stale. We run weekly evaluation benchmarks against a golden test set to catch this before users notice."
