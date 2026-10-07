"""Explicit pinned public model download, verified before the file becomes usable."""

import hashlib
import urllib.request
from pathlib import Path

from app.ml.vector_store import CLIP_SHA


def main():
    folder = Path("data/models")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "ViT-B-32.pt"
    if path.exists():
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() == CLIP_SHA:
                print("Pinned CLIP weights already verified")
                return
    temporary = path.with_suffix(".download")
    try:
        urllib.request.urlretrieve(
            f"https://openaipublic.azureedge.net/clip/models/{CLIP_SHA}/ViT-B-32.pt", temporary
        )
        with temporary.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != CLIP_SHA:
                raise ValueError("Checkpoint hash mismatch")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    print("Pinned CLIP weights downloaded and verified")


if __name__ == "__main__":
    main()
