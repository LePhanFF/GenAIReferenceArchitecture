# Adding a New Workload

1. Create your service in services/<name>/ (app/, Dockerfile, requirements.txt)
2. Copy this template to workloads/inference/base/<name>/ (or training/)
3. Fill in deployment.yaml and service.yaml
4. Add to the parent kustomization.yaml
5. git push → ArgoCD deploys automatically

The platform is framework-agnostic. LangChain, LlamaIndex, CrewAI,
custom Python — doesn't matter. If it runs in a container, it deploys.
