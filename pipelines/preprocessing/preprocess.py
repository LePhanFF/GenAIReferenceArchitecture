"""
Data Preprocessing Pipeline
============================
Cleans, deduplicates, and transforms raw data into training-ready datasets.

Usage:
    # Local
    python preprocess.py --input ./raw/data.csv --output ./processed/train.jsonl --format jsonl

    # S3
    python preprocess.py --input s3://bucket/raw/data.csv --output s3://bucket/processed/train.jsonl

    # K8s Job: configured via environment variables
    INPUT_PATH=./raw/data.csv OUTPUT_PATH=./processed/train.jsonl python preprocess.py

Environment Variables:
    INPUT_PATH   - Path to raw data (CSV, JSON, Parquet — local or S3)
    OUTPUT_PATH  - Path for processed output (local or S3)
    OUTPUT_FORMAT - Output format: jsonl, csv, parquet (default: jsonl)
    DEDUP_COLUMNS - Comma-separated columns for deduplication (default: all)
    MIN_TEXT_LENGTH - Minimum text length to keep (default: 10)
    SAMPLE_FRACTION - Random sample fraction 0-1 (default: 1.0, keep all)
"""

import argparse
import hashlib
import logging
import os
import re
import sys
import tempfile
from pathlib import Path

import boto3
import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Config:
    INPUT_PATH: str = os.getenv("INPUT_PATH", "./raw/data.csv")
    OUTPUT_PATH: str = os.getenv("OUTPUT_PATH", "./processed/train.jsonl")
    OUTPUT_FORMAT: str = os.getenv("OUTPUT_FORMAT", "jsonl")
    DEDUP_COLUMNS: str = os.getenv("DEDUP_COLUMNS", "")  # empty = all columns
    MIN_TEXT_LENGTH: int = int(os.getenv("MIN_TEXT_LENGTH", "10"))
    SAMPLE_FRACTION: float = float(os.getenv("SAMPLE_FRACTION", "1.0"))


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def download_from_s3(s3_uri: str) -> str:
    """Download file from S3, return local path."""
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    s3 = boto3.client("s3")
    local_path = os.path.join(tempfile.mkdtemp(), Path(key).name)
    logger.info("Downloading s3://%s/%s -> %s", bucket, key, local_path)
    s3.download_file(bucket, key, local_path)
    return local_path


def upload_to_s3(local_path: str, s3_uri: str) -> None:
    """Upload file to S3."""
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket, key = parts[0], parts[1]
    s3 = boto3.client("s3")
    logger.info("Uploading %s -> s3://%s/%s", local_path, bucket, key)
    s3.upload_file(local_path, bucket, key)


def load_dataframe(path: str) -> pd.DataFrame:
    """Load a file into a DataFrame."""
    if path.startswith("s3://"):
        path = download_from_s3(path)

    ext = Path(path).suffix.lower()
    if ext == ".csv":
        return pd.read_csv(path)
    elif ext == ".json":
        return pd.read_json(path)
    elif ext == ".jsonl":
        return pd.read_json(path, lines=True)
    elif ext == ".parquet":
        return pd.read_parquet(path)
    else:
        raise ValueError(f"Unsupported input format: {ext}")


def save_dataframe(df: pd.DataFrame, path: str, fmt: str) -> None:
    """Save DataFrame to file, upload to S3 if needed."""
    is_s3 = path.startswith("s3://")
    local_path = os.path.join(tempfile.mkdtemp(), f"output.{fmt}") if is_s3 else path

    Path(local_path).parent.mkdir(parents=True, exist_ok=True)

    if fmt == "jsonl":
        df.to_json(local_path, orient="records", lines=True, force_ascii=False)
    elif fmt == "csv":
        df.to_csv(local_path, index=False)
    elif fmt == "parquet":
        df.to_parquet(local_path, index=False)
    else:
        raise ValueError(f"Unsupported output format: {fmt}")

    logger.info("Saved %d rows to %s", len(df), local_path)

    if is_s3:
        upload_to_s3(local_path, path)


# ---------------------------------------------------------------------------
# Preprocessing steps
# ---------------------------------------------------------------------------

def clean_text(text: str) -> str:
    """Basic text cleaning."""
    if not isinstance(text, str):
        return ""
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    # Remove null bytes
    text = text.replace("\x00", "")
    return text


def preprocess(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Run all preprocessing steps."""
    initial_count = len(df)
    logger.info("Starting preprocessing: %d rows", initial_count)

    # 1. Drop completely empty rows
    df = df.dropna(how="all")
    logger.info("After drop-all-null: %d rows (removed %d)", len(df), initial_count - len(df))

    # 2. Clean text columns
    text_cols = df.select_dtypes(include=["object"]).columns
    for col in text_cols:
        df[col] = df[col].apply(clean_text)
    logger.info("Cleaned %d text columns", len(text_cols))

    # 3. Filter short text
    if text_cols.any():
        primary_text_col = text_cols[0]
        before = len(df)
        df = df[df[primary_text_col].str.len() >= cfg.MIN_TEXT_LENGTH]
        logger.info("After min-length filter (%d chars on '%s'): %d rows (removed %d)",
                     cfg.MIN_TEXT_LENGTH, primary_text_col, len(df), before - len(df))

    # 4. Deduplicate
    dedup_cols = cfg.DEDUP_COLUMNS.split(",") if cfg.DEDUP_COLUMNS else None
    if dedup_cols:
        dedup_cols = [c.strip() for c in dedup_cols if c.strip() in df.columns]
    before = len(df)
    df = df.drop_duplicates(subset=dedup_cols or None)
    logger.info("After deduplication: %d rows (removed %d duplicates)", len(df), before - len(df))

    # 5. Sample if requested
    if 0 < cfg.SAMPLE_FRACTION < 1.0:
        df = df.sample(frac=cfg.SAMPLE_FRACTION, random_state=42)
        logger.info("Sampled %.0f%%: %d rows", cfg.SAMPLE_FRACTION * 100, len(df))

    # 6. Reset index
    df = df.reset_index(drop=True)

    logger.info("Preprocessing complete: %d -> %d rows", initial_count, len(df))
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Data Preprocessing Pipeline")
    parser.add_argument("--input", default=None, help="Input data path")
    parser.add_argument("--output", default=None, help="Output data path")
    parser.add_argument("--format", default=None, choices=["jsonl", "csv", "parquet"])
    parser.add_argument("--dedup-columns", default=None)
    parser.add_argument("--min-length", type=int, default=None)
    parser.add_argument("--sample", type=float, default=None)
    args = parser.parse_args()

    cfg = Config()
    if args.input:
        cfg.INPUT_PATH = args.input
    if args.output:
        cfg.OUTPUT_PATH = args.output
    if args.format:
        cfg.OUTPUT_FORMAT = args.format
    if args.dedup_columns:
        cfg.DEDUP_COLUMNS = args.dedup_columns
    if args.min_length is not None:
        cfg.MIN_TEXT_LENGTH = args.min_length
    if args.sample is not None:
        cfg.SAMPLE_FRACTION = args.sample

    # Load
    df = load_dataframe(cfg.INPUT_PATH)

    # Process
    df = preprocess(df, cfg)

    if df.empty:
        logger.warning("No data after preprocessing. Exiting.")
        sys.exit(0)

    # Save
    save_dataframe(df, cfg.OUTPUT_PATH, cfg.OUTPUT_FORMAT)
    logger.info("Pipeline finished. Output: %s", cfg.OUTPUT_PATH)


if __name__ == "__main__":
    main()
