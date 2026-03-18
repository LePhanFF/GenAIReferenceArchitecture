FROM python:3.12-slim AS base

WORKDIR /app

# Create model directory
RUN mkdir -p /models

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/

EXPOSE 8000

# MODEL_DIR env var for model persistence (override via K8s PVC mount)
ENV MODEL_DIR=/models

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
