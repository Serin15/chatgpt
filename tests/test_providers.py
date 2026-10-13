import asyncio

import httpx
import pytest

from app.providers import ProviderError, Providers
from tests.conftest import ADDRESS, OTHER


def pair(base=ADDRESS, liquidity=50000, **overrides):
    return {
        "chainId": "solana",
        "baseToken": {"address": base, "name": "Fixture", "symbol": "FIX"},
        "quoteToken": {"address": OTHER},
        "pairAddress": OTHER,
        "priceUsd": "1",
        "liquidity": {"usd": liquidity},
        "dexId": "test",
    } | overrides


def run_provider(settings, response, method, *args):
    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response))
        provider = Providers(settings, client)
        try:
            return await getattr(provider, method)(*args)
        finally:
            await provider.close()

    return asyncio.run(run())


def test_market_uses_base_token_and_deepest_single_pool(settings):
    data = [pair(liquidity=10000), pair(liquidity=50000), pair(base=OTHER, liquidity=9999999)]
    result = run_provider(settings, httpx.Response(200, json=data), "market", ADDRESS)
    assert result.liquidity_usd == 50000
    assert result.volume_5m is None  # missing != zero
    assert result.buys_5m is None


def test_profiles_deduplicated_and_chain_filtered(settings):
    data = [
        {"chainId": "solana", "tokenAddress": ADDRESS},
        {"chainId": "solana", "tokenAddress": ADDRESS},
        {"chainId": "base", "tokenAddress": OTHER},
        {"chainId": "solana", "tokenAddress": "invalid"},
    ]
    assert run_provider(settings, httpx.Response(200, json=data), "discover") == [ADDRESS]


def test_empty_market_is_not_a_price(settings):
    with pytest.raises(ProviderError, match="nicio pereche"):
        run_provider(settings, httpx.Response(200, json=[]), "market", ADDRESS)


def test_provider_failure_is_explicit(settings):
    with pytest.raises(ProviderError, match="HTTP 403"):
        run_provider(settings, httpx.Response(403, text="denied"), "discover")


def test_missing_goplus_report_is_not_clean(settings):
    with pytest.raises(ProviderError, match="indisponibil"):
        run_provider(
            settings, httpx.Response(200, json={"code": 1, "result": {}}), "goplus", ADDRESS
        )


def test_rpc_base64_fallback_remains_unknown(settings):
    data = {"result": {"value": {"data": ["AAAA", "base64"]}}}
    with pytest.raises(ProviderError, match="neinterpretate"):
        run_provider(settings, httpx.Response(200, json=data), "mint_info", ADDRESS)


def test_rpc_json_error_not_treated_as_success(settings):
    with pytest.raises(ProviderError, match="JSON-RPC"):
        run_provider(
            settings, httpx.Response(200, json={"error": {"code": -32602}}), "mint_info", ADDRESS
        )


def test_null_market_optionals_preserved(settings):
    result = run_provider(
        settings,
        httpx.Response(200, json=[pair(volume=None, priceChange=None, txns=None)]),
        "market",
        ADDRESS,
    )
    assert result.volume_5m is None
    assert result.change_5m is None


def test_invalid_response_schema_becomes_provider_error(settings):
    with pytest.raises(ProviderError, match="schema"):
        run_provider(settings, httpx.Response(200, json=[None]), "market", ADDRESS)
