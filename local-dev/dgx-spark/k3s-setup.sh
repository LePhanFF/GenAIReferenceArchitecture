#!/usr/bin/env bash
#
# DGX Spark — K3s + GPU Operator + ArgoCD + KEDA Setup
# =====================================================
# Installs a complete local Kubernetes environment on NVIDIA DGX Spark
# for running the GenAI Reference Architecture.
#
# Usage:
#   chmod +x k3s-setup.sh
#   ./k3s-setup.sh
#
# Prerequisites:
#   - NVIDIA drivers installed (nvidia-smi works)
#   - NVIDIA Container Toolkit installed
#   - Internet access (for pulling images)
#

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/lehph/GenAIReferenceArchitecture.git}"
REPO_BRANCH="${REPO_BRANCH:-main}"
K3S_VERSION="${K3S_VERSION:-v1.30.2+k3s1}"
NAMESPACE="genai"

echo "============================================="
echo "  DGX Spark — K3s Setup"
echo "============================================="
echo ""

# -------------------------------------------------------------------
# Pre-flight checks
# -------------------------------------------------------------------

echo "[1/7] Pre-flight checks..."

if ! command -v nvidia-smi &>/dev/null; then
    echo "ERROR: nvidia-smi not found. Install NVIDIA drivers first."
    exit 1
fi

echo "  GPU detected:"
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | sed 's/^/    /'

if ! command -v nvidia-ctk &>/dev/null; then
    echo "WARNING: nvidia-ctk not found. Installing NVIDIA Container Toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
        sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit
fi

echo "  Pre-flight checks passed."
echo ""

# -------------------------------------------------------------------
# Install K3s
# -------------------------------------------------------------------

echo "[2/7] Installing K3s ${K3S_VERSION}..."

if command -v k3s &>/dev/null; then
    echo "  K3s already installed, skipping."
else
    curl -sfL https://get.k3s.io | \
        INSTALL_K3S_VERSION="${K3S_VERSION}" \
        INSTALL_K3S_EXEC="--disable traefik" \
        sh -

    # Wait for K3s to be ready
    echo "  Waiting for K3s to start..."
    sleep 10
    until sudo k3s kubectl get nodes &>/dev/null; do
        sleep 5
    done
fi

# Set up kubeconfig for the current user
mkdir -p "$HOME/.kube"
sudo cp /etc/rancher/k3s/k3s.yaml "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
export KUBECONFIG="$HOME/.kube/config"

echo "  K3s installed. Node status:"
kubectl get nodes | sed 's/^/    /'
echo ""

# -------------------------------------------------------------------
# Configure NVIDIA runtime for K3s
# -------------------------------------------------------------------

echo "[3/7] Configuring NVIDIA container runtime for K3s..."

# Configure containerd to use nvidia runtime
sudo nvidia-ctk runtime configure --runtime=containerd --config=/var/lib/rancher/k3s/agent/etc/containerd/config.toml.tmpl
sudo systemctl restart k3s

sleep 10
echo "  NVIDIA runtime configured."
echo ""

# -------------------------------------------------------------------
# Install Helm (if not present)
# -------------------------------------------------------------------

if ! command -v helm &>/dev/null; then
    echo "  Installing Helm..."
    curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

# -------------------------------------------------------------------
# Install NVIDIA GPU Operator
# -------------------------------------------------------------------

echo "[4/7] Installing NVIDIA GPU Operator..."

helm repo add nvidia https://helm.ngc.nvidia.com/nvidia 2>/dev/null || true
helm repo update

# driver.enabled=false because DGX Spark already has drivers
helm upgrade --install gpu-operator nvidia/gpu-operator \
    --namespace gpu-operator --create-namespace \
    --set driver.enabled=false \
    --set toolkit.enabled=false \
    --wait --timeout 5m

echo "  GPU Operator installed."
echo ""

# -------------------------------------------------------------------
# Install ArgoCD
# -------------------------------------------------------------------

echo "[5/7] Installing ArgoCD..."

kubectl create namespace argocd 2>/dev/null || true
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

echo "  Waiting for ArgoCD to be ready..."
kubectl wait --for=condition=Available deployment/argocd-server \
    -n argocd --timeout=300s

ARGOCD_PASSWORD=$(kubectl -n argocd get secret argocd-initial-admin-secret \
    -o jsonpath="{.data.password}" | base64 -d)

echo "  ArgoCD installed."
echo "  UI: kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo "  Username: admin"
echo "  Password: ${ARGOCD_PASSWORD}"
echo ""

# -------------------------------------------------------------------
# Install KEDA
# -------------------------------------------------------------------

echo "[6/7] Installing KEDA..."

helm repo add kedacore https://kedacore.github.io/charts 2>/dev/null || true
helm repo update

helm upgrade --install keda kedacore/keda \
    --namespace keda --create-namespace \
    --wait --timeout 5m

echo "  KEDA installed."
echo ""

# -------------------------------------------------------------------
# Configure ArgoCD Application
# -------------------------------------------------------------------

echo "[7/7] Configuring ArgoCD to sync from repo..."

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

echo "  ArgoCD Application created. It will sync from:"
echo "    Repo: ${REPO_URL}"
echo "    Branch: ${REPO_BRANCH}"
echo "    Path: k8s/base"
echo ""

# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------

echo "============================================="
echo "  Setup Complete!"
echo "============================================="
echo ""
echo "  K3s:          $(k3s --version 2>/dev/null | head -1)"
echo "  GPU Operator: installed (driver=host)"
echo "  ArgoCD:       installed (port 8080)"
echo "  KEDA:         installed"
echo ""
echo "  Next steps:"
echo "    1. kubectl get pods -A              # Verify all pods are running"
echo "    2. kubectl get pods -n ${NAMESPACE}     # Check GenAI stack"
echo "    3. kubectl port-forward svc/argocd-server -n argocd 8080:443"
echo "    4. Open https://localhost:8080 (admin / ${ARGOCD_PASSWORD})"
echo ""
echo "  To run services without K8s, use Docker Compose instead:"
echo "    cd local-dev/dgx-spark && docker compose up -d"
echo ""
