"""Resolve explicit publisher DEX pool links without treating pool IDs as mints."""

import asyncio
import hashlib
import json
import math
import re
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import httpx

from app.assets import safe_link
from app.errors import ProviderError
from app.http_client import read_json
from app.models import epoch, number, solana_address, utcnow
from app.providers import Providers

QUOTE_ASSETS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}


def pool_slug(url):
    if not safe_link(url):
        return None
    parsed = urlsplit(url)
    if {key.casefold() for key in parse_qs(parsed.query)} & {"cluster", "network", "chain"}:
        return None
    match = re.fullmatch(r"/solana/([A-Za-z0-9]{32,44})/?", parsed.path)
    return match[1] if parsed.hostname == "dexscreener.com" and match else None


def validated_reference(ref):
    slug = pool_slug(ref["reference_url"])
    if not slug or ref.get("state") != "resolved":
        raise ValueError("Not a resolved Solana market reference")
    for key in ["pool", "base_contract", "quote_contract"]:
        solana_address(ref[key])
    if ref["pool"].casefold() != slug.casefold() or ref["base_contract"] == ref["quote_contract"]:
        raise ValueError("Pool identity mismatch")
    if not isinstance(ref["negative_context"], bool) or not re.fullmatch(
        r"[a-f0-9]{64}", ref["response_sha256"]
    ):
        raise ValueError("Invalid reference provenance")
    observed = datetime.fromisoformat(ref["observed_at"])
    if observed.tzinfo is None:
        raise ValueError("Observation timestamp requires a timezone")
    for key in [
        "price_usd",
        "liquidity_usd",
        "price_change_24h_reported_pct",
        "pool_created_at_reported",
    ]:
        value = ref.get(key)
        if value is None and key in {"price_change_24h_reported_pct", "pool_created_at_reported"}:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("Invalid market value")
        if key == "price_usd" and value <= 0 or key == "liquidity_usd" and value < 0:
            raise ValueError("Invalid market value")
        if key == "pool_created_at_reported" and not 0 < value / 1000 <= epoch(ref["observed_at"]):
            raise ValueError("Invalid reported pool creation time")
        if key == "price_change_24h_reported_pct" and value < -100:
            raise ValueError("Invalid reported price change")
    return ref | {
        "issuer_verified": False,
        "contract_printed_in_document": False,
        "qualifies_for_discovery": ref["quote_contract"] in QUOTE_ASSETS
        and ref["base_contract"] not in QUOTE_ASSETS
        and not ref["negative_context"],
    }


async def resolve_references(document, client):
    # Imported here to avoid a parser/reader import cycle.
    from app.announcements import NEGATIVE

    refs = []
    seen = set()
    for link in document["links"]:
        slug = pool_slug(link)
        if not slug or slug.casefold() in seen:
            continue
        seen.add(slug.casefold())
        context = " ".join(
            x["text"] for x in document.get("link_contexts", []) if x["url"] == link
        )[:1500]
        ref = {
            "reference_url": link,
            "excerpt": context,
            "negative_context": bool(NEGATIVE.search(context)),
            "issuer_verified": False,
            "contract_printed_in_document": False,
        }
        try:
            async with asyncio.timeout(8):
                result = await read_json(
                    client,
                    "GET",
                    "https://api.dexscreener.com/latest/dex/pairs/solana/" + slug,
                    attempts=1,
                )
            if not isinstance(result, dict) or not isinstance(result.get("pairs"), list):
                raise ValueError("Invalid pair response")
            matches = [
                p
                for p in result["pairs"]
                if isinstance(p, dict)
                and p.get("chainId") == "solana"
                and isinstance(p.get("pairAddress"), str)
                and p["pairAddress"].casefold() == slug.casefold()
            ]
            if len(matches) != 1:
                raise ValueError("Pool is absent or ambiguous")
            pair = matches[0]
            market = Providers.parse_market(pair, pair["baseToken"]["address"])
            ref.update(
                state="resolved",
                pool=market.pair_address,
                base_contract=market.address,
                quote_contract=pair["quoteToken"]["address"],
                base_name=market.name,
                quote_name=str(pair["quoteToken"].get("name", "?"))[:100],
                observed_at=utcnow(),
                price_usd=market.price_usd,
                liquidity_usd=market.liquidity_usd,
                pool_created_at_reported=market.pool_created_at,
                price_change_24h_reported_pct=number(
                    (pair.get("priceChange") or {}).get("h24"), None
                ),
                response_sha256=hashlib.sha256(
                    json.dumps(result, sort_keys=True, allow_nan=False).encode()
                ).hexdigest(),
                identity_source="DEX Screener pair response; not issuer verification",
            )
            ref = validated_reference(ref)
            ref["warning"] = (
                None
                if ref["qualifies_for_discovery"]
                else "Quote asset is outside the supported infrastructure set, or context is negative; no automatic candidate from this reference."
            )
        except (
            ProviderError,
            httpx.HTTPError,
            TimeoutError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            OverflowError,
        ):
            ref.update(
                state="unavailable",
                observed_at=utcnow(),
                qualifies_for_discovery=False,
                error="Pool reference could not be validated; no mint address is inferred.",
            )
        refs.append(ref)
        if len(refs) == 2:
            break
    return refs
