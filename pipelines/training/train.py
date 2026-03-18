"""
Fine-Tuning Pipeline — Unsloth + LoRA on Qwen2.5-1.5B
======================================================
Runs as a K8s Job with GPU or locally on DGX Spark.

Usage:
    # Local
    python train.py --dataset ./data/train.jsonl --output ./output

    # S3
    python train.py --dataset s3://bucket/train.jsonl --output s3://bucket/adapters/

    # K8s Job: configured via environment variables
    DATASET_PATH=s3://bucket/train.jsonl OUTPUT_PATH=s3://bucket/adapters/ python train.py

Environment Variables:
    DATASET_PATH        - Path to training dataset (local or S3 URI)
    OUTPUT_PATH         - Where to save the LoRA adapter (local or S3 URI)
    MODEL_NAME          - Base model (default: Qwen/Qwen2.5-1.5B-Instruct)
    LORA_RANK           - LoRA rank (default: 16)
    LORA_ALPHA          - LoRA alpha (default: 32)
    LORA_DROPOUT        - LoRA dropout (default: 0.05)
    LEARNING_RATE       - Learning rate (default: 2e-4)
    NUM_EPOCHS          - Number of training epochs (default: 3)
    BATCH_SIZE          - Per-device batch size (default: 4)
    GRAD_ACCUM_STEPS    - Gradient accumulation steps (default: 4)
    MAX_SEQ_LENGTH      - Maximum sequence length (default: 2048)
    WANDB_PROJECT       - Weights & Biases project (optional)
"""

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

import boto3
import torch
from datasets import Dataset, load_dataset
from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Config:
    DATASET_PATH: str = os.getenv("DATASET_PATH", "./data/train.jsonl")
    OUTPUT_PATH: str = os.getenv("OUTPUT_PATH", "./output")
    MODEL_NAME: str = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-1.5B-Instruct")
    LORA_RANK: int = int(os.getenv("LORA_RANK", "16"))
    LORA_ALPHA: int = int(os.getenv("LORA_ALPHA", "32"))
    LORA_DROPOUT: float = float(os.getenv("LORA_DROPOUT", "0.05"))
    LEARNING_RATE: float = float(os.getenv("LEARNING_RATE", "2e-4"))
    NUM_EPOCHS: int = int(os.getenv("NUM_EPOCHS", "3"))
    BATCH_SIZE: int = int(os.getenv("BATCH_SIZE", "4"))
    GRAD_ACCUM_STEPS: int = int(os.getenv("GRAD_ACCUM_STEPS", "4"))
    MAX_SEQ_LENGTH: int = int(os.getenv("MAX_SEQ_LENGTH", "2048"))
    WANDB_PROJECT: str = os.getenv("WANDB_PROJECT", "")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_data(path: str) -> Dataset:
    """Load dataset from local file or S3."""
    if path.startswith("s3://"):
        logger.info("Downloading dataset from S3: %s", path)
        parts = path.replace("s3://", "").split("/", 1)
        bucket, key = parts[0], parts[1]
        s3 = boto3.client("s3")
        local_path = Path(tempfile.mkdtemp()) / Path(key).name
        s3.download_file(bucket, key, str(local_path))
        path = str(local_path)

    logger.info("Loading dataset from: %s", path)

    if path.endswith(".jsonl") or path.endswith(".json"):
        dataset = load_dataset("json", data_files=path, split="train")
    elif path.endswith(".csv"):
        dataset = load_dataset("csv", data_files=path, split="train")
    elif path.endswith(".parquet"):
        dataset = load_dataset("parquet", data_files=path, split="train")
    else:
        raise ValueError(f"Unsupported dataset format: {path}")

    logger.info("Dataset loaded: %d examples", len(dataset))
    return dataset


def format_instruction(example: dict) -> str:
    """Format a single example into the chat template.

    Expected fields: instruction, input (optional), output
    """
    parts = []
    parts.append(f"### Instruction:\n{example['instruction']}")
    if example.get("input"):
        parts.append(f"### Input:\n{example['input']}")
    parts.append(f"### Response:\n{example['output']}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Model setup
# ---------------------------------------------------------------------------

def setup_model(cfg: Config):
    """Load base model with Unsloth and apply LoRA."""
    logger.info("Loading model: %s", cfg.MODEL_NAME)

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg.MODEL_NAME,
        max_seq_length=cfg.MAX_SEQ_LENGTH,
        dtype=None,  # auto-detect
        load_in_4bit=True,
    )

    logger.info("Applying LoRA: rank=%d, alpha=%d, dropout=%.3f",
                cfg.LORA_RANK, cfg.LORA_ALPHA, cfg.LORA_DROPOUT)

    model = FastLanguageModel.get_peft_model(
        model,
        r=cfg.LORA_RANK,
        lora_alpha=cfg.LORA_ALPHA,
        lora_dropout=cfg.LORA_DROPOUT,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    return model, tokenizer


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(model, tokenizer, dataset: Dataset, cfg: Config) -> str:
    """Run SFT training and return the output path."""
    output_dir = cfg.OUTPUT_PATH
    is_s3 = output_dir.startswith("s3://")
    local_output = tempfile.mkdtemp() if is_s3 else output_dir

    training_args = TrainingArguments(
        output_dir=local_output,
        per_device_train_batch_size=cfg.BATCH_SIZE,
        gradient_accumulation_steps=cfg.GRAD_ACCUM_STEPS,
        num_train_epochs=cfg.NUM_EPOCHS,
        learning_rate=cfg.LEARNING_RATE,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        logging_steps=10,
        save_strategy="epoch",
        warmup_ratio=0.03,
        lr_scheduler_type="cosine",
        optim="adamw_8bit",
        seed=42,
        report_to="wandb" if cfg.WANDB_PROJECT else "none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        formatting_func=format_instruction,
        max_seq_length=cfg.MAX_SEQ_LENGTH,
        args=training_args,
    )

    logger.info("Starting training...")
    trainer.train()

    # Save the LoRA adapter
    adapter_path = os.path.join(local_output, "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    logger.info("Adapter saved to: %s", adapter_path)

    # Upload to S3 if needed
    if is_s3:
        upload_to_s3(adapter_path, output_dir)

    return adapter_path


def upload_to_s3(local_dir: str, s3_uri: str) -> None:
    """Upload a directory to S3."""
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""

    s3 = boto3.client("s3")
    for root, _, files in os.walk(local_dir):
        for fname in files:
            local_path = os.path.join(root, fname)
            rel = os.path.relpath(local_path, local_dir)
            key = f"{prefix}/{rel}" if prefix else rel
            logger.info("Uploading %s -> s3://%s/%s", local_path, bucket, key)
            s3.upload_file(local_path, bucket, key)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Fine-tuning pipeline (Unsloth + LoRA)")
    parser.add_argument("--dataset", default=None, help="Path to training dataset")
    parser.add_argument("--output", default=None, help="Output path for adapter")
    parser.add_argument("--model", default=None, help="Base model name")
    parser.add_argument("--epochs", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--lr", type=float, default=None)
    args = parser.parse_args()

    cfg = Config()
    if args.dataset:
        cfg.DATASET_PATH = args.dataset
    if args.output:
        cfg.OUTPUT_PATH = args.output
    if args.model:
        cfg.MODEL_NAME = args.model
    if args.epochs:
        cfg.NUM_EPOCHS = args.epochs
    if args.batch_size:
        cfg.BATCH_SIZE = args.batch_size
    if args.lr:
        cfg.LEARNING_RATE = args.lr

    # Load data
    dataset = load_data(cfg.DATASET_PATH)

    # Setup model
    model, tokenizer = setup_model(cfg)

    # Train
    adapter_path = train(model, tokenizer, dataset, cfg)

    logger.info("Training complete. Adapter at: %s", adapter_path)

    # Print summary
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    logger.info("Trainable parameters: %d / %d (%.2f%%)", trainable, total, 100 * trainable / total)


if __name__ == "__main__":
    main()
