import base64
import io

import pytest
from PIL import Image

from app.config import Settings
from app.media import InvalidImage, build_variants, validate_image


def image_bytes(size=(1800, 900), mode="RGB", color="#507c44", exif=None):
    output = io.BytesIO()
    Image.new(mode, size, color).save(output, "PNG", **({"exif": exif} if exif else {}))
    return output.getvalue()


def test_resize_preserves_aspect_and_strips_metadata():
    exif = Image.Exif()
    exif[274] = 6  # Rotate 90 degrees; width/height must follow the displayed orientation.
    exif[270] = "private metadata"
    variants, width, height, color = build_variants(
        image_bytes(exif=exif), Settings(_env_file=None)
    )
    assert (width, height) == (900, 1800)
    assert color == "#507c44"
    for name, dimensions in {"thumb": (200, 400), "display": (600, 1200)}.items():
        with Image.open(io.BytesIO(variants[name]["data"])) as image:
            assert image.size == dimensions
            assert image.mode == "RGB"
            assert not image.getexif()


def test_small_transparent_image_is_flattened_without_upscaling():
    variants, width, height, color = build_variants(
        image_bytes((40, 20), "RGBA", (0, 0, 0, 0)), Settings(_env_file=None)
    )
    assert (width, height, color) == (40, 20, "#ffffff")
    assert variants["display"]["width"] == 40


@pytest.mark.parametrize("data", [b"", b"<svg>image</svg>", b"not an image"])
def test_invalid_formats_are_rejected(data):
    with pytest.raises(InvalidImage):
        validate_image(data, Settings(_env_file=None))


def test_byte_and_pixel_limits_are_enforced():
    data = image_bytes((100, 100))
    with pytest.raises(InvalidImage):
        validate_image(data, Settings(_env_file=None, upload_max_bytes=10))
    with pytest.raises(InvalidImage):
        validate_image(data, Settings(_env_file=None, image_max_pixels=9999))


def test_truncated_image_is_rejected():
    output = io.BytesIO()
    Image.new("RGB", (200, 200)).save(output, "JPEG")
    with pytest.raises(InvalidImage):
        validate_image(output.getvalue()[:-100], Settings(_env_file=None))


def test_bad_png_checksum_is_a_validation_error():
    corrupted = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
    )
    with pytest.raises(InvalidImage):
        validate_image(corrupted, Settings(_env_file=None))
