import hashlib
import io
from dataclasses import dataclass
from math import ceil, floor

from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from app.config import Settings
from app.media import validate_image


class CropBox(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    left: FiniteFloat = Field(default=0, ge=0, le=1)
    top: FiniteFloat = Field(default=0, ge=0, le=1)
    right: FiniteFloat = Field(default=1, ge=0, le=1)
    bottom: FiniteFloat = Field(default=1, ge=0, le=1)

    @model_validator(mode="after")
    def ordered_coordinates(self):
        if self.left >= self.right or self.top >= self.bottom:
            raise ValueError("Choose a crop with positive width and height")
        return self


@dataclass(frozen=True)
class PreparedCrop:
    # The actual RGB PNG is transient; no user image is stored or logged by Lens preparation.
    image_bytes: bytes
    source_sha256: str
    crop_sha256: str
    oriented_size: tuple[int, int]
    pixel_box: tuple[int, int, int, int]
    policy_version: str = "lens-crop:oriented-rgb-png:v1"


def prepare_crop(data: bytes, box: CropBox, settings: Settings) -> PreparedCrop:
    validate_image(data, settings)
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        pixels = (
            floor(box.left * image.width),
            floor(box.top * image.height),
            ceil(box.right * image.width),
            ceil(box.bottom * image.height),
        )
        rgba = image.crop(pixels)
        rgb = Image.new("RGB", rgba.size, "white")
        rgb.paste(rgba, mask=rgba.getchannel("A"))
        output = io.BytesIO()
        rgb.save(output, format="PNG")
        image_bytes = output.getvalue()
        return PreparedCrop(
            image_bytes=image_bytes,
            source_sha256=hashlib.sha256(data).hexdigest(),
            crop_sha256=hashlib.sha256(image_bytes).hexdigest(),
            oriented_size=image.size,
            pixel_box=pixels,
        )
