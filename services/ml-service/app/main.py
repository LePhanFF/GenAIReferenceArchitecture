"""ML Service - FastAPI application.

Provides traditional ML capabilities: intent classification and
anomaly detection. Uses scikit-learn pipelines with joblib persistence.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.models import (
    classify,
    detect_anomalies,
    load_classifier,
    train_classifier,
)

logger = logging.getLogger("ml-service")
logging.basicConfig(level="INFO")


class AppState:
    classifier = None


state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load or bootstrap classifier on startup."""
    logger.info("Initializing ML service...")

    # Try to load existing model, otherwise train with defaults
    state.classifier = load_classifier()
    if state.classifier is None:
        logger.info("No saved model found, training with default data...")
        state.classifier = train_classifier()
        logger.info("Classifier trained and ready")
    else:
        logger.info("Loaded existing classifier model")

    yield
    logger.info("ML service shut down")


app = FastAPI(
    title="ML Service",
    description="Intent classification and anomaly detection",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------
class ClassifyRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Text to classify")


class ClassifyResponse(BaseModel):
    intent: str
    confidence: float
    probabilities: dict[str, float]
    latency_ms: float


class AnomalyRequest(BaseModel):
    data: list[dict] = Field(
        ...,
        min_length=1,
        description="List of metric data points (dicts with numeric values)",
    )


class AnomalyResponse(BaseModel):
    total_points: int
    anomalies_found: int
    anomaly_rate: float
    features_used: list[str]
    results: list[dict]
    latency_ms: float


class TrainRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, description="Training texts")
    labels: list[str] = Field(..., min_length=1, description="Training labels")


class TrainResponse(BaseModel):
    status: str
    samples: int
    classes: list[str]
    latency_ms: float


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/classify", response_model=ClassifyResponse)
async def classify_intent(request: ClassifyRequest):
    """Classify the intent of input text."""
    if state.classifier is None:
        raise HTTPException(status_code=503, detail="Classifier not ready")

    start = time.time()

    try:
        result = classify(state.classifier, request.text)
        latency_ms = (time.time() - start) * 1000

        return ClassifyResponse(
            intent=result["intent"],
            confidence=result["confidence"],
            probabilities=result["probabilities"],
            latency_ms=round(latency_ms, 2),
        )
    except Exception as e:
        logger.error(f"Classification failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Classification failed: {str(e)}")


@app.post("/anomaly", response_model=AnomalyResponse)
async def detect_anomaly(request: AnomalyRequest):
    """Detect anomalies in metrics data."""
    start = time.time()

    try:
        result = detect_anomalies(request.data)
        latency_ms = (time.time() - start) * 1000

        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])

        return AnomalyResponse(
            total_points=result["total_points"],
            anomalies_found=result["anomalies_found"],
            anomaly_rate=result["anomaly_rate"],
            features_used=result["features_used"],
            results=result["results"],
            latency_ms=round(latency_ms, 2),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Anomaly detection failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Anomaly detection failed: {str(e)}")


@app.post("/train", response_model=TrainResponse)
async def retrain(request: TrainRequest):
    """Retrain the classifier with new labeled data."""
    if len(request.texts) != len(request.labels):
        raise HTTPException(
            status_code=400,
            detail=f"Mismatch: {len(request.texts)} texts vs {len(request.labels)} labels",
        )

    start = time.time()

    try:
        state.classifier = train_classifier(request.texts, request.labels)
        latency_ms = (time.time() - start) * 1000

        return TrainResponse(
            status="retrained",
            samples=len(request.texts),
            classes=list(state.classifier.classes_),
            latency_ms=round(latency_ms, 2),
        )
    except Exception as e:
        logger.error(f"Retraining failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Retraining failed: {str(e)}")


@app.get("/health")
async def health():
    """Health check for K8s probes."""
    return {
        "service": "ml-service",
        "status": "healthy" if state.classifier is not None else "loading",
        "classifier_ready": state.classifier is not None,
        "classes": list(state.classifier.classes_) if state.classifier else [],
    }
