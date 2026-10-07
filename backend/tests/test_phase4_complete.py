import io
import socket

import pytest
from PIL import Image

from app.product.api import PreferencesInput
from app.product.safety import pixel_hash
from app.product.url_import import InvalidImport, public_target


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://127.0.0.1/image",
        "http://[::1]/image",
        "http://169.254.169.254/",
        "http://user:pass@example.com/image",
        "https://example.com:8080/image",
    ],
)
def test_import_rejects_internal_and_unsupported_targets(url):
    with pytest.raises(InvalidImport):
        public_target(url)


def test_import_rejects_mixed_public_private_dns_answers(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *a, **k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(InvalidImport):
        public_target("https://images.example/image.png")


def test_duplicate_hash_compares_pixels_across_encodings():
    image = Image.new("RGB", (32, 32), "blue")
    outputs = []
    for compression in (0, 9):
        buf = io.BytesIO()
        image.save(buf, "PNG", compress_level=compression)
        outputs.append(buf.getvalue())
    assert outputs[0] != outputs[1]
    assert pixel_hash(outputs[0]) == pixel_hash(outputs[1])
    other = io.BytesIO()
    Image.new("RGB", (32, 32), "red").save(other, "PNG")
    assert pixel_hash(other.getvalue()) != pixel_hash(outputs[0])


def test_preferences_do_not_accept_arbitrary_terms_or_duplicates():
    from pydantic import ValidationError

    for interests in (["unknown"], ["art", "art"]):
        with pytest.raises(ValidationError):
            PreferencesInput(interests=interests)
    assert PreferencesInput(interests=[]).onboarding_complete
