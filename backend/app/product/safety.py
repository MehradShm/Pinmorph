"""Exact oriented-pixel duplicates and an explicit, replaceable zero-shot safety gate."""

import hashlib
import io

import httpx
from PIL import Image, ImageOps

from app.config import Settings

SAFETY_VERSION = "safety:clip-zero-shot:v1"


def pixel_hash(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        rgb = Image.new("RGB", image.size, "white")
        rgb.paste(image, mask=image.getchannel("A"))
        return hashlib.sha256(f"{rgb.width}x{rgb.height}:".encode() + rgb.tobytes()).hexdigest()


def classify(data: bytes, settings: Settings) -> dict:
    with httpx.Client(timeout=90, trust_env=False) as client:
        response = client.post(
            settings.lens_endpoint + "/classify", files={"image": ("image.png", data, "image/png")}
        )
        response.raise_for_status()
        result = response.json()
    if result.get("version") != SAFETY_VERSION or type(result.get("hold")) is not bool:
        raise ValueError("Safety classifier version mismatch")
    return result
