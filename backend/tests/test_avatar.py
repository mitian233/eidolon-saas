import httpx
import pytest

from eidolon import avatar
from eidolon.own_keys import NotPublic


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
        lambda request: httpx.Response(status, headers={"content-type": content_type, "location": "http://127.0.0.1/"}, content=body)
    ))
    with pytest.raises(avatar.InvalidAvatar):
        await avatar.fetch_avatar("https://example.com/avatar")


@pytest.mark.asyncio
async def test_fetches_image_without_sending_cookies(monkeypatch):
    def handle(request):
        assert "cookie" not in request.headers
        return httpx.Response(200, headers={"content-type": "image/png", "set-cookie": "secret=1"}, content=b"image")
    monkeypatch.setattr(avatar, "_transport", lambda: httpx.MockTransport(handle))
    assert await avatar.fetch_avatar("https://example.com/image") == (b"image", "image/png")
    with pytest.raises(avatar.InvalidAvatar):
        await avatar.fetch_avatar("file:///etc/passwd")
