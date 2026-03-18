#!/usr/bin/env bash
#
# KinD (Kubernetes in Docker) Setup — CPU-Only
# =============================================
# For development on machines WITHOUT an NVIDIA GPU.
# Uses CPU-only inference (slower but functional).
#
# Usage:
#   chmod +x setup.sh
#   ./setup.sh
#
# Prerequisites:
#   - Docker installed and running
#   - kubectl installed
#

set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-genai-dev}"
NAMESPACE="genai"
REPO_URL="${REPO_URL:-https://github.com/lehph/GenAIReferenceArchitecture.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"

echo "============================================="
echo "  KinD Setup — CPU-Only GenAI Stack"
echo "============================================="
echo ""

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------

echo "[1/5] Pre-flight checks..."

if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker not found. Install Docker first."
    exit 1
fi

if ! docker info &>/dev/null; then
    echo "ERROR: Docker is not running."
    exit 1
fi

# Install KinD if not present
if ! command -v kind &>/dev/null; then
    echo "  Installing KinD..."
    if [[ "$(uname -s)" == "Darwin" ]]; then
        brew install kind
    else
        curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.23.0/kind-linux-amd64
        chmod +x ./kind
        sudo mv ./kind /usr/local/bin/kind
    fi
fi

# Install kubectl if not present
if ! command -v kubectl &>/dev/null; then
    echo "  Installing kubectl..."
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    chmod +x kubectl
    sudo mv kubectl /usr/local/bin/kubectl
fi

echo "  Pre-flight checks passed."
echo ""

# -------------------------------------------------------------------
# Create KinD cluster
# -------------------------------------------------------------------

echo "[2/5] Creating KinD cluster '${CLUSTER_NAME}'..."

if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
    echo "  Cluster '${CLUSTER_NAME}' already exists, skipping."
else
    cat <<EOF | kind create cluster --name "${CLUSTER_NAME}" --config=-
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
  - role: control-plane
    extraPortMappings:
      - containerPort: 30000
        hostPort: 8000
        protocol: TCP
      - containerPort: 30001
        hostPort: 8001
        protocol: TCP
      - containerPort: 30002
        hostPort: 8002
        protocol: TCP
      - containerPort: 30003
        hostPort: 8003
        protocol: TCP
      - containerPort: 30080
        hostPort: 8080
        protocol: TCP
EOF
fi

kubectl cluster-info --context "kind-${CLUSTER_NAME}"
echo ""

# -------------------------------------------------------------------
# Install Helm
# -------------------------------------------------------------------

if ! command -v helm &>/dev/null; then
    echo "  Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# -------------------------------------------------------------------
# Install ArgoCD
# -------------------------------------------------------------------

echo "[3/5] Installing ArgoCD..."

kubectl create namespace argocd 2>/dev/null || true
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

echo "  Waiting for ArgoCD..."
kubectl wait --for=condition=Available deployment/argocd-server \
    -n argocd --timeout=300s

ARGOCD_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret \
    -o jsonpath="{.data.password}" | base64 -d 2>/dev/null || echo "not-ready")

echo "  ArgoCD installed."
echo ""

# -------------------------------------------------------------------
# Install KEDA
# -------------------------------------------------------------------

echo "[4/5] Installing KEDA..."

helm repo add kedacore https://kedacore.github.io/charts 2>/dev/null || true
helm repo update

helm upgrade --install keda kedacore/keda \
    --namespace keda --create-namespace \
    --wait --timeout 5m

echo "  KEDA installed."
echo ""

# -------------------------------------------------------------------
# Create namespace and ArgoCD Application
# -------------------------------------------------------------------

echo "[5/5] Configuring ArgoCD..."

kubectl create namespace "${NAMESPACE}" 2>/dev/null || true

cat <<EOF | kubectl apply -f -
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: genai-stack
  namespace: argocd
spec:
  project: default
  source:
    repoURL: ${REPO_URL}
    targetRevision: ${REPO_BRANCH}
    path: k8s/base
  destination:
    server: https://kubernetes.default.svc
    namespace: ${NAMESPACE}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
EOF

echo ""

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------

echo "============================================="
echo "  KinD Setup Complete!"
echo "============================================="
echo ""
echo "  Cluster: ${CLUSTER_NAME}"
echo "  ArgoCD:  kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo "  Login:   admin / ${ARGOCD_PASSWORD}"
echo ""
echo "  NOTE: This is a CPU-only setup. Inference will be slower."
echo "  For GPU support, use the DGX Spark setup instead."
echo ""
echo "  Next steps:"
echo "    kubectl get pods -n ${NAMESPACE}"
echo "    kubectl port-forward svc/rag-service -n ${NAMESPACE} 8000:8000"
echo ""
