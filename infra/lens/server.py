"""CPU-only CLIP image encoder; no network downloads or request/image logging."""

import hashlib
import io
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import torch
from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image
from torchvision.transforms import (
    CenterCrop,
    Compose,
    InterpolationMode,
    Normalize,
    Resize,
    ToTensor,
)
from vendor.model import build_model
from vendor.simple_tokenizer import SimpleTokenizer

VERSION = "embedder:clip-image-crop:v1"
SHA = "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af"
lock = threading.Lock()
torch.set_num_threads(2)
preprocess = Compose(
    [
        Resize(224, interpolation=InterpolationMode.BICUBIC),
        CenterCrop(224),
        ToTensor(),
        Normalize((0.48145466, 0.4578275, 0.40821073), (0.26862954, 0.26130258, 0.27577711)),
    ]
)


@asynccontextmanager
async def lifespan(app):
    path = Path("/models/ViT-B-32.pt")
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != SHA:
        raise RuntimeError("CLIP checkpoint hash mismatch")
    archive = torch.jit.load(str(path), map_location="cpu")
    app.state.model = build_model(archive.state_dict()).float().eval()
    tokenizer = SimpleTokenizer()
    labels = [
        "a photo of explicit nudity",
        "a photo of graphic bloody violence",
        "a photo of clothing",
        "a photo of a decorated room",
        "a photo of food",
        "a photo of a landscape",
        "a photo of artwork",
        "a photo of an object",
    ]
    tokens = torch.zeros(len(labels), 77, dtype=torch.long)
    for i, label in enumerate(labels):
        ids = (
            [tokenizer.encoder["<|startoftext|>"]]
            + tokenizer.encode(label)
            + [tokenizer.encoder["<|endoftext|>"]]
        )
        tokens[i, : len(ids)] = torch.tensor(ids)
    with torch.inference_mode():
        text = app.state.model.encode_text(tokens).float()
        app.state.safety_text = text / text.norm(dim=-1, keepdim=True)
    del archive
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "version": VERSION,
        "weights_sha256": SHA,
        "architecture": "ViT-B/32",
        "dimension": 512,
        "preprocess_version": "openai-clip:eval224:v1",
        "text_policy": "image_only:v1",
        "image_weight": 1.0,
        "library_versions": {"torch": torch.__version__, "device": "cpu"},
    }


@app.post("/encode")
def encode(image: Annotated[UploadFile, File()]):
    data = image.file.read(12 * 1024 * 1024 + 1)
    if len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "Image too large")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height > 24_000_000:
                raise ValueError("Too many pixels")
            pixels = preprocess(source.convert("RGB")).unsqueeze(0)
    except Exception as exc:
        raise HTTPException(422, "Invalid image") from exc
    with lock, torch.inference_mode():
        vector = app.state.model.encode_image(pixels).float()
        vector /= vector.norm(dim=-1, keepdim=True)
    return {"embedder_version": VERSION, "values": vector[0].tolist()}


@app.post("/classify")
def classify(image: Annotated[UploadFile, File()]):
    encoded = encode(image)
    vector = torch.tensor(encoded["values"]).unsqueeze(0)
    with torch.inference_mode():
        scores = (vector @ app.state.safety_text.T)[0]
    unsafe = float(scores[:2].max())
    safe = float(scores[2:].max())
    return {
        "version": "safety:clip-zero-shot:v1",
        "hold": unsafe >= 0.28 and unsafe - safe >= 0.03,
        "unsafe_similarity": unsafe,
        "safe_similarity": safe,
        "threshold": 0.28,
        "margin": 0.03,
    }
