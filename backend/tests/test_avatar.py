import base64
import gzip

import httpcore
import httpx
import pytest
from httpcore._backends.auto import AutoBackend

from eidolon import avatar
from eidolon.own_keys import NotPublic


class RawStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self.content = content

    async def __aiter__(self):
        yield self.content


@pytest.mark.asyncio
@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.1.1", "224.0.0.1", "::1", "fc00::1", "fe80::1", "ff02::1", "::ffff:127.0.0.1"])
async def test_rejects_non_public_address(monkeypatch, address):
    async def resolve(host, port):
        return ["8.8.8.8", address]

    monkeypatch.setattr(avatar, "resolve", resolve)
    with pytest.raises(NotPublic):
        await avatar._public_addresses("example.com", 443)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,content_type,body", [
    (302, "image/png", b""),
    (200, "text/html", b"hello"),
    (200, "image/svg+xml", b"<svg/>"),
    (200, "image/png", b"x" * (5 * 1024 * 1024 + 1)),
])
async def test_rejects_unsafe_responses(monkeypatch, status, content_type, body):
    monkeypatch.setattr(avatar, "_transport", lambda: httpx.MockTransport(
        lambda request: httpx.Response(status, headers={"content-type": content_type, "location": "http://127.0.0.1/"}, stream=RawStream(body))
    ))
    with pytest.raises(avatar.InvalidAvatar):
        await avatar.fetch_avatar("https://example.com/avatar")


@pytest.mark.asyncio
async def test_fetches_image_at_checked_address_without_sending_cookies(monkeypatch):
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/aXkAAAAASUVORK5CYII="
    )
    connections = []
    lookups = []

    class Stream(httpcore.AsyncNetworkStream):
        def __init__(self):
            self.response = (
                b"HTTP/1.1 200 OK\r\nContent-Type: image/png\r\n"
                + f"Content-Length: {len(png)}\r\n".encode()
                + b"Set-Cookie: secret=1\r\n\r\n"
                + png
            )
            self.request = b""
            self.server_hostname = None

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            self.server_hostname = server_hostname
            return self

        async def write(self, buffer, timeout=None):
            self.request += buffer

        async def read(self, max_bytes, timeout=None):
            result, self.response = self.response[:max_bytes], self.response[max_bytes:]
            return result

        async def aclose(self):
            pass

    stream = Stream()

    async def resolve(host, port):
        lookups.append((host, port))
        return ["8.8.8.8"]

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        connections.append((host, port))
        return stream

    monkeypatch.setattr(avatar, "resolve", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect_tcp)
    assert await avatar.fetch_avatar("https://example.com/image") == (png, "image/png")
    assert lookups == [("example.com", 443)]
    assert connections == [("8.8.8.8", 443)]
    assert stream.server_hostname == "example.com"
    headers = stream.request.lower().split(b"\r\n")
    assert b"host: example.com" in headers
    assert not any(header.startswith(b"cookie:") for header in headers)
    with pytest.raises(avatar.InvalidAvatar):
        await avatar.fetch_avatar("file:///etc/passwd")


@pytest.mark.asyncio
async def test_rejects_mixed_addresses_before_connecting(monkeypatch):
    connections = []

    async def resolve(host, port):
        return ["8.8.8.8", "127.0.0.1"]

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        connections.append((host, port))
        raise AssertionError("must not connect to a mixed DNS result")

    monkeypatch.setattr(avatar, "resolve", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect_tcp)
    with pytest.raises(avatar.InvalidAvatar):
        await avatar.fetch_avatar("https://example.com/image")
    assert connections == []


@pytest.mark.asyncio
async def test_rejects_compressed_avatar(monkeypatch):
    monkeypatch.setattr(avatar, "_transport", lambda: httpx.MockTransport(
        lambda request: httpx.Response(
            200, headers={"content-type": "image/png", "content-encoding": "gzip"},
            stream=RawStream(gzip.compress(b"image")),
        )
    ))
    with pytest.raises(avatar.InvalidAvatar):
        await avatar.fetch_avatar("https://example.com/avatar")
