"""Bounded direct-image fetching with DNS pinning on every redirect, including HTTPS."""

import http.client
import ipaddress
import socket
import ssl
from time import monotonic
from urllib.parse import urljoin, urlsplit

from app.config import Settings
from app.media import InvalidImage, validate_image


class InvalidImport(ValueError):
    pass


def public_target(url: str):
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
    ):
        raise InvalidImport("Use a public HTTP(S) image URL without credentials")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if port not in {80, 443}:
            raise ValueError()
        host = parts.hostname.encode("idna").decode("ascii")
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (ValueError, UnicodeError, OSError) as exc:
        raise InvalidImport("The URL cannot be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise InvalidImport("Private, loopback and reserved addresses are not allowed")
    return parts, host, port, addresses[0][4][0]


def fetch_image(url: str, settings: Settings) -> bytes:
    deadline = monotonic() + 15
    for _ in range(4):
        parts, host, port, address = public_target(url)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise InvalidImport("Image import timed out")
        connection = http.client.HTTPConnection(host, port, timeout=min(5, remaining))
        try:
            connection.sock = socket.create_connection((address, port), timeout=min(5, remaining))
            if parts.scheme == "https":
                connection.sock = ssl.create_default_context().wrap_socket(
                    connection.sock, server_hostname=host
                )
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request(
                "GET",
                path,
                headers={
                    "Host": host,
                    "Accept": "image/*",
                    "Accept-Encoding": "identity",
                    "User-Agent": "Pinmorph-ImageImport/1",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                target = response.getheader("Location")
                if not target:
                    raise InvalidImport("Redirect has no destination")
                url = urljoin(url, target)
                continue
            if (
                response.status != 200
                or response.getheader("Content-Encoding", "identity").lower() != "identity"
            ):
                raise InvalidImport("Image server returned an unsupported response")
            if not response.getheader("Content-Type", "").lower().startswith("image/"):
                raise InvalidImport("Use a direct JPEG, PNG or WebP image URL")
            data = bytearray()
            while len(data) <= settings.upload_max_bytes:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise InvalidImport("Image import timed out")
                connection.sock.settimeout(min(5, remaining)) if connection.sock else None
                chunk = response.read(min(65536, settings.upload_max_bytes + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
            validate_image(bytes(data), settings)
            return bytes(data)
        except (OSError, http.client.HTTPException, InvalidImage) as exc:
            raise InvalidImport("Could not fetch a valid image within the import limits") from exc
        finally:
            connection.close()
    raise InvalidImport("Too many redirects")
