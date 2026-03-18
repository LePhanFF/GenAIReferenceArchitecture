# Dev environment — GCP
# COST OPTIMIZED: ~$6/mo idle (vs AWS ~$78/mo)
#
# GCP is the recommended cloud for dev:
# - Free zonal cluster (AWS charges $73/mo)
# - Cheapest spot GPUs (L4 at $0.23/hr)
# - Cloud NAT is $1/mo (AWS NAT Gateway $32/mo)

project_id = "your-gcp-project-id" # <-- UPDATE THIS
region     = "us-central1"          # Best L4 spot availability
