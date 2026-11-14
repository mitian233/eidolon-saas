"""Fetch a character's external avatar without exposing the server's network."""

import asyncio
import ipaddress

import httpcore
import httpx

from eidolon.own_keys import NotPublic, PublicOnlyBackend, resolve

MAX_AVATAR_BYTES = 5 * 1024 * 1024
AVATAR_TIMEOUT = 10.0


class InvalidAvatar(Exception):
    """The avatar could not be safely fetched."""


async def _public_addresses(host: str, port: int) -> list[str]:
    addresses = await resolve(host, port)
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_link_local:
            raise NotPublic("Not a public address")
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            mapped = ip.ipv4_mapped
            if not mapped.is_global or mapped.is_multicast or mapped.is_reserved:
                raise NotPublic("Not a public address")
    return addresses


def _transport() -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport()
    pool = transport._pool
    assert isinstance(pool, httpcore.AsyncConnectionPool)
    pool._network_backend = PublicOnlyBackend(pool._network_backend, _public_addresses)
    return transport


async def fetch_avatar(url: str) -> tuple[bytes, str]:
    try:
        parsed = httpx.URL(url)
        if parsed.scheme not in ("http", "https") or not parsed.host or parsed.userinfo:
            raise InvalidAvatar()
        transport = _transport()
        async with asyncio.timeout(AVATAR_TIMEOUT):
            async with httpx.AsyncClient(transport=transport, trust_env=False, timeout=AVATAR_TIMEOUT, follow_redirects=False) as client:
                async with client.stream("GET", parsed, headers={"Accept": "image/*", "Accept-Encoding": "identity"}) as response:
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    # SVG can contain active content; reject it rather than serve it from our origin.
                    if response.status_code != 200 or not content_type.startswith("image/") or content_type == "image/svg+xml":
                        raise InvalidAvatar()
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_AVATAR_BYTES:
                            raise InvalidAvatar()
                    return bytes(content), content_type
    except (httpx.HTTPError, httpx.InvalidURL, OSError, ValueError, TimeoutError) as exc:
        raise InvalidAvatar() from exc
