"""Shared runtime settings for the legacy PDF RAG scripts."""

from __future__ import annotations

import os


EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)


def embedding_device() -> str:
    """Select an available device instead of assuming an Apple MPS host."""
    requested = os.getenv("EMBEDDING_DEVICE", "auto").lower()
    if requested != "auto":
        return requested
    try:
        import torch
    except ImportError:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def transformers_device() -> int | str:
    """Return the device format accepted by transformers.pipeline."""
    device = embedding_device()
    if device == "cuda":
        return 0
    if device == "mps":
        return "mps"
    return -1
