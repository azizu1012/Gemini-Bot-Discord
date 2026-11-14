"""Bounded HTTP body reading for untrusted web and image downloads."""

from __future__ import annotations

import zlib

import aiohttp


class DownloadTooLarge(ValueError):
    pass


async def read_limited_response(response: aiohttp.ClientResponse, max_bytes: int) -> bytes:
    """Read at most max_bytes decompressed bytes (session auto_decompress=False).

    Bound decompressor output too: aiohttp's automatic decompression can expand
    a small wire chunk into an arbitrarily large allocation before a read limit.
    """
    declared = response.headers.get("Content-Length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise DownloadTooLarge("Response exceeds download limit")
    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in {"identity", "", "gzip", "deflate"}:
        raise ValueError("Unsupported content encoding")
    decoder = None
    if encoding in {"gzip", "deflate"}:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == "gzip" else zlib.MAX_WBITS)
    result = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        remaining = max_bytes - len(result)
        decoded = decoder.decompress(chunk, remaining + 1) if decoder else chunk
        if len(decoded) > remaining:
            raise DownloadTooLarge("Response exceeds download limit")
        result.extend(decoded)
        if decoder and decoder.unused_data:
            raise ValueError("Unexpected trailing compressed data")
    if decoder and not decoder.eof:
        raise ValueError("Incomplete compressed response")
    return bytes(result)
