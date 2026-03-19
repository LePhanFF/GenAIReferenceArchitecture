# Migration & Upgrade Playbooks

Practical runbooks for upgrading Kubernetes clusters, models, databases, frameworks, and infrastructure. Each section covers the procedure, risks, rollback plan, and interview-ready explanations.

---

## 1. EKS Version Upgrades

EKS supports two upgrade strategies. Choose based on risk tolerance and downtime budget.

### Strategy A: Blue-Green Cluster Migration (Safer)

Create a new cluster at the target version, migrate workloads, then decommission the old cluster. Zero risk of in-place upgrade failures. More infrastructure cost during migration window.

**Step-by-step:**

```bash
# 1. Create new cluster at target version (Terraform)
# In terraform/environments/production/main.tf, add:
module "eks_v2" {
  source          = "../../modules/eks"
  cluster_name    = "genai-prod-v130"
  cluster_version = "1.30"
  # Copy all other settings from existing cluster
}

# 2. Apply Terraform to create the new cluster
terraform plan -target=module.eks_v2
terraform apply -target=module.eks_v2

# 3. Install addons on new cluster
# Core addons (must be compatible with target K8s version)
aws eks create-addon --cluster-name genai-prod-v130 --addon-name vpc-cni --addon-version v1.18.1-eksbuild.1
aws eks create-addon --cluster-name genai-prod-v130 --addon-name coredns --addon-version v1.11.1-eksbuild.9
aws eks create-addon --cluster-name genai-prod-v130 --addon-name kube-proxy --addon-version v1.30.0-eksbuild.3

# GPU operator
helm install gpu-operator nvidia/gpu-operator --version v24.6.0 --namespace gpu-operator

# 4. Deploy workloads to new cluster
kubectl config use-context genai-prod-v130
kubectl apply -k k8s/overlays/production/

# 5. Run smoke tests on new cluster
kubectl run smoke-test --image=curlimages/curl --rm -it -- \
  curl -s http://api-gateway.default/health

# 6. Test GPU workloads
kubectl apply -f k8s/test/gpu-test-pod.yaml
kubectl logs gpu-test-pod  # Verify CUDA works

# 7. Switch DNS / load balancer to new cluster
# Update Route53 weighted record or ALB target group
aws elbv2 modify-target-group --target-group-arn $NEW_TG_ARN --targets ...

# 8. Monitor for 24-48 hours, then decommission old cluster
terraform destroy -target=module.eks_v1
```

### Strategy B: In-Place Rolling Upgrade (Simpler)

Upgrade the control plane first, then node groups one at a time. Less infrastructure overhead but riskier — failed upgrades can leave the cluster in a mixed-version state.

**Step-by-step:**

```bash
# 1. Pre-upgrade: Check for deprecated APIs
# Install kubent (kube-no-trouble) to find deprecated API usage
kubent --cluster

# Or use kubectl to check for deprecated APIs removed in target version
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis

# 2. Pre-upgrade: Update addons compatibility matrix
# Check: https://docs.aws.amazon.com/eks/latest/userguide/managing-add-ons.html

# 3. Update control plane (Terraform)
# Change cluster_version in Terraform
resource "aws_eks_cluster" "main" {
  name    = "genai-prod"
  version = "1.30"  # was "1.29"
}
terraform apply

# Control plane upgrade takes 20-40 minutes
# Workloads continue running on old-version nodes during this time

# 4. Update node groups one at a time
# Update launch template with new AMI
aws eks update-nodegroup-version \
  --cluster-name genai-prod \
  --nodegroup-name cpu-workers \
  --kubernetes-version 1.30

# Wait for node group update to complete
aws eks wait nodegroup-active \
  --cluster-name genai-prod \
  --nodegroup-name cpu-workers

# Then update GPU node group
aws eks update-nodegroup-version \
  --cluster-name genai-prod \
  --nodegroup-name gpu-workers \
  --kubernetes-version 1.30 \
  --launch-template name=gpu-node-v130,version=2

# 5. Update addons to compatible versions
aws eks update-addon --cluster-name genai-prod \
  --addon-name vpc-cni --addon-version v1.18.1-eksbuild.1

aws eks update-addon --cluster-name genai-prod \
  --addon-name coredns --addon-version v1.11.1-eksbuild.9

# 6. Verify
kubectl get nodes -o wide  # All nodes should show new version
kubectl get pods -A | grep -v Running  # No crashing pods
```

### Pre-Upgrade Checklist

- [ ] Run `kubent` to find deprecated API usage (CronJob batch/v1beta1, Ingress extensions/v1beta1, etc.)
- [ ] Check addon compatibility matrix for target version
- [ ] Verify GPU operator version compatibility (NVIDIA publishes a K8s compatibility matrix)
- [ ] Check PodDisruptionBudgets — ensure they allow node drains
- [ ] Review PodSecurityPolicies → PodSecurityStandards migration (if applicable)
- [ ] Test upgrade in staging/dev cluster first
- [ ] Check custom admission webhooks work with new API server version
- [ ] Backup etcd (EKS manages this, but verify)
- [ ] Confirm Terraform state is clean (`terraform plan` shows no drift)
- [ ] Notify team, schedule maintenance window

### Key Risks

| Risk | Mitigation |
|---|---|
| Deprecated API removal | Run `kubent` pre-upgrade, update manifests |
| GPU operator incompatibility | Check NVIDIA GPU Operator compatibility matrix |
| Addon version mismatch | Update addons after control plane, before node groups |
| PDB blocking node drain | Review PDBs, temporarily relax if needed |
| Custom webhook failures | Test webhooks against new API server version |
| Terraform state drift | Run `terraform plan` before and after |

---

## 2. GKE Version Upgrades

GKE simplifies upgrades significantly compared to EKS through release channels and automatic upgrades.

### Release Channels

| Channel | Behavior | Best For |
|---|---|---|
| **Rapid** | Newest versions, earliest patches | Dev/staging environments |
| **Regular** | Balanced stability, 2-3 months behind Rapid | Most production workloads |
| **Stable** | Most tested, 4-5 months behind Rapid | Risk-averse production |

### Controlling Upgrade Timing

```bash
# Set release channel
gcloud container clusters update genai-prod \
  --release-channel regular \
  --region us-central1

# Configure maintenance window (upgrades only happen during this window)
gcloud container clusters update genai-prod \
  --maintenance-window-start 2024-01-01T02:00:00Z \
  --maintenance-window-end 2024-01-01T06:00:00Z \
  --maintenance-window-recurrence "FREQ=WEEKLY;BYDAY=SA,SU"

# Maintenance exclusions (block upgrades during critical periods)
gcloud container clusters update genai-prod \
  --add-maintenance-exclusion-name "product-launch" \
  --add-maintenance-exclusion-start 2024-03-01T00:00:00Z \
  --add-maintenance-exclusion-end 2024-03-15T00:00:00Z \
  --add-maintenance-exclusion-scope no_upgrades
```

### Surge Upgrade Settings

Surge upgrades control how many extra nodes GKE creates during a rolling update, affecting speed vs cost.

```bash
# Configure surge upgrade: 1 extra node, 0 unavailable (safest)
gcloud container node-pools update gpu-pool \
  --cluster genai-prod \
  --max-surge-upgrade 1 \
  --max-unavailable-upgrade 0

# For faster upgrades (GPU pools are expensive to double):
# Allow 1 unavailable node during upgrade
gcloud container node-pools update gpu-pool \
  --cluster genai-prod \
  --max-surge-upgrade 1 \
  --max-unavailable-upgrade 1
```

### Testing in Staging

```bash
# 1. Check what version is available
gcloud container get-server-config --region us-central1 \
  --format="yaml(channels)"

# 2. Manually trigger upgrade in staging
gcloud container clusters upgrade genai-staging \
  --master \
  --cluster-version 1.30.2-gke.1234 \
  --region us-central1

# 3. After control plane, upgrade node pools
gcloud container clusters upgrade genai-staging \
  --node-pool gpu-pool \
  --cluster-version 1.30.2-gke.1234 \
  --region us-central1

# 4. Run e2e tests against staging
kubectl config use-context gke_project_region_genai-staging
pytest tests/e2e/ -v --base-url=https://staging-api.example.com
```

---

## 3. Model Version Upgrades

### Canary Rollout with Istio VirtualService

Progressive traffic shifting from old model to new model with automated quality gates.

**Phase 1: Deploy new model version (0% traffic)**

```yaml
# k8s/deployments/model-v2.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-generator-v2
  labels:
    app: rag-generator
    version: v2
spec:
  replicas: 1  # Start with 1 replica for canary
  selector:
    matchLabels:
      app: rag-generator
      version: v2
  template:
    metadata:
      labels:
        app: rag-generator
        version: v2
    spec:
      containers:
      - name: vllm
        image: vllm/vllm-openai:latest
        args:
        - "--model=s3://models/rag-generator/v2/merged"
        - "--tensor-parallel-size=1"
        resources:
          limits:
            nvidia.com/gpu: 1
```

**Phase 2: Canary at 5%**

```yaml
# k8s/istio/model-virtualservice.yaml
apiVersion: networking.istio.io/v1beta1
kind: VirtualService
metadata:
  name: rag-generator-vs
spec:
  hosts:
  - rag-generator
  http:
  - route:
    - destination:
        host: rag-generator
        subset: v1
        port:
          number: 8000
      weight: 95
    - destination:
        host: rag-generator
        subset: v2
        port:
          number: 8000
      weight: 5
---
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: rag-generator-dr
spec:
  host: rag-generator
  subsets:
  - name: v1
    labels:
      version: v1
  - name: v2
    labels:
      version: v2
```

**Phase 3: Monitor and promote (automated script)**

```python
import subprocess
import json
import time

STAGES = [
    {"weight_v2": 5,   "duration_minutes": 30},
    {"weight_v2": 25,  "duration_minutes": 60},
    {"weight_v2": 50,  "duration_minutes": 60},
    {"weight_v2": 100, "duration_minutes": 0},  # Full promotion
]

PROMOTION_CRITERIA = {
    "max_error_rate": 0.01,        # 1% error rate
    "max_latency_p99_ms": 500,     # 500ms P99
    "min_quality_score": 0.85,     # LLM-as-judge quality score
}

def get_canary_metrics(version: str) -> dict:
    """Query Prometheus for canary metrics."""
    # Error rate
    error_rate = prometheus_query(
        f'rate(http_requests_total{{app="rag-generator",version="{version}",code=~"5.."}}[5m]) / '
        f'rate(http_requests_total{{app="rag-generator",version="{version}"}}[5m])'
    )
    # Latency P99
    latency_p99 = prometheus_query(
        f'histogram_quantile(0.99, rate(http_request_duration_seconds_bucket'
        f'{{app="rag-generator",version="{version}"}}[5m]))'
    )
    return {"error_rate": error_rate, "latency_p99_ms": latency_p99 * 1000}

def update_traffic_weight(weight_v2: int):
    """Update Istio VirtualService weights."""
    patch = {
        "spec": {"http": [{"route": [
            {"destination": {"host": "rag-generator", "subset": "v1",
                             "port": {"number": 8000}}, "weight": 100 - weight_v2},
            {"destination": {"host": "rag-generator", "subset": "v2",
                             "port": {"number": 8000}}, "weight": weight_v2},
        ]}]}
    }
    subprocess.run([
        "kubectl", "patch", "virtualservice", "rag-generator-vs",
        "--type", "merge", "-p", json.dumps(patch)
    ], check=True)

def rollback():
    """Rollback to v1."""
    update_traffic_weight(0)
    subprocess.run(["kubectl", "delete", "deployment", "rag-generator-v2"], check=True)
    print("ROLLBACK COMPLETE: All traffic on v1")

for stage in STAGES:
    update_traffic_weight(stage["weight_v2"])
    print(f"Canary at {stage['weight_v2']}% — monitoring for {stage['duration_minutes']} minutes")

    # Monitor during this stage
    end_time = time.time() + stage["duration_minutes"] * 60
    while time.time() < end_time:
        metrics = get_canary_metrics("v2")
        if metrics["error_rate"] > PROMOTION_CRITERIA["max_error_rate"]:
            print(f"ERROR RATE TOO HIGH: {metrics['error_rate']}")
            rollback()
            exit(1)
        if metrics["latency_p99_ms"] > PROMOTION_CRITERIA["max_latency_p99_ms"]:
            print(f"LATENCY TOO HIGH: {metrics['latency_p99_ms']}ms")
            rollback()
            exit(1)
        time.sleep(60)

print("CANARY PROMOTION COMPLETE: v2 serving 100% traffic")
# Scale up v2, scale down v1
subprocess.run(["kubectl", "scale", "deployment", "rag-generator-v2", "--replicas=3"], check=True)
subprocess.run(["kubectl", "scale", "deployment", "rag-generator-v1", "--replicas=0"], check=True)
```

### Rollback Procedure

```bash
# Immediate rollback: shift all traffic back to v1
kubectl patch virtualservice rag-generator-vs --type merge \
  -p '{"spec":{"http":[{"route":[
    {"destination":{"host":"rag-generator","subset":"v1","port":{"number":8000}},"weight":100},
    {"destination":{"host":"rag-generator","subset":"v2","port":{"number":8000}},"weight":0}
  ]}]}}'

# Delete canary deployment
kubectl delete deployment rag-generator-v2

# Rollback takes seconds because v1 is still running
```

---

## 4. pgvector Migrations

### Schema Changes and Index Rebuilds

pgvector indexes (IVFFlat, HNSW) are sensitive to data distribution. Schema changes and embedding dimension changes require careful migration.

### Re-embedding Migration Pattern

When changing embedding models (e.g., upgrading from `text-embedding-ada-002` to `text-embedding-3-large`), you can't just swap — dimensions may change (1536 → 3072) and the vector space is completely different.

**Zero-downtime migration approach:**

```sql
-- Step 1: Add new column for new embeddings (don't drop the old one yet)
ALTER TABLE documents
  ADD COLUMN embedding_v2 vector(3072);  -- New dimension

-- Step 2: Create index on new column (CONCURRENTLY to avoid locking)
-- CRITICAL: CREATE INDEX CONCURRENTLY does NOT lock the table for writes
-- Regular CREATE INDEX locks the table, blocking all inserts/updates
CREATE INDEX CONCURRENTLY idx_documents_embedding_v2
  ON documents
  USING hnsw (embedding_v2 vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

-- Why CONCURRENTLY matters:
-- - Without CONCURRENTLY: table is WRITE-LOCKED for the entire index build
--   (can take hours for millions of rows)
-- - With CONCURRENTLY: no write lock, but takes ~2x longer and requires
--   more memory. Can't run inside a transaction block.

-- Step 3: Background re-embedding job (Python)
```

```python
import psycopg2
from openai import OpenAI

client = OpenAI()

def re_embed_batch(batch_size=100):
    """Re-embed documents in batches. Designed to be run as a background job."""
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()

    while True:
        # Fetch documents that haven't been re-embedded yet
        cur.execute("""
            SELECT id, content FROM documents
            WHERE embedding_v2 IS NULL
            ORDER BY id
            LIMIT %s
            FOR UPDATE SKIP LOCKED  -- Allow concurrent re-embedding workers
        """, (batch_size,))

        rows = cur.fetchall()
        if not rows:
            break

        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]

        # Generate new embeddings
        response = client.embeddings.create(
            model="text-embedding-3-large",
            input=texts,
            dimensions=3072
        )

        # Update in batch
        for row_id, embedding_data in zip(ids, response.data):
            cur.execute(
                "UPDATE documents SET embedding_v2 = %s WHERE id = %s",
                (embedding_data.embedding, row_id)
            )

        conn.commit()
        print(f"Re-embedded {len(rows)} documents")

    cur.close()
    conn.close()
```

```sql
-- Step 4: Verify re-embedding is complete
SELECT COUNT(*) FROM documents WHERE embedding_v2 IS NULL;
-- Should be 0

-- Step 5: Switch application to use new column
-- Update application queries:
-- FROM: ORDER BY embedding <=> $1
-- TO:   ORDER BY embedding_v2 <=> $1

-- Step 6: After confirming new embeddings work in production (24-48 hours)
-- Drop old column and index
DROP INDEX idx_documents_embedding;
ALTER TABLE documents DROP COLUMN embedding;
ALTER TABLE documents RENAME COLUMN embedding_v2 TO embedding;
ALTER INDEX idx_documents_embedding_v2 RENAME TO idx_documents_embedding;
```

### Embedding Dimension Changes

If changing dimensions without changing the model (using Matryoshka embeddings or dimensionality reduction):

```sql
-- text-embedding-3-large supports variable dimensions via API parameter
-- But you need a new column because vector(1536) != vector(3072)

-- Option 1: Reduce dimensions at query time (slower, no schema change)
SELECT id, content
FROM documents
ORDER BY (embedding::vector(256)) <=> ($1::vector(256))
LIMIT 10;

-- Option 2: Store reduced dimensions in a new column (faster queries)
ALTER TABLE documents ADD COLUMN embedding_256 vector(256);
UPDATE documents SET embedding_256 = embedding::vector(256);
CREATE INDEX CONCURRENTLY ON documents
  USING hnsw (embedding_256 vector_cosine_ops);
```

### Index Tuning

```sql
-- HNSW parameters (tune for your data)
-- m: connections per node (higher = better recall, more memory)
-- ef_construction: build-time beam width (higher = better recall, slower build)
CREATE INDEX CONCURRENTLY ON documents
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

-- Query-time parameter (higher = better recall, slower queries)
SET hnsn.ef_search = 100;  -- Default is 40

-- IVFFlat (faster build, less memory, but requires VACUUM ANALYZE)
CREATE INDEX CONCURRENTLY ON documents
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 1000);  -- sqrt(num_rows) is a good starting point

-- IMPORTANT: Run ANALYZE after bulk inserts to update statistics
ANALYZE documents;
```

---

## 5. LangChain 1.0 Migration

### Major Breaking Changes

LangChain 0.2 → 0.3+ (the "1.0 direction") introduced significant architectural changes:

| Area | Old (0.1/0.2) | New (0.3+) |
|---|---|---|
| **Chains** | `LLMChain`, `RetrievalQA`, etc. | Deprecated. Use LCEL (LangChain Expression Language) or LangGraph |
| **Primary framework** | Chains | LangGraph (stateful, graph-based) |
| **Import paths** | `from langchain.xxx` | `from langchain_community.xxx` or `from langchain_openai` |
| **LLM wrappers** | `from langchain.llms import OpenAI` | `from langchain_openai import ChatOpenAI` |
| **Serving** | LangServe | Deprecated. Use LangGraph Platform or FastAPI |
| **Callbacks** | `BaseCallbackHandler` | Same, but tracing via LangSmith recommended |
| **Vector stores** | `from langchain.vectorstores` | `from langchain_community.vectorstores` or partner packages |

### Migration Steps

```python
# BEFORE (0.1/0.2 style — deprecated)
from langchain.llms import OpenAI
from langchain.chains import LLMChain, RetrievalQA
from langchain.prompts import PromptTemplate
from langchain.vectorstores import PGVector
from langchain.embeddings import OpenAIEmbeddings

llm = OpenAI(temperature=0)
chain = LLMChain(llm=llm, prompt=prompt)
result = chain.run("What is RAG?")

qa = RetrievalQA.from_chain_type(llm=llm, retriever=retriever)
answer = qa.run("How does the system work?")

# AFTER (0.3+ style)
from langchain_openai import ChatOpenAI
from langchain_community.vectorstores import PGVector
from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# LCEL chain (replaces LLMChain)
llm = ChatOpenAI(model="gpt-4o", temperature=0)
prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a helpful assistant."),
    ("user", "{question}")
])
chain = prompt | llm | StrOutputParser()
result = chain.invoke({"question": "What is RAG?"})

# LCEL RAG chain (replaces RetrievalQA)
from langchain_core.runnables import RunnablePassthrough

def format_docs(docs):
    return "\n\n".join(d.page_content for d in docs)

rag_prompt = ChatPromptTemplate.from_messages([
    ("system", "Answer based on context:\n{context}"),
    ("user", "{question}")
])

rag_chain = (
    {"context": retriever | format_docs, "question": RunnablePassthrough()}
    | rag_prompt
    | llm
    | StrOutputParser()
)
answer = rag_chain.invoke("How does the system work?")
```

### LangGraph Migration (for complex flows)

```python
# BEFORE: Sequential chain with routing logic (messy with LLMChain)

# AFTER: LangGraph (stateful graph)
from langgraph.graph import StateGraph, END
from typing import TypedDict

class RAGState(TypedDict):
    question: str
    context: list[str]
    answer: str
    needs_retrieval: bool

def should_retrieve(state: RAGState) -> str:
    """Router: decide if we need retrieval."""
    if state.get("needs_retrieval", True):
        return "retrieve"
    return "generate"

def retrieve(state: RAGState) -> RAGState:
    docs = retriever.invoke(state["question"])
    return {"context": [d.page_content for d in docs]}

def generate(state: RAGState) -> RAGState:
    context = "\n".join(state.get("context", []))
    answer = llm.invoke(f"Context: {context}\nQuestion: {state['question']}")
    return {"answer": answer.content}

# Build graph
graph = StateGraph(RAGState)
graph.add_node("retrieve", retrieve)
graph.add_node("generate", generate)
graph.add_conditional_edges("__start__", should_retrieve)
graph.add_edge("retrieve", "generate")
graph.add_edge("generate", END)

app = graph.compile()
result = app.invoke({"question": "How does caching work?", "needs_retrieval": True})
```

### What Changes in This Repo's Services

| Service | Change Needed |
|---|---|
| **RAG service** | Replace `RetrievalQA` chain with LCEL or LangGraph RAG chain |
| **API layer** | If using LangServe, migrate to FastAPI + LangGraph |
| **Import paths** | Update all `from langchain.xxx` to `langchain_community` or partner packages |
| **Vector store** | `from langchain_community.vectorstores import PGVector` |
| **Embeddings** | `from langchain_openai import OpenAIEmbeddings` |
| **Dependencies** | Add `langchain-openai`, `langchain-community`, `langgraph` to requirements |

### Package Changes

```
# Old requirements.txt
langchain==0.1.x
openai

# New requirements.txt
langchain-core>=0.3.0
langchain-community>=0.3.0
langchain-openai>=0.2.0
langgraph>=0.2.0
# Remove: langchain (monolithic package)
# Remove: langserve
```

---

## 6. Infrastructure Migration (Region/Cloud)

### Region Move

Moving from one AWS region to another (e.g., `us-east-1` → `us-west-2` for GPU availability or latency).

**Terraform workspace per region:**

```hcl
# terraform/environments/us-west-2/main.tf
module "eks" {
  source          = "../../modules/eks"
  cluster_name    = "genai-prod-usw2"
  cluster_version = "1.30"
  region          = "us-west-2"
  vpc_cidr        = "10.1.0.0/16"  # Different CIDR from us-east-1
}

module "rds" {
  source       = "../../modules/rds"
  identifier   = "genai-db-usw2"
  # Create read replica first, then promote
  replicate_source_db = "arn:aws:rds:us-east-1:123456:db:genai-db"
}
```

**S3 replication for model artifacts:**

```bash
# Enable cross-region replication
aws s3api put-bucket-replication \
  --bucket genai-models-use1 \
  --replication-configuration '{
    "Role": "arn:aws:iam::role/s3-replication",
    "Rules": [{
      "Status": "Enabled",
      "Destination": {
        "Bucket": "arn:aws:s3:::genai-models-usw2",
        "StorageClass": "STANDARD"
      }
    }]
  }'

# Sync existing data
aws s3 sync s3://genai-models-use1 s3://genai-models-usw2 --region us-west-2
```

**DNS weighted routing for cutover:**

```bash
# Phase 1: 90/10 split (test new region with 10% traffic)
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID \
  --change-batch '{
    "Changes": [
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "api.genai.example.com",
          "Type": "A",
          "SetIdentifier": "us-east-1",
          "Weight": 90,
          "AliasTarget": {"HostedZoneId": "$ALB_ZONE_USE1", "DNSName": "$ALB_USE1"}
        }
      },
      {
        "Action": "UPSERT",
        "ResourceRecordSet": {
          "Name": "api.genai.example.com",
          "Type": "A",
          "SetIdentifier": "us-west-2",
          "Weight": 10,
          "AliasTarget": {"HostedZoneId": "$ALB_ZONE_USW2", "DNSName": "$ALB_USW2"}
        }
      }
    ]
  }'

# Phase 2: After validation, shift to 0/100
# Phase 3: Decommission old region
```

### Cloud Swap (AWS to GCP)

| Layer | Portable | Changes Required |
|---|---|---|
| **K8s manifests** | Yes (mostly) | Node selectors, storage classes, GPU resource names |
| **Helm charts** | Yes | Values files change (ingress, storage) |
| **Application code** | Yes | SDK changes (boto3 → google-cloud) |
| **Terraform** | No | Rewrite: aws_* → google_* resources |
| **IAM** | No | AWS IAM roles → GCP Workload Identity |
| **Storage** | No | S3 → GCS, EBS → Persistent Disk |
| **Networking** | No | VPC, subnets, security groups → firewall rules |
| **Secrets** | No | AWS Secrets Manager → GCP Secret Manager |
| **CI/CD** | Partial | Pipeline structure same, auth/deploy commands change |
| **Monitoring** | Partial | Prometheus/Grafana portable, CloudWatch → Cloud Monitoring |

**Key K8s manifest changes:**

```yaml
# AWS (EKS)
resources:
  limits:
    nvidia.com/gpu: 1
nodeSelector:
  node.kubernetes.io/instance-type: g5.xlarge
storageClassName: gp3

# GCP (GKE)
resources:
  limits:
    nvidia.com/gpu: 1  # Same
nodeSelector:
  cloud.google.com/gke-accelerator: nvidia-l4  # Different
storageClassName: premium-rwo  # Different
```

---

## 7. Dependency Upgrades

### Python Dependency Strategy

**Pin major versions, auto-update patches.**

```
# requirements.in (input for pip-compile)
langchain-core>=0.3,<0.4
langchain-openai>=0.2,<0.3
fastapi>=0.110,<1.0
uvicorn>=0.27,<1.0
psycopg2-binary>=2.9,<3.0
pgvector>=0.3,<0.4
pydantic>=2.0,<3.0
torch>=2.2,<3.0

# Generate locked requirements
pip-compile requirements.in --output-file requirements.txt --generate-hashes
```

**pip-compile produces:**

```
# requirements.txt (locked, with hashes for security)
langchain-core==0.3.15 \
    --hash=sha256:abc123...
langchain-openai==0.2.8 \
    --hash=sha256:def456...
# ... all transitive dependencies locked
```

### Automated Updates with Renovate

```json
// renovate.json
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended"],
  "packageRules": [
    {
      "matchManagers": ["pip_requirements"],
      "matchUpdateTypes": ["patch"],
      "automerge": true,
      "automergeType": "pr"
    },
    {
      "matchManagers": ["pip_requirements"],
      "matchUpdateTypes": ["minor"],
      "automerge": false,
      "labels": ["dependency-update", "needs-review"]
    },
    {
      "matchManagers": ["pip_requirements"],
      "matchUpdateTypes": ["major"],
      "automerge": false,
      "labels": ["dependency-update", "breaking-change"]
    },
    {
      "matchPackageNames": ["torch", "transformers"],
      "groupName": "ML framework updates",
      "schedule": ["before 6am on monday"]
    }
  ]
}
```

### CI Test Matrix

```yaml
# .github/workflows/dependency-test.yaml
name: Dependency Test Matrix
on:
  pull_request:
    paths:
      - 'requirements*.txt'
      - 'pyproject.toml'

jobs:
  test:
    strategy:
      matrix:
        python-version: ["3.11", "3.12"]
        include:
          - python-version: "3.11"
            torch-version: "2.2"
          - python-version: "3.12"
            torch-version: "2.3"
    runs-on: ubuntu-latest
    steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with:
        python-version: ${{ matrix.python-version }}
    - name: Install dependencies
      run: pip install -r requirements.txt
    - name: Run tests
      run: pytest tests/ -v --tb=short
    - name: Check for import errors
      run: python -c "from app.main import app; print('Import OK')"
```

---

## 8. Rollback Procedures

### Rollback Matrix

| Migration Type | Rollback Method | Expected Downtime | Data Implications |
|---|---|---|---|
| **EKS blue-green** | Switch DNS/LB back to old cluster | < 5 minutes (DNS TTL) | None (old cluster still running) |
| **EKS in-place** | Cannot easily rollback K8s version | N/A | Must fix forward or rebuild |
| **Model canary** | Shift Istio weight to 100% v1 | 0 (v1 still running) | None |
| **pgvector re-embedding** | Keep using old column | 0 | Old embeddings still available |
| **LangChain migration** | Revert Git commit, redeploy | Minutes (deploy time) | None |
| **Region migration** | Shift DNS weight back | < 5 minutes (DNS TTL) | Check DB replication lag |
| **Dependency upgrade** | Revert requirements.txt, redeploy | Minutes (deploy time) | None |

### EKS Blue-Green Rollback

```bash
# Old cluster is still running — just switch traffic back
aws elbv2 modify-target-group \
  --target-group-arn $OLD_TG_ARN \
  --targets ...

# Or switch DNS
aws route53 change-resource-record-sets --hosted-zone-id $ZONE_ID \
  --change-batch '{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{
    "Name":"api.example.com","Type":"A",
    "AliasTarget":{"DNSName":"$OLD_ALB","HostedZoneId":"$OLD_ZONE"}
  }}]}'
```

### Model Rollback

```bash
# Immediate — v1 is still running
kubectl patch virtualservice rag-generator-vs --type merge \
  -p '{"spec":{"http":[{"route":[
    {"destination":{"host":"rag-generator","subset":"v1","port":{"number":8000}},"weight":100}
  ]}]}}'

# Clean up failed canary
kubectl delete deployment rag-generator-v2
```

### Database Rollback

```sql
-- If migration added a column (non-destructive), just stop using it
-- Application code reverted via Git revert + deploy

-- If migration was destructive (dropped column), restore from backup
-- This is why we keep old columns during migration window

-- Point-in-time recovery (last resort)
-- AWS RDS supports PITR to any second within the backup retention window
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier genai-db \
  --target-db-instance-identifier genai-db-rollback \
  --restore-time "2024-03-15T14:30:00Z"
```

### Application Rollback

```bash
# Revert to previous deployment (K8s keeps revision history)
kubectl rollout undo deployment/rag-service
kubectl rollout undo deployment/api-gateway

# Or revert to a specific revision
kubectl rollout history deployment/rag-service
kubectl rollout undo deployment/rag-service --to-revision=3

# Verify
kubectl rollout status deployment/rag-service
```

---

## 9. Pre-Migration Checklist

Universal checklist before ANY migration. Print this, tape it to your monitor.

### Before Migration

- [ ] **Backup everything**
  - Database: snapshot/backup verified and tested
  - Configuration: all configs in Git
  - Secrets: exported and stored securely
  - Model artifacts: verified in object storage

- [ ] **Test in staging first**
  - Run the exact migration procedure in staging
  - Run full e2e test suite against staging after migration
  - Note any surprises, update the production procedure

- [ ] **Communication plan**
  - Team notified of maintenance window
  - Stakeholders informed of potential impact
  - Status page updated (if external-facing)
  - On-call rotation aware and staffed

- [ ] **Rollback plan documented**
  - Step-by-step rollback procedure written out
  - Rollback tested in staging
  - Rollback criteria defined ("rollback if error rate > 1% for 5 minutes")
  - Rollback owner designated

- [ ] **Monitoring ready**
  - Dashboards open: latency, error rate, throughput, GPU util
  - Alerts configured for degradation
  - Log aggregation working
  - Comparison metrics from before migration captured (baseline)

- [ ] **On-call staffed**
  - Primary and secondary on-call assigned
  - Escalation path clear
  - All team members have access to necessary tools (kubectl, cloud console, etc.)

### During Migration

- [ ] **Execute step by step** — follow the runbook exactly, do not improvise
- [ ] **Verify each step** — check the expected outcome before proceeding to the next step
- [ ] **Monitor continuously** — eyes on dashboards throughout
- [ ] **Communicate progress** — post updates to the team channel at each milestone
- [ ] **Time-box** — if the migration takes longer than expected, consider rollback

### After Migration

- [ ] **Smoke tests pass** — run automated and manual verification
- [ ] **Metrics normal** — compare against pre-migration baseline
- [ ] **No error spike** — check logs for new errors
- [ ] **Performance acceptable** — latency and throughput within bounds
- [ ] **Clean up** — remove old resources after burn-in period (24-48 hours minimum)
- [ ] **Document** — update runbooks with any deviations or lessons learned
- [ ] **Retrospective** — what went well, what to improve for next time

---

## 10. Interview Q&As

### Q1: "How would you upgrade an EKS cluster with GPU workloads running in production?"

**Answer:** "I'd use a blue-green cluster migration. First, I create a new EKS cluster at the target version using Terraform, keeping the old cluster running. I install the NVIDIA GPU Operator compatible with the new K8s version — this is the highest-risk compatibility point. I deploy all workloads to the new cluster and run smoke tests, including a GPU test pod that verifies CUDA is functional. Then I shift traffic via Route53 weighted routing or ALB target group swap. I keep the old cluster running for 24-48 hours as a hot standby, then decommission it. The key advantage over in-place upgrade is that rollback is instant — just switch traffic back. For in-place upgrades, you can't easily downgrade the K8s control plane version, so a failed upgrade is much harder to recover from."

### Q2: "You need to change your embedding model in production. The new model has different dimensions. How do you handle this without downtime?"

**Answer:** "Four-phase migration. Phase one: add a new column with the new vector dimension — `ALTER TABLE ADD COLUMN embedding_v2 vector(3072)`. Phase two: create the HNSW index using `CREATE INDEX CONCURRENTLY` — this is critical because without CONCURRENTLY, it locks the table for the entire index build, which can take hours on millions of rows. Phase three: run a background re-embedding job that processes documents in batches, using `FOR UPDATE SKIP LOCKED` so multiple workers can run in parallel. The application continues using the old column during this entire process. Phase four: once all documents are re-embedded, switch the application queries to use the new column, monitor for 24-48 hours, then drop the old column. Zero downtime because the old index serves queries throughout the migration."

### Q3: "How does your canary deployment for models differ from a standard software canary?"

**Answer:** "Three key differences. First, the quality gate — for software, we check error rate and latency. For models, we also need to evaluate output quality, which often requires LLM-as-judge scoring on a sample of responses. A model can return 200 OK with fast latency but produce garbage answers. Second, the monitoring window is longer — software canaries might run 10-15 minutes, but model canaries need 30-60 minutes per stage because we need enough inference volume to detect quality issues statistically. Third, the warm standby cost — both model versions must be loaded in GPU memory simultaneously, which doubles GPU cost during the canary window. For large models, this means we need the GPU capacity to run both versions, which we plan for in advance."

### Q4: "How do you handle LangChain version upgrades when they deprecate major components?"

**Answer:** "The LangChain 0.2 to 0.3 migration was substantial — they deprecated legacy chains in favor of LCEL and LangGraph, changed import paths to partner packages, and deprecated LangServe. My approach: first, I update imports from the monolithic `langchain` package to the new partner packages — `langchain-openai`, `langchain-community`, `langchain-core`. Second, I replace deprecated chain classes with LCEL pipe syntax — for example, `RetrievalQA` becomes a chain of `retriever | format_docs | prompt | llm | output_parser`. Third, for complex flows with routing or state management, I migrate to LangGraph's stateful graph model. I do this incrementally — update one service at a time, test in staging, deploy. The key lesson: don't use framework-specific abstractions for critical business logic. Keep your core logic framework-agnostic so you're not rewriting everything when the framework changes."

### Q5: "Describe your rollback strategy for a production database migration."

**Answer:** "My core principle is: never make destructive changes during the forward migration. For schema changes, I add new columns but keep old ones. For re-embedding, I add a new column alongside the existing one. The application continues using old columns until the migration is verified. This means rollback is trivial — revert the application code to use old columns, and the new columns are just unused. I only drop old columns after a burn-in period of 24-48 hours. For cases where destructive changes are unavoidable, I take a database snapshot before starting, test the migration on a snapshot clone first, and have RDS point-in-time recovery as a last resort. The worst rollback scenario is restoring from backup, which means some data loss — so I design migrations to avoid that scenario entirely by using the add-new-switch-drop pattern."

---

*Last updated: 2026-03-18*
