import io
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from app.config import Settings
from app.discovery.config import DiscoveryConfig
from app.discovery.crop import CropBox, prepare_crop
from app.discovery.service import DiscoveryServices
from app.feed.registry import Registry
from app.media import InvalidImage
from app.models import Pin
from app.search.service import SearchQuery, decode_cursor, encode_cursor
from app.social.schemas import SectionAssignment


def test_search_cursor_is_bound_to_query_and_filters():
    query = SearchQuery(q="  GREEN   chairs ", provenance="hm")
    assert query.q == "green chairs"
    pin = Pin(id=str(uuid4()), created_at=datetime(2026, 10, 7, tzinfo=UTC))
    cursor = encode_cursor(query, pin)
    assert decode_cursor(cursor, query) == (pin.created_at, pin.id)
    for other in [SearchQuery(q="other"), SearchQuery(q="green chairs")]:
        with pytest.raises(ValueError, match="Invalid cursor"):
            decode_cursor(cursor, other)


@pytest.mark.parametrize("value", ["bad", "W10=", "bnVsbA==", "e30=", "===="])
def test_search_cursor_rejects_malformed_payloads(value):
    with pytest.raises(ValueError, match="Invalid cursor"):
        decode_cursor(value, SearchQuery(q="chairs"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"q": "  "},
        {"q": "!!!"},
        {"q": "chair", "owner_id": "x" * 36},
        {
            "q": "chair",
            "created_after": "2026-10-08T00:00:00Z",
            "created_before": "2026-10-07T00:00:00Z",
        },
        {"q": "chair", "created_after": "2026-10-07T00:00:00"},
        {"q": "chair", "provenance": "unknown"},
    ],
)
def test_search_rejects_invalid_queries(kwargs):
    with pytest.raises(ValidationError):
        SearchQuery(**kwargs)


def test_crop_uses_oriented_pixel_coordinates_and_strips_metadata():
    image = Image.new("RGBA", (8, 6), (255, 0, 0, 0))
    output = io.BytesIO()
    image.save(output, "PNG")
    prepared = prepare_crop(
        output.getvalue(), CropBox(left=0.25, top=0, right=0.75, bottom=0.5), Settings()
    )
    assert prepared.pixel_box == (2, 0, 6, 3)
    assert prepared.oriented_size == (8, 6)
    with Image.open(io.BytesIO(prepared.image_bytes)) as crop:
        assert crop.size == (4, 3) and crop.mode == "RGB"
        assert crop.getpixel((0, 0)) == (255, 255, 255)
        assert not crop.getexif()
    assert (
        prepare_crop(output.getvalue(), CropBox(), Settings()).crop_sha256 != prepared.crop_sha256
    )


def test_crop_applies_exif_orientation_before_selecting_region():
    image = Image.new("RGB", (12, 8), "green")
    exif = image.getexif()
    exif[274] = 6
    output = io.BytesIO()
    image.save(output, "JPEG", exif=exif)
    crop = prepare_crop(output.getvalue(), CropBox(right=0.5), Settings())
    assert crop.oriented_size == (8, 12) and crop.pixel_box == (0, 0, 4, 12)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"left": 0.5, "right": 0.5},
        {"top": 0.8, "bottom": 0.2},
        {"left": -0.1},
        {"right": float("nan")},
        {"bottom": float("inf")},
    ],
)
def test_crop_rejects_invalid_boxes(kwargs):
    with pytest.raises(ValidationError):
        CropBox(**kwargs)


def test_crop_rejects_invalid_image():
    with pytest.raises(InvalidImage):
        prepare_crop(b"not an image", CropBox(), Settings())


def test_section_assignment_can_explicitly_clear_section():
    assert SectionAssignment(section_id=None).section_id is None
    with pytest.raises(ValidationError):
        SectionAssignment(section_id="bad")


@pytest.mark.parametrize(
    "component", ["following_source", "related_source", "crop_embedder", "lens_service"]
)
def test_discovery_rejects_unknown_versions_before_serving(component):
    with pytest.raises(ValueError, match="Unknown implementation"):
        DiscoveryServices(DiscoveryConfig(**{component: "unknown:v1"}))


def test_discovery_can_swap_source_through_registry_and_config():
    class Alternative:
        version = "candidate:following-fixture:v2"

        def retrieve(self, db, context):
            raise AssertionError("Constructing the registry must not serve or run inference")

    source = Alternative()
    registry = Registry()
    registry.register(source.version, source)
    services = DiscoveryServices(
        DiscoveryConfig(following_source=source.version), following_registry=registry
    )
    assert services.following_source is source
