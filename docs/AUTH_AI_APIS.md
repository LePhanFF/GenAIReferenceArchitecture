# Authentication & Rate Limiting for AI APIs

## 1. Why AI APIs Need Different Auth

Traditional API auth gates access and counts requests. AI APIs have a fundamentally different cost model:

| Dimension | Traditional API | AI/LLM API |
|-----------|----------------|------------|
| **Cost unit** | Per request (roughly equal) | Per token (varies 100x between prompts) |
| **Resource consumption** | CPU/memory (elastic) | GPU VRAM (fixed, scarce) |
| **Latency** | Milliseconds | Seconds to minutes |
| **Concurrency impact** | Linear degradation | Cliff — GPU OOM kills everything |
| **Abuse risk** | DDoS, scraping | Prompt injection, model extraction, crypto-mining GPU theft |

A single request with a 128k context window costs ~$4 on GPT-4 class models. A traditional per-request rate limit of "100 req/min" is meaningless when one request can burn $4 and another $0.001.

**You need:**
- Token-aware rate limiting (input + output tokens)
- Model-scoped permissions (not all keys get access to expensive models)
- Spend caps per tenant/team
- GPU concurrency limits (max parallel inference requests)

---

## 2. API Key Management

### Key Generation and Storage

Never store raw API keys. Hash them like passwords but use a fast hash (SHA-256) since keys are high-entropy (unlike passwords, brute force isn't viable).

```python
# api_keys/models.py
import secrets
import hashlib
from datetime import datetime, timedelta
from sqlalchemy import Column, String, DateTime, Integer, Boolean, JSON
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class APIKey(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True)
    key_hash = Column(String(64), unique=True, index=True)  # SHA-256
    key_prefix = Column(String(8))  # First 8 chars for identification
    tenant_id = Column(String, nullable=False)
    name = Column(String)  # Human-readable label

    # Scoping
    allowed_models = Column(JSON, default=["llama-3-8b"])  # Which models this key can access
    allowed_endpoints = Column(JSON, default=["/v1/chat/completions"])
    max_tokens_per_minute = Column(Integer, default=10_000)
    max_tokens_per_day = Column(Integer, default=500_000)
    max_concurrent_requests = Column(Integer, default=5)
    spend_limit_usd = Column(Integer, default=100)  # Monthly spend cap

    # Lifecycle
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)
    last_used_at = Column(DateTime)
    revoked = Column(Boolean, default=False)
    revoked_at = Column(DateTime)


def generate_api_key(tenant_id: str, name: str, **scopes) -> tuple[str, APIKey]:
    """Generate a new API key. Returns (raw_key, db_record).

    The raw key is shown ONCE to the user. We only store the hash.
    """
    raw_key = f"sk-{secrets.token_urlsafe(32)}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

    record = APIKey(
        id=secrets.token_urlsafe(16),
        key_hash=key_hash,
        key_prefix=raw_key[:8],
        tenant_id=tenant_id,
        name=name,
        expires_at=datetime.utcnow() + timedelta(days=90),
        **scopes,
    )
    return raw_key, record


def verify_api_key(raw_key: str, db_session) -> APIKey | None:
    """Look up and validate an API key."""
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    record = db_session.query(APIKey).filter_by(key_hash=key_hash).first()

    if not record:
        return None
    if record.revoked:
        return None
    if record.expires_at and record.expires_at < datetime.utcnow():
        return None

    # Update last_used_at
    record.last_used_at = datetime.utcnow()
    db_session.commit()
    return record
```

### FastAPI Auth Middleware

```python
# middleware/auth.py
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer
from starlette.middleware.base import BaseHTTPMiddleware

security = HTTPBearer()

class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip health checks
        if request.url.path in ("/health", "/ready", "/metrics"):
            return await call_next(request)

        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing API key")

        raw_key = auth_header.replace("Bearer ", "")
        api_key = verify_api_key(raw_key, request.state.db)

        if not api_key:
            raise HTTPException(status_code=401, detail="Invalid or expired API key")

        # Check model scope
        body = await request.json() if request.method == "POST" else {}
        requested_model = body.get("model", "")
        if requested_model and requested_model not in api_key.allowed_models:
            raise HTTPException(
                status_code=403,
                detail=f"Key not authorized for model '{requested_model}'. "
                       f"Allowed: {api_key.allowed_models}"
            )

        # Check endpoint scope
        if request.url.path not in api_key.allowed_endpoints:
            raise HTTPException(status_code=403, detail="Endpoint not allowed for this key")

        # Attach key info to request state for downstream use
        request.state.api_key = api_key
        request.state.tenant_id = api_key.tenant_id

        response = await call_next(request)
        return response
```

### Key Rotation Strategy

```
1. User creates new key (old key still active)
2. User updates their systems to use new key
3. User revokes old key
4. Grace period: revoked keys return 401 with "key_rotated" error code
   (so misconfigured services get a clear signal, not a generic auth failure)
```

Never auto-expire without warning. Send alerts at 7d, 3d, 1d before expiry via webhook.

---

## 3. OAuth2/OIDC Integration

For internal teams, API keys are clunky. Use OIDC with JWTs — teams authenticate through your IdP, and JWT claims determine their access tier.

### JWT Validation in FastAPI

```python
# auth/jwt_auth.py
from jose import jwt, JWTError
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import httpx
from functools import lru_cache

security = HTTPBearer()

# Cache JWKS for 1 hour
@lru_cache(maxsize=1)
def get_jwks(jwks_url: str) -> dict:
    response = httpx.get(jwks_url)
    return response.json()

class JWTAuth:
    def __init__(
        self,
        jwks_url: str,          # e.g., https://cognito-idp.us-east-1.amazonaws.com/{pool_id}/.well-known/jwks.json
        issuer: str,            # e.g., https://cognito-idp.us-east-1.amazonaws.com/{pool_id}
        audience: str,          # Your API's client ID
    ):
        self.jwks_url = jwks_url
        self.issuer = issuer
        self.audience = audience

    async def __call__(
        self, credentials: HTTPAuthorizationCredentials = Security(security)
    ) -> dict:
        token = credentials.credentials
        try:
            jwks = get_jwks(self.jwks_url)

            # Get the signing key
            unverified_header = jwt.get_unverified_header(token)
            key = next(
                k for k in jwks["keys"]
                if k["kid"] == unverified_header["kid"]
            )

            payload = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
            return payload

        except StopIteration:
            raise HTTPException(status_code=401, detail="Unknown signing key")
        except JWTError as e:
            raise HTTPException(status_code=401, detail=f"Token validation failed: {e}")


# Initialize for your IdP
jwt_auth = JWTAuth(
    jwks_url="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xxxxx/.well-known/jwks.json",
    issuer="https://cognito-idp.us-east-1.amazonaws.com/us-east-1_xxxxx",
    audience="your-app-client-id",
)
```

### Claims-Based Routing

Embed AI-specific claims in your JWT (via Cognito pre-token-generation Lambda or Auth0 Actions):

```python
# auth/claims_router.py
from dataclasses import dataclass

# Expected custom claims in JWT:
# {
#   "sub": "user-123",
#   "custom:team": "ml-research",
#   "custom:tier": "premium",           # free | standard | premium
#   "custom:allowed_models": "llama-3-70b,mixtral-8x7b,llama-3-8b",
#   "custom:max_tokens_per_min": "50000",
#   "custom:max_concurrent": "10"
# }

TIER_DEFAULTS = {
    "free":     {"models": ["llama-3-8b"], "tpm": 5_000, "concurrent": 2},
    "standard": {"models": ["llama-3-8b", "llama-3-70b"], "tpm": 20_000, "concurrent": 5},
    "premium":  {"models": ["llama-3-8b", "llama-3-70b", "mixtral-8x7b"], "tpm": 100_000, "concurrent": 20},
}

@dataclass
class UserContext:
    user_id: str
    team: str
    tier: str
    allowed_models: list[str]
    max_tokens_per_minute: int
    max_concurrent_requests: int

def extract_user_context(claims: dict) -> UserContext:
    """Extract AI-specific context from JWT claims."""
    tier = claims.get("custom:tier", "free")
    defaults = TIER_DEFAULTS[tier]

    # Claims override defaults if present
    models_claim = claims.get("custom:allowed_models", "")
    models = models_claim.split(",") if models_claim else defaults["models"]

    return UserContext(
        user_id=claims["sub"],
        team=claims.get("custom:team", "default"),
        tier=tier,
        allowed_models=models,
        max_tokens_per_minute=int(claims.get("custom:max_tokens_per_min", defaults["tpm"])),
        max_concurrent_requests=int(claims.get("custom:max_concurrent", defaults["concurrent"])),
    )


# Usage in FastAPI endpoint
from fastapi import Depends

@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatRequest,
    claims: dict = Depends(jwt_auth),
):
    ctx = extract_user_context(claims)

    if request.model not in ctx.allowed_models:
        raise HTTPException(403, f"Model {request.model} not in your tier ({ctx.tier})")

    # Pass ctx to rate limiter, then to inference
    await check_rate_limit(ctx)
    return await run_inference(request, ctx)
```

---

## 4. Token-Based Rate Limiting

### Why Per-Request Limits Fail for LLMs

```
User A: 100 requests/min, each 50 tokens  →  5,000 tokens/min  →  ~$0.01
User B: 100 requests/min, each 50,000 tokens  →  5,000,000 tokens/min  →  ~$10.00

Same rate limit. 1000x cost difference.
```

You need to track **input tokens + output tokens** per key, per time window.

### Redis-Backed Token Counter

```python
# ratelimit/token_limiter.py
import redis.asyncio as redis
import time
from fastapi import HTTPException

r = redis.Redis(host="redis", port=6379, decode_responses=True)

class TokenRateLimiter:
    """Sliding window token rate limiter using Redis."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    async def check_and_reserve(
        self,
        key_id: str,
        estimated_input_tokens: int,
        max_output_tokens: int,
        limit_tokens_per_minute: int,
    ) -> None:
        """Pre-request check. Reserves estimated tokens.

        We estimate input tokens from the prompt length and reserve
        max_output_tokens. After response, we reconcile with actuals.
        """
        now = int(time.time())
        window_key = f"tpm:{key_id}:{now // 60}"  # 1-minute window
        daily_key = f"tpd:{key_id}:{now // 86400}"  # Daily window

        # Get current usage in this window
        current = await self.redis.get(window_key)
        current_tokens = int(current) if current else 0

        estimated_total = estimated_input_tokens + max_output_tokens

        if current_tokens + estimated_total > limit_tokens_per_minute:
            retry_after = 60 - (now % 60)
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "token_rate_limit_exceeded",
                    "current_tokens": current_tokens,
                    "requested_tokens": estimated_total,
                    "limit": limit_tokens_per_minute,
                    "retry_after_seconds": retry_after,
                },
                headers={"Retry-After": str(retry_after)},
            )

        # Reserve tokens (pipeline for atomicity)
        pipe = self.redis.pipeline()
        pipe.incrby(window_key, estimated_total)
        pipe.expire(window_key, 120)  # TTL = 2 minutes (covers window + buffer)
        pipe.incrby(daily_key, estimated_total)
        pipe.expire(daily_key, 172800)
        await pipe.execute()

    async def reconcile(
        self,
        key_id: str,
        estimated_tokens: int,
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> None:
        """Post-response: adjust reservation to actual usage."""
        now = int(time.time())
        window_key = f"tpm:{key_id}:{now // 60}"
        daily_key = f"tpd:{key_id}:{now // 86400}"

        actual_total = actual_input_tokens + actual_output_tokens
        delta = actual_total - estimated_tokens

        # Adjust (can be negative if we over-estimated)
        if delta != 0:
            pipe = self.redis.pipeline()
            pipe.incrby(window_key, delta)
            pipe.incrby(daily_key, delta)
            await pipe.execute()

    async def get_usage(self, key_id: str) -> dict:
        """Get current usage stats for headers."""
        now = int(time.time())
        window_key = f"tpm:{key_id}:{now // 60}"
        daily_key = f"tpd:{key_id}:{now // 86400}"

        pipe = self.redis.pipeline()
        pipe.get(window_key)
        pipe.get(daily_key)
        minute_usage, daily_usage = await pipe.execute()

        return {
            "tokens_used_this_minute": int(minute_usage or 0),
            "tokens_used_today": int(daily_usage or 0),
        }

limiter = TokenRateLimiter(r)
```

### Concurrency Limiter (GPU Protection)

GPU OOM is catastrophic — it kills all concurrent requests. Limit concurrency per key AND globally:

```python
# ratelimit/concurrency.py
import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import HTTPException

class ConcurrencyLimiter:
    """Limits concurrent inference requests to protect GPU memory."""

    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    @asynccontextmanager
    async def acquire(self, key_id: str, max_per_key: int, max_global: int = 50):
        per_key = f"concurrent:{key_id}"
        global_key = "concurrent:global"

        # Check both limits
        pipe = self.redis.pipeline()
        pipe.get(per_key)
        pipe.get(global_key)
        key_count, global_count = await pipe.execute()

        if int(key_count or 0) >= max_per_key:
            raise HTTPException(429, "Too many concurrent requests for this key")
        if int(global_count or 0) >= max_global:
            raise HTTPException(503, "Service at capacity, retry shortly")

        # Increment
        pipe = self.redis.pipeline()
        pipe.incr(per_key)
        pipe.expire(per_key, 300)  # Safety TTL
        pipe.incr(global_key)
        pipe.expire(global_key, 300)
        await pipe.execute()

        try:
            yield
        finally:
            # Decrement
            pipe = self.redis.pipeline()
            pipe.decr(per_key)
            pipe.decr(global_key)
            await pipe.execute()
```

### FastAPI Middleware Combining Everything

```python
# middleware/rate_limit.py
from starlette.middleware.base import BaseHTTPMiddleware
import tiktoken

class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/ready", "/metrics"):
            return await call_next(request)

        api_key = request.state.api_key  # Set by auth middleware

        # Estimate tokens from request body
        body = await request.json()
        messages = body.get("messages", [])
        max_output = body.get("max_tokens", 1024)

        # Quick token estimate (tiktoken or len/4 approximation)
        input_text = " ".join(m.get("content", "") for m in messages)
        estimated_input = len(input_text) // 4  # Rough estimate
        estimated_total = estimated_input + max_output

        # Check token rate limit
        await limiter.check_and_reserve(
            api_key.id, estimated_input, max_output,
            api_key.max_tokens_per_minute,
        )

        # Check concurrency
        async with concurrency_limiter.acquire(
            api_key.id, api_key.max_concurrent_requests
        ):
            response = await call_next(request)

        # Add usage headers
        usage = await limiter.get_usage(api_key.id)
        response.headers["X-Tokens-Used-Minute"] = str(usage["tokens_used_this_minute"])
        response.headers["X-Tokens-Limit-Minute"] = str(api_key.max_tokens_per_minute)

        return response
```

---

## 5. LiteLLM as Gateway

Building all of the above from scratch is substantial. **LiteLLM Proxy** gives you 80% of it out of the box.

### What LiteLLM Proxy Provides

- **Unified OpenAI-compatible API** in front of vLLM, Ollama, or any provider
- **Built-in API key management** with virtual keys, team budgets, spend tracking
- **Rate limiting** per key, per team (token-aware)
- **Model routing** — load balance across multiple vLLM instances
- **Spend tracking** — per-key, per-team, per-model cost attribution
- **Fallback chains** — if model A fails, try model B
- **Logging** to Langfuse, Prometheus, S3

### K8s Deployment

```yaml
# k8s/litellm-proxy.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: litellm-config
  namespace: ai-platform
data:
  config.yaml: |
    model_list:
      - model_name: llama-3-70b
        litellm_params:
          model: openai/llama-3-70b
          api_base: http://vllm-70b.ai-platform.svc:8000/v1
          api_key: "os.environ/VLLM_API_KEY"
          max_tokens: 4096
          rpm: 100    # requests per minute
          tpm: 500000 # tokens per minute
        model_info:
          input_cost_per_token: 0.00001  # For spend tracking
          output_cost_per_token: 0.00003

      - model_name: llama-3-8b
        litellm_params:
          model: openai/llama-3-8b
          api_base: http://vllm-8b.ai-platform.svc:8000/v1
          api_key: "os.environ/VLLM_API_KEY"
          rpm: 500
          tpm: 2000000

      # Fallback to external provider
      - model_name: llama-3-70b
        litellm_params:
          model: together_ai/meta-llama/Llama-3-70b-chat-hf
          api_key: "os.environ/TOGETHER_API_KEY"
          rpm: 50

    litellm_settings:
      drop_params: true
      set_verbose: false
      max_budget: 1000        # Global monthly budget USD
      budget_duration: monthly

    general_settings:
      master_key: "os.environ/LITELLM_MASTER_KEY"  # Admin key
      database_url: "os.environ/DATABASE_URL"       # PostgreSQL for keys/spend
      alerting:
        - slack
      alert_types:
        - budget_alerts
        - failed_tracking
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: litellm-proxy
  namespace: ai-platform
spec:
  replicas: 2
  selector:
    matchLabels:
      app: litellm-proxy
  template:
    metadata:
      labels:
        app: litellm-proxy
    spec:
      containers:
        - name: litellm
          image: ghcr.io/berriai/litellm:main-latest
          command: ["litellm", "--config", "/etc/litellm/config.yaml", "--port", "4000"]
          ports:
            - containerPort: 4000
          env:
            - name: LITELLM_MASTER_KEY
              valueFrom:
                secretKeyRef:
                  name: litellm-secrets
                  key: master-key
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: litellm-secrets
                  key: database-url
            - name: VLLM_API_KEY
              valueFrom:
                secretKeyRef:
                  name: litellm-secrets
                  key: vllm-api-key
          volumeMounts:
            - name: config
              mountPath: /etc/litellm
          resources:
            requests:
              cpu: 500m
              memory: 512Mi
            limits:
              cpu: "2"
              memory: 1Gi
          livenessProbe:
            httpGet:
              path: /health/liveliness
              port: 4000
            initialDelaySeconds: 10
          readinessProbe:
            httpGet:
              path: /health/readiness
              port: 4000
      volumes:
        - name: config
          configMap:
            name: litellm-config
---
apiVersion: v1
kind: Service
metadata:
  name: litellm-proxy
  namespace: ai-platform
spec:
  selector:
    app: litellm-proxy
  ports:
    - port: 4000
      targetPort: 4000
```

### Managing Keys via LiteLLM API

```bash
# Create a team
curl -X POST http://litellm-proxy:4000/team/new \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{
    "team_alias": "ml-research",
    "max_budget": 500,
    "budget_duration": "monthly",
    "models": ["llama-3-70b", "llama-3-8b"],
    "tpm_limit": 100000,
    "rpm_limit": 200
  }'

# Create a key for that team
curl -X POST http://litellm-proxy:4000/key/generate \
  -H "Authorization: Bearer $MASTER_KEY" \
  -d '{
    "team_id": "team-uuid-here",
    "key_alias": "alice-dev-key",
    "max_budget": 50,
    "duration": "90d",
    "models": ["llama-3-8b"],
    "tpm_limit": 20000
  }'

# Check spend
curl http://litellm-proxy:4000/team/info?team_id=team-uuid \
  -H "Authorization: Bearer $MASTER_KEY"
```

### Why LiteLLM Is the Easiest Path

| Build Custom | Use LiteLLM |
|-------------|-------------|
| Write auth middleware | Built-in key management |
| Build token counter in Redis | Built-in TPM/RPM limits |
| Build spend tracking | Per-key/team spend out of box |
| Build model routing | Config-driven model list |
| Build fallback logic | Automatic fallbacks |
| Build logging pipeline | Langfuse/Prometheus integrations |
| **Weeks of work** | **1 hour to deploy** |

Build custom only when you need: custom auth flows (OIDC with specific claims), sub-request-level billing, or priority queuing across tiers.

---

## 6. Multi-Tenant Architecture

### Namespace Isolation

```yaml
# k8s/tenant-namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: tenant-acme
  labels:
    tenant: acme
    tier: premium
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: gpu-quota
  namespace: tenant-acme
spec:
  hard:
    requests.nvidia.com/gpu: "4"
    limits.nvidia.com/gpu: "4"
    requests.cpu: "32"
    requests.memory: 128Gi
    persistentvolumeclaims: "10"
---
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: tenant-acme
spec:
  limits:
    - default:
        cpu: "4"
        memory: 16Gi
      defaultRequest:
        cpu: "1"
        memory: 4Gi
      type: Container
```

### Network Policies (Tenant Isolation)

```yaml
# k8s/network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: tenant-isolation
  namespace: tenant-acme
spec:
  podSelector: {}  # All pods in namespace
  policyTypes:
    - Ingress
    - Egress
  ingress:
    # Allow from API gateway only
    - from:
        - namespaceSelector:
            matchLabels:
              app: ai-gateway
      ports:
        - port: 8000
  egress:
    # Allow DNS
    - to:
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
    # Allow access to shared model storage (S3/EFS)
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8
      ports:
        - port: 2049  # NFS/EFS
    # Allow access to shared pgvector
    - to:
        - namespaceSelector:
            matchLabels:
              app: pgvector
      ports:
        - port: 5432
```

### Per-Tenant pgvector Schemas

Don't deploy a separate database per tenant. Use PostgreSQL schemas:

```sql
-- Per-tenant schema for vector isolation
CREATE SCHEMA IF NOT EXISTS tenant_acme;

CREATE TABLE tenant_acme.embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,  -- pgvector
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX ON tenant_acme.embeddings
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Row-Level Security as defense in depth
ALTER TABLE tenant_acme.embeddings ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_acme_policy ON tenant_acme.embeddings
    USING (current_setting('app.tenant_id') = 'acme');
```

```python
# In your API, set the schema per request:
async def get_db_session(tenant_id: str):
    session = SessionLocal()
    await session.execute(f"SET search_path TO tenant_{tenant_id}, public")
    await session.execute(f"SET app.tenant_id TO '{tenant_id}'")
    return session
```

### Architecture Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │              Ingress / ALB                   │
                    └─────────────────┬───────────────────────────┘
                                      │
                    ┌─────────────────▼───────────────────────────┐
                    │         LiteLLM Proxy (API Gateway)          │
                    │  - Auth (API keys / JWT)                     │
                    │  - Token rate limiting                       │
                    │  - Model routing                             │
                    │  - Spend tracking                            │
                    └──────┬──────────┬──────────┬────────────────┘
                           │          │          │
              ┌────────────▼──┐ ┌─────▼────┐ ┌──▼───────────┐
              │ ns: tenant-a  │ │ ns: tenant-b│ │ ns: shared   │
              │               │ │           │ │              │
              │ vLLM (8B)     │ │ vLLM (8B) │ │ vLLM (70B)   │
              │ 1x GPU        │ │ 1x GPU    │ │ 4x GPU       │
              │ Quota: 2 GPU  │ │ Quota: 1  │ │              │
              │               │ │           │ │              │
              │ NetworkPolicy │ │ NetPol    │ │ NetPol       │
              │ (isolated)    │ │ (isolated)│ │ (gateway in) │
              └──────┬────────┘ └─────┬─────┘ └──────┬───────┘
                     │                │               │
              ┌──────▼────────────────▼───────────────▼───────┐
              │              Shared PostgreSQL + pgvector       │
              │  schema: tenant_a  │  schema: tenant_b         │
              │  RLS enforced      │  RLS enforced              │
              └────────────────────────────────────────────────┘
```

---

## 7. Provider Comparison: Cognito vs Auth0 vs Keycloak

| Feature | AWS Cognito | Auth0 | Keycloak on EKS |
|---------|------------|-------|-----------------|
| **Hosting** | Managed (AWS) | Managed (SaaS) | Self-hosted (K8s) |
| **Cost** | Free to 50K MAU, then $0.0055/MAU | Free to 7.5K MAU, $23/1K MAU after | Free (OSS), you pay compute |
| **M2M / API keys** | App clients + client_credentials | Full M2M support, API keys native | Service accounts, client_credentials |
| **Custom claims** | Pre-token-generation Lambda | Actions (JS) — very flexible | Protocol mappers, SPI extensions |
| **OIDC compliance** | Partial (quirks with token endpoint) | Full | Full |
| **SCIM provisioning** | No (use Lambda triggers) | Yes (Enterprise) | Yes (plugin) |
| **MFA** | SMS, TOTP, WebAuthn | SMS, TOTP, WebAuthn, Push | TOTP, WebAuthn (via plugins) |
| **Group/Team mapping** | Cognito Groups → claims | Organizations (Enterprise) | Realm roles, groups, native |
| **Best for** | AWS-native, simple needs, cost-sensitive | Fast integration, rich features, small teams | Full control, large orgs, air-gapped |
| **Pitfalls** | Hosted UI is ugly, hard to customize. ALB integration doesn't forward custom claims. | Expensive at scale. Rate limits on management API. | Operational burden. Upgrades can break. DB management. |

### Recommendation for AI Platform

| Scenario | Pick |
|----------|------|
| Startup, AWS-native, < 50K users | **Cognito** — free, integrates with ALB/API GW |
| Multi-cloud, need fast dev, < 10K users | **Auth0** — best DX, Actions are powerful |
| Enterprise, on-prem/air-gapped, full control | **Keycloak** — deploy in-cluster, own everything |
| Just need API key auth for AI gateway | **LiteLLM built-in** — skip the IdP entirely |

---

## 8. Interview Q&As

**Q1: How would you implement rate limiting for an LLM API where different requests have wildly different costs?**

Per-request rate limits are meaningless for LLMs because a 10-token request and a 100K-token request consume completely different resources. I'd implement token-based rate limiting: estimate input tokens from the prompt (len/4 or tiktoken), add max_output_tokens from the request, and check against a per-key sliding window counter in Redis. Pre-request, I reserve the estimated tokens. Post-response, I reconcile with the actual usage from the model's response. I'd also layer on a concurrency limiter to prevent GPU OOM — even if you're under your token budget, 50 concurrent long-context requests will exhaust GPU memory.

**Q2: A team is complaining their AI API calls are getting 429'd but they're well under their request-per-minute limit. What's happening?**

They're likely hitting a token-per-minute limit, not an RPM limit. One large prompt can consume their entire token budget for the minute. I'd check: (1) their token usage vs limit in the rate limiter, (2) whether they're sending large context windows or documents in prompts, (3) if another key on the same team is consuming shared budget. Fix: increase their TPM, or help them optimize — use summarization, truncate context, or reduce max_tokens.

**Q3: How would you design multi-tenant isolation for a shared AI platform on Kubernetes?**

Three layers: (1) Namespace isolation — each tenant gets a namespace with ResourceQuotas for GPU/CPU/memory, LimitRanges for pod defaults, and NetworkPolicies restricting ingress to the API gateway only. (2) Data isolation — shared PostgreSQL with per-tenant schemas and Row Level Security. pgvector indexes are schema-scoped so one tenant's embeddings can't leak to another. (3) API gateway — LiteLLM or custom middleware that validates the tenant from the JWT/API key and routes to the correct namespace, enforcing per-tenant rate limits and spend caps.

**Q4: Why might you choose LiteLLM Proxy over building custom auth middleware for your vLLM deployment?**

LiteLLM gives you API key management, per-key/team TPM rate limiting, spend tracking, model routing with fallbacks, and logging to Langfuse — all from config. Building that custom takes weeks. I'd build custom only if I need: OIDC integration with specific claim structures, priority queuing across tiers (LiteLLM doesn't do priority), sub-request billing (e.g., charge per RAG retrieval + inference separately), or the proxy hop adds unacceptable latency for streaming.

**Q5: How do you handle API key rotation without downtime?**

Support overlapping validity. User creates a new key while the old one is still active. They update their services, then revoke the old key. The revoked key should return a specific error code like `key_rotated` (not generic 401) so misconfigured services get a clear signal. For automated rotation: store keys in AWS Secrets Manager, use Lambda rotation, and have services pull from Secrets Manager at startup + on a cache TTL. For K8s: External Secrets Operator syncs from Secrets Manager to K8s secrets, and pods pick up changes via volume mounts (not env vars, which require restart).
