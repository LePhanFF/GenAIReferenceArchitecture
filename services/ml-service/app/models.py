"""Scikit-learn model definitions for classification and anomaly detection.

Provides:
    - Intent classification pipeline (TF-IDF + RandomForest)
    - Anomaly detection (IsolationForest on time-series metrics)
    - Training and inference functions
    - Model persistence via joblib
"""

import logging
import os
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline

logger = logging.getLogger(__name__)

MODEL_DIR = Path(os.environ.get("MODEL_DIR", "/models"))


# ---------------------------------------------------------------------------
# Intent Classification
# ---------------------------------------------------------------------------
def create_classifier_pipeline() -> Pipeline:
    """Create a TF-IDF + RandomForest classification pipeline."""
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            max_features=10000,
            ngram_range=(1, 2),
            stop_words="english",
        )),
        ("clf", RandomForestClassifier(
            n_estimators=100,
            max_depth=20,
            random_state=42,
            n_jobs=-1,
        )),
    ])


def get_default_training_data() -> tuple[list[str], list[str]]:
    """Return default training data for bootstrapping.

    In production, this would come from a labeled dataset on S3/GCS.
    """
    texts = [
        # Question / knowledge lookup
        "What is the deployment process?",
        "How do I configure the model?",
        "What are the system requirements?",
        "Tell me about the API endpoints",
        "Where can I find documentation?",
        "Explain the architecture",
        "What models are supported?",
        "How does RAG work?",
        # Metrics / analytics
        "Show me the latency trends",
        "What's the GPU utilization?",
        "How much are we spending on inference?",
        "Show me error rates for last hour",
        "What's the p99 latency?",
        "Compare throughput across models",
        "Show cost breakdown by service",
        # Action / command
        "Deploy the new model version",
        "Scale up the inference pods",
        "Restart the embedding service",
        "Run a benchmark test",
        "Trigger model retraining",
        "Update the configuration",
        "Roll back to previous version",
        # Troubleshooting
        "The service is returning 500 errors",
        "Latency has spiked in the last 10 minutes",
        "OOM errors on GPU nodes",
        "Pods keep crashing",
        "Model responses are degraded",
        "Connection timeouts to the database",
        "Embedding service is slow",
    ]
    labels = [
        "question", "question", "question", "question",
        "question", "question", "question", "question",
        "metrics", "metrics", "metrics", "metrics",
        "metrics", "metrics", "metrics",
        "action", "action", "action", "action",
        "action", "action", "action",
        "troubleshooting", "troubleshooting", "troubleshooting",
        "troubleshooting", "troubleshooting", "troubleshooting",
        "troubleshooting",
    ]
    return texts, labels


def train_classifier(
    texts: Optional[list[str]] = None,
    labels: Optional[list[str]] = None,
) -> Pipeline:
    """Train the intent classifier.

    Args:
        texts: Training texts. If None, uses default data.
        labels: Training labels. If None, uses default data.

    Returns:
        Trained pipeline.
    """
    if texts is None or labels is None:
        texts, labels = get_default_training_data()

    pipeline = create_classifier_pipeline()
    pipeline.fit(texts, labels)

    # Save model
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODEL_DIR / "intent_classifier.joblib"
    joblib.dump(pipeline, model_path)
    logger.info(f"Classifier saved to {model_path}")

    return pipeline


def load_classifier() -> Optional[Pipeline]:
    """Load a trained classifier from disk."""
    model_path = MODEL_DIR / "intent_classifier.joblib"
    if model_path.exists():
        return joblib.load(model_path)
    return None


def classify(pipeline: Pipeline, text: str) -> dict:
    """Run intent classification.

    Returns:
        Dict with intent, confidence, and all class probabilities.
    """
    prediction = pipeline.predict([text])[0]
    probabilities = pipeline.predict_proba([text])[0]
    classes = pipeline.classes_

    confidence = float(max(probabilities))
    all_probs = {cls: round(float(prob), 4) for cls, prob in zip(classes, probabilities)}

    return {
        "intent": prediction,
        "confidence": confidence,
        "probabilities": all_probs,
    }


# ---------------------------------------------------------------------------
# Anomaly Detection
# ---------------------------------------------------------------------------
def create_anomaly_detector() -> IsolationForest:
    """Create an IsolationForest for metrics anomaly detection."""
    return IsolationForest(
        n_estimators=100,
        contamination=0.1,
        random_state=42,
    )


def detect_anomalies(data: list[dict]) -> dict:
    """Run anomaly detection on metrics data.

    Args:
        data: List of dicts with numeric metric values.
              Example: [{"latency_ms": 50, "error_rate": 0.01}, ...]

    Returns:
        Dict with anomaly flags and scores per data point.
    """
    df = pd.DataFrame(data)
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    if not numeric_cols:
        return {"error": "No numeric columns found in data"}

    detector = create_anomaly_detector()
    features = df[numeric_cols].fillna(0)

    predictions = detector.fit_predict(features)
    scores = detector.score_samples(features)

    results = []
    for i, (pred, score) in enumerate(zip(predictions, scores)):
        results.append({
            "index": i,
            "is_anomaly": bool(pred == -1),
            "anomaly_score": round(float(score), 4),
        })

    anomaly_count = sum(1 for r in results if r["is_anomaly"])

    return {
        "total_points": len(results),
        "anomalies_found": anomaly_count,
        "anomaly_rate": round(anomaly_count / len(results), 4) if results else 0,
        "features_used": numeric_cols,
        "results": results,
    }
