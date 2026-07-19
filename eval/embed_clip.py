"""CLIP ViT-B/32 image embedder that produces the SAME 512-d vector as the
production web app (which uses Xenova/clip-vit-base-patch32 in the browser).

The Xenova model IS OpenAI's clip-vit-base-patch32 exported to ONNX; using
the openai/ hub id here gives identical output modulo quantization (production
uses q8; we use fp32 for eval accuracy).
"""
from __future__ import annotations

# Disable TF import chain in transformers so startup is fast.
import os
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")

import io
from functools import lru_cache

import numpy as np
import torch
from PIL import Image
from transformers import CLIPImageProcessor, CLIPVisionModelWithProjection

MODEL_ID = "openai/clip-vit-base-patch32"


@lru_cache(maxsize=1)
def _load():
    proc = CLIPImageProcessor.from_pretrained(MODEL_ID)
    model = CLIPVisionModelWithProjection.from_pretrained(MODEL_ID).eval()
    return proc, model


def embed_bytes(image_bytes: bytes) -> np.ndarray | None:
    """Return a unit-length 512-d numpy vector, or None on decode failure."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    proc, model = _load()
    inputs = proc(images=img, return_tensors="pt")
    with torch.no_grad():
        out = model(**inputs).image_embeds[0].cpu().numpy()
    n = np.linalg.norm(out)
    if n < 1e-8:
        return None
    return (out / n).astype(np.float32)


def embed_batch(image_bytes_list: list[bytes]) -> list[np.ndarray | None]:
    """Batched embedding for speed."""
    proc, model = _load()
    imgs, ok_idx = [], []
    for i, b in enumerate(image_bytes_list):
        try:
            imgs.append(Image.open(io.BytesIO(b)).convert("RGB"))
            ok_idx.append(i)
        except Exception:
            pass
    if not imgs:
        return [None] * len(image_bytes_list)
    inputs = proc(images=imgs, return_tensors="pt")
    with torch.no_grad():
        out = model(**inputs).image_embeds.cpu().numpy()
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    out = out / np.maximum(norms, 1e-8)
    result: list[np.ndarray | None] = [None] * len(image_bytes_list)
    for j, i in enumerate(ok_idx):
        result[i] = out[j].astype(np.float32)
    return result
