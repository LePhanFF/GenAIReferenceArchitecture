# Adding a Workload: Framework-Agnostic Service Deployment

## The Platform Promise

Any containerized workload deploys the same way. The platform does not care about your framework, language, or AI library. LangChain, LlamaIndex, CrewAI, AutoGen, Haystack, custom Python, Go, Rust -- it all works identically.

The contract is simple:
1. Your code runs in a container
2. You provide Kubernetes manifests
3. You register with Kustomize
4. ArgoCD deploys it

Everything else -- cluster provisioning, GPU scheduling, networking, TLS, monitoring scraping, artifact access -- is already handled by the platform.

## Steps to Add a New Service

### Step 1: Create the Service

Add your application code under `services/`:

```
services/<name>/
  app/
    main.py              # Your code (FastAPI, Flask, whatever)
    __init__.py
  Dockerfile             # How to build it
  requirements.txt       # Dependencies
```

The only requirements for your service:
- It listens on a port (default: 8000)
- It has a health check endpoint (`/health` or `/healthz`)
- Optionally: it exposes Prometheus metrics at `/metrics`

### Step 2: Create the Kubernetes Manifests

Add deployment manifests under the appropriate workloads directory:

**For inference/serving workloads:**
```
workloads/inference/base/<name>/
  deployment.yaml        # How to run it
  service.yaml           # How to expose it
```

**For training workloads:**
```
workloads/training/base/<name>/
  job.yaml               # Or deployment.yaml for long-running services like JupyterLab
```

Minimal `deployment.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: <name>
  namespace: inference
spec:
  replicas: 1
  selector:
    matchLabels:
      app: <name>
  template:
    metadata:
      labels:
        app: <name>
    spec:
      containers:
        - name: <name>
          image: ghcr.io/your-org/<name>:latest
          ports:
            - containerPort: 8000
          env:
            - name: VLLM_ENDPOINT
              value: "http://vllm:8000"
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2"
              memory: "2Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
```

Minimal `service.yaml`:
```yaml
apiVersion: v1
kind: Service
metadata:
  name: <name>
  namespace: inference
spec:
  selector:
    app: <name>
  ports:
    - port: 8000
      targetPort: 8000
```

### Step 3: Register with Kustomize

Add your manifests to the appropriate `kustomization.yaml`:

```yaml
# workloads/inference/base/kustomization.yaml
resources:
  - vllm/deployment.yaml
  - vllm/service.yaml
  - rag-service/deployment.yaml
  - rag-service/service.yaml
  - <name>/deployment.yaml          # Add this
  - <name>/service.yaml             # Add this
```

### Step 4: Push

```bash
git add .
git commit -m "Add <name> service"
git push
```

ArgoCD detects the change, syncs the manifests, and your service is deployed in approximately 3 minutes.

## Example: Adding a LlamaIndex RAG Service

You already have a LangChain-based RAG service. Now you want to add a LlamaIndex-based one alongside it -- maybe for a different use case, or to A/B test frameworks.

### Step 1: Create the service

```
services/llamaindex-rag/
  app/
    main.py
  Dockerfile
  requirements.txt
```

**`services/llamaindex-rag/requirements.txt`:**
```
fastapi==0.115.0
uvicorn==0.30.0
llama-index==0.11.0
llama-index-vector-stores-postgres==0.2.0
llama-index-llms-openai-like==0.2.0
```

**`services/llamaindex-rag/app/main.py`:**
```python
from fastapi import FastAPI
from llama_index.core import VectorStoreIndex, Settings
from llama_index.vector_stores.postgres import PGVectorStore
from llama_index.llms.openai_like import OpenAILike
import os

app = FastAPI()

# Point LlamaIndex at our internal vLLM endpoint
Settings.llm = OpenAILike(
    api_base=os.getenv("VLLM_ENDPOINT", "http://vllm:8000") + "/v1",
    model=os.getenv("MODEL_NAME", "qwen2.5-1.5b"),
    api_key="not-needed",
)

# Connect to the same pgvector database
vector_store = PGVectorStore.from_params(
    host=os.getenv("PGVECTOR_HOST", "pgvector"),
    port=5432,
    database="vectors",
    table_name="llamaindex_docs",
)
index = VectorStoreIndex.from_vector_store(vector_store)
query_engine = index.as_query_engine()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query")
def query(request: dict):
    response = query_engine.query(request["question"])
    return {"answer": str(response), "sources": [n.text for n in response.source_nodes]}
```

**`services/llamaindex-rag/Dockerfile`:**
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 2: Create the manifests

```
workloads/inference/base/llamaindex-rag/
  deployment.yaml
  service.yaml
```

**`deployment.yaml`:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llamaindex-rag
  namespace: inference
spec:
  replicas: 2
  selector:
    matchLabels:
      app: llamaindex-rag
  template:
    metadata:
      labels:
        app: llamaindex-rag
    spec:
      containers:
        - name: llamaindex-rag
          image: ghcr.io/your-org/llamaindex-rag:latest
          ports:
            - containerPort: 8000
          env:
            - name: VLLM_ENDPOINT
              value: "http://vllm:8000"
            - name: PGVECTOR_HOST
              value: "pgvector"
            - name: MODEL_NAME
              value: "qwen2.5-1.5b"
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2"
              memory: "2Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
```

**`service.yaml`:**
```yaml
apiVersion: v1
kind: Service
metadata:
  name: llamaindex-rag
  namespace: inference
spec:
  selector:
    app: llamaindex-rag
  ports:
    - port: 8000
      targetPort: 8000
```

### Step 3: Register with Kustomize

```yaml
# workloads/inference/base/kustomization.yaml
resources:
  - vllm/deployment.yaml
  - vllm/service.yaml
  - rag-service/deployment.yaml
  - rag-service/service.yaml
  - llamaindex-rag/deployment.yaml     # New
  - llamaindex-rag/service.yaml        # New
```

### Step 4: Push and deploy

```bash
git add services/llamaindex-rag/ workloads/inference/base/llamaindex-rag/
git commit -m "Add LlamaIndex RAG service alongside LangChain RAG"
git push
# ArgoCD syncs automatically
```

Now you have two RAG services running side by side. Route traffic between them via your ingress or API gateway.

## Example: Adding a CrewAI Agent Service

CrewAI uses a multi-agent architecture. The platform handles it exactly the same way.

### Step 1: Create the service

```
services/crewai-agents/
  app/
    main.py
    crews/
      research_crew.py
  Dockerfile
  requirements.txt
```

**`services/crewai-agents/requirements.txt`:**
```
fastapi==0.115.0
uvicorn==0.30.0
crewai==0.80.0
crewai-tools==0.14.0
```

**`services/crewai-agents/app/main.py`:**
```python
from fastapi import FastAPI
from crewai import Agent, Task, Crew, LLM
import os

app = FastAPI()

# Point CrewAI at our internal vLLM endpoint
llm = LLM(
    model=f"openai/{os.getenv('MODEL_NAME', 'qwen2.5-1.5b')}",
    base_url=os.getenv("VLLM_ENDPOINT", "http://vllm:8000") + "/v1",
    api_key="not-needed",
)

researcher = Agent(
    role="Research Analyst",
    goal="Find and summarize relevant information",
    llm=llm,
)

writer = Agent(
    role="Technical Writer",
    goal="Create clear, concise reports",
    llm=llm,
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/research")
def research(request: dict):
    task1 = Task(description=f"Research: {request['topic']}", agent=researcher)
    task2 = Task(description="Write a summary report", agent=writer)
    crew = Crew(agents=[researcher, writer], tasks=[task1, task2])
    result = crew.kickoff()
    return {"result": str(result)}
```

### Step 2: Create manifests and register

Same pattern as the LlamaIndex example -- create `workloads/inference/base/crewai-agents/deployment.yaml` and `service.yaml`, add to `kustomization.yaml`, push.

The deployment is identical. CrewAI, LangChain, LlamaIndex -- the platform treats them all as containers that listen on a port.

## What You Don't Need to Change

When adding a new workload, the following platform components require **zero modification**:

| Component | Why It Just Works |
|-----------|-------------------|
| **Terraform** | Cluster infrastructure doesn't know or care about your framework. Nodes, networking, IAM are all workload-agnostic. |
| **ArgoCD** | It syncs any manifest in the `workloads/` directory tree. Adding files to a Kustomize resource list is all it takes. |
| **CI/CD** | Add a build matrix entry for your new service image. The pipeline structure (build, push, update tag) is the same. |
| **Monitoring** | Prometheus automatically scrapes any pod with a `/metrics` endpoint. Grafana dashboards can be added but aren't required. |
| **Storage** | Same PVCs, same artifact store access. Your service reads models from the same S3 bucket via the same service account. |
| **Networking** | Cluster DNS resolves service names automatically. `http://vllm:8000` works for any pod in the namespace. |
| **Secrets** | Shared secrets (API keys, DB credentials) are already in the namespace. Your pod picks them up via env vars or volume mounts. |
| **GPU scheduling** | If your workload needs a GPU, add a `nvidia.com/gpu: 1` resource request. The existing node autoscaler handles provisioning. |

## Checklist for New Workloads

```
[ ] Service code exists in services/<name>/
[ ] Dockerfile builds and runs locally
[ ] Health check endpoint works (/health or /healthz)
[ ] Kubernetes manifests created in workloads/{training|inference}/base/<name>/
[ ] Manifests registered in kustomization.yaml
[ ] Resource requests and limits set appropriately
[ ] Environment variables configured (VLLM_ENDPOINT, model names, etc.)
[ ] Liveness and readiness probes configured
[ ] (Optional) /metrics endpoint for Prometheus scraping
[ ] (Optional) HPA or KEDA scaler configured for autoscaling
[ ] Pushed to git, ArgoCD syncing
```
