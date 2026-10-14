"""Bounded read-only HTTP, sanitized failures and limited retries for public data."""

import asyncio
import json
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

from app.errors import ProviderError


def retry_delay(value, attempt):
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            seconds = 2**attempt
    return min(4, max(0, seconds)) if math.isfinite(seconds) else 4


async def read_response(client, method, url, *, attempts=3, max_bytes=2_000_000, **kwargs):
    for attempt in range(attempts):
        try:
            async with client.stream(method, url, follow_redirects=False, **kwargs) as response:
                if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                    await asyncio.sleep(retry_delay(response.headers.get("Retry-After"), attempt))
                    continue
                response.raise_for_status()
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ProviderError("Răspunsul sursei depășește limita de dimensiune.")
                    chunks.append(chunk)
                return b"".join(chunks), response.headers
        except httpx.TransportError as exc:
            if attempt + 1 < attempts:
                await asyncio.sleep(2**attempt)
                continue
            raise ProviderError(f"Sursă indisponibilă: {type(exc).__name__}.") from None
        except httpx.HTTPStatusError as exc:
            raise ProviderError(f"Sursa a răspuns HTTP {exc.response.status_code}.") from None
    raise ProviderError("Sursa nu a returnat date.")


async def read_json(client, method, url, **kwargs):
    raw, _ = await read_response(client, method, url, **kwargs)
    try:

        def invalid_constant(value):
            raise ValueError("Non-finite JSON number")

        return json.loads(raw, parse_constant=invalid_constant)
    except (ValueError, TypeError):
        raise ProviderError("Sursa a returnat JSON invalid.") from None
