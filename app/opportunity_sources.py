"""Bounded reads for anchored pool quotes and explicitly sampled on-chain activity."""

from collections import Counter
from decimal import Decimal

from app.errors import ProviderError
from app.http_client import read_json
from app.models import Market, number, utcnow
from app.wallets import JUPITER_PROGRAM


async def pool_markets(providers, candidates):
    """One request per 30 distinct mints; never switch the candidate's original pool."""
    addresses = list(dict.fromkeys(c["contract"] for c in candidates))
    pairs = await providers.request(
        "dex", "GET", "https://api.dexscreener.com/tokens/v1/solana/" + ",".join(addresses)
    )
    if not isinstance(pairs, list):
        raise ProviderError("Pool quote batch has an invalid schema.")
    result = {}
    expected = {(c["pool"], c["contract"]) for c in candidates}
    for p in pairs:
        try:
            key = (p["pairAddress"], p["baseToken"]["address"])
            if p.get("chainId") != "solana" or key not in expected:
                continue
            result[key] = providers.parse_market(p, key[1]).model_dump()
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
    return result


async def fallback_pool(discovery, candidate):
    # A fixed public provider URL; addresses were validated at discovery.
    value = await read_json(
        discovery.client,
        "GET",
        f"https://api.geckoterminal.com/api/v2/networks/solana/pools/{candidate['pool']}",
    )
    return gecko_market(value["data"], candidate)


def gecko_market(row, candidate):
    a = row["attributes"]
    base = row["relationships"]["base_token"]["data"]["id"]
    if base != "solana_" + candidate["contract"] or a["address"] != candidate["pool"]:
        raise ProviderError("Pool identity does not match its first discovery.")
    tx = (a.get("transactions") or {}).get("m5") or {}
    buyers = tx.get("buyers")
    sellers = tx.get("sellers")
    if buyers is not None and tx.get("buys") is not None and buyers > tx["buys"]:
        buyers = None
    if sellers is not None and tx.get("sells") is not None and sellers > tx["sells"]:
        sellers = None
    return Market(
        address=candidate["contract"],
        name=a.get("name", "?"),
        symbol=a.get("name", "?").split(" / ")[0],
        pair_address=candidate["pool"],
        dex="GeckoTerminal reported pool",
        price_usd=number(a.get("base_token_price_usd")),
        liquidity_usd=number(a.get("reserve_in_usd")),
        volume_5m=number((a.get("volume_usd") or {}).get("m5"), None),
        volume_1h=number((a.get("volume_usd") or {}).get("h1"), None),
        change_5m=number((a.get("price_change_percentage") or {}).get("m5"), None),
        buys_5m=tx.get("buys"),
        sells_5m=tx.get("sells"),
        buyers_5m_reported=buyers,
        sellers_5m_reported=sellers,
        source="GeckoTerminal pool observation",
    ).model_dump()


async def gecko_markets(discovery, candidates):
    result = {}
    for i in range(0, len(candidates), 30):
        batch = candidates[i : i + 30]
        data = await read_json(
            discovery.client,
            "GET",
            "https://api.geckoterminal.com/api/v2/networks/solana/pools/multi/"
            + ",".join(c["pool"] for c in batch),
        )
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise ProviderError("Invalid multi-pool response.")
        bypool = {c["pool"]: c for c in batch}
        for row in data["data"]:
            try:
                pool = row["attributes"]["address"]
                if pool not in bypool:
                    continue
                c = bypool[pool]
                result[(pool, c["contract"])] = gecko_market(row, c)
            except (ValueError, TypeError, KeyError, ProviderError):
                continue
    return result


def sampled_activity(transactions, contract, pool):
    buyers = []
    sellers = []
    amounts = []
    slots = []
    unparsed = 0
    fees = []
    known_route_transactions = 0
    signers_by_slot = {}
    for transaction in transactions:
        try:
            meta = transaction["meta"]
            message = transaction["transaction"]["message"]
            keys = message["accountKeys"]
            pubkeys = {k["pubkey"] if isinstance(k, dict) else k for k in keys}
            if meta.get("err") or pool not in pubkeys:
                continue
            signers = {k["pubkey"] for k in keys if isinstance(k, dict) and k.get("signer")}
            programs = {
                i.get("programId") for i in message.get("instructions", []) if isinstance(i, dict)
            }
            for group in meta.get("innerInstructions") or []:
                programs |= {
                    i.get("programId") for i in group.get("instructions", []) if isinstance(i, dict)
                }
            deltas = {}
            for key, direction in [("preTokenBalances", -1), ("postTokenBalances", 1)]:
                for row in meta.get(key) or []:
                    if row.get("owner") not in signers:
                        continue
                    amount = row["uiTokenAmount"]
                    v = Decimal(amount["amount"]) / Decimal(10) ** int(amount["decimals"])
                    if not v.is_finite() or v < 0:
                        raise ValueError
                    owner = row["owner"]
                    mint = row["mint"]
                    deltas[(owner, mint)] = deltas.get((owner, mint), Decimal(0)) + direction * v
            for owner in signers:
                delta = deltas.get((owner, contract), Decimal(0))
                opposite = any(
                    o == owner and m != contract and v * delta < 0 for (o, m), v in deltas.items()
                )
                # A balance change is still only a swap candidate, even with a known route program.
                if not delta or not opposite:
                    continue
                (buyers if delta > 0 else sellers).append(owner)
                amounts.append(str(abs(delta)))
                slots.append(transaction.get("slot"))
                signers_by_slot.setdefault(transaction.get("slot"), set()).add(owner)
                fees.append(meta.get("fee"))
            if JUPITER_PROGRAM in programs:
                known_route_transactions += 1
        except (TypeError, KeyError, ValueError, AttributeError, ArithmeticError):
            unparsed += 1
    counts = Counter(buyers + sellers)
    n = sum(counts.values())
    suspicions = []
    share = max(counts.values()) / n if n else None
    if n >= 4 and share is not None and share >= 0.5:
        suspicions.append(
            {
                "kind": "sampled_trader_concentration",
                "severity": "medium",
                "origin": "sampled_statistical_suspicion",
                "value": share,
                "note": "Share of parsed swap-candidate events in a bounded sample, not market-wide buyer concentration.",
            }
        )
    if len(amounts) >= 4 and max(Counter(amounts).values()) / len(amounts) >= 0.75:
        suspicions.append(
            {
                "kind": "repeated_token_quantities",
                "severity": "medium",
                "origin": "sampled_statistical_suspicion",
                "note": "Repeated quantities can also reflect routing or regular orders; wash trading is not confirmed.",
            }
        )
    if any(len(v) >= 3 for k, v in signers_by_slot.items() if k is not None):
        suspicions.append(
            {
                "kind": "same_slot_participation",
                "severity": "medium",
                "origin": "sampled_statistical_suspicion",
                "note": "Shared slots alone do not establish common wallet control.",
            }
        )
    return {
        "observed_at": utcnow(),
        "sample_size": len(transactions),
        "parsed_swap_candidate_events": n,
        "unique_buy_candidates": len(set(buyers)) if n else None,
        "unique_sell_candidates": len(set(sellers)) if n else None,
        "max_wallet_share": share,
        "known_route_transactions": known_route_transactions,
        "unparsed": unparsed,
        "suspicions": suspicions,
        "coverage": "bounded recent pool transactions, not all trades or all unique buyers",
        "organic_demand_verified": False,
    }


async def pool_activity(onchain, candidate, limit):
    rows = await onchain.rpc(
        "solana",
        "getSignaturesForAddress",
        [candidate["pool"], {"limit": limit, "commitment": "confirmed"}],
    )
    if not isinstance(rows, list):
        raise ProviderError("Invalid pool signature sample.")
    transactions = []
    for row in rows[:limit]:
        if not isinstance(row, dict) or not isinstance(row.get("signature"), str):
            continue
        data = await onchain.rpc(
            "solana",
            "getTransaction",
            [
                row["signature"],
                {
                    "encoding": "jsonParsed",
                    "commitment": "confirmed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        )
        transactions.append(data)
    return sampled_activity(transactions, candidate["contract"], candidate["pool"])


def monitored_wallets(wallets, contract, at):
    from app.models import epoch

    events = []
    for wallet in wallets.listing():
        if wallet["chain"] != "solana":
            continue
        for event in wallet["activity"]:
            p = event["payload"]
            delta = number((p.get("token_deltas") or {}).get(contract), None)
            block = p.get("block_time")
            if (
                delta is not None
                and delta
                and block
                and 0 <= epoch(at) - block <= 3600
                and epoch(event["at"]) <= epoch(at)
            ):
                events.append(
                    {
                        "wallet_id": wallet["id"],
                        "event_id": event["event_id"],
                        "delta": delta,
                        "block_time": block,
                        "kind": p.get("kind"),
                    }
                )
    return {
        "score": None,
        "events": events,
        "note": "Observed deltas from user-tracked wallets; transfers and swap candidates do not establish smart-money quality, cost basis or profitability.",
    }
