"""Observed trading venues and separately sourced, manually reviewed listing schedules."""

import json
import re

from pydantic import AwareDatetime, Field

from app.ai_research import StrictModel
from app.announcements import VerificationInput, normalized
from app.assets import safe_link
from app.errors import ProviderError
from app.http_client import read_json
from app.models import number, utcnow
from app.onchain import chain_address


class ListingInput(StrictModel):
    source_url: str
    chain: str
    contract: str
    excerpt: str = Field(min_length=20, max_length=2000)
    venue: str = Field(min_length=2, max_length=100)
    starts_at: AwareDatetime | None = None
    reviewed: bool = False


class Listings:
    def __init__(self, service):
        self.service, self.store = service, service.store
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS listing_schedules(id INTEGER PRIMARY KEY,address TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL)"
            )

    async def venues(self, address, chain="solana"):
        if address.startswith("asset:"):
            return {
                "venues": await self.service.assets.venues(address[6:]),
                "execution_verified": False,
                "prelisting_access": "not_established",
            }
        address = chain_address(chain, address)
        pairs = await read_json(
            self.service.providers.client,
            "GET",
            f"https://api.dexscreener.com/token-pairs/v1/{chain}/{address}",
        )
        if not isinstance(pairs, list):
            raise ProviderError("Date de pool invalide.")
        venues = []
        for p in pairs:
            try:
                if (
                    p["chainId"] != chain
                    or chain_address(chain, p["baseToken"]["address"]) != address
                ):
                    continue
                liquidity = number((p.get("liquidity") or {}).get("usd"))
                price = number(p.get("priceUsd"))
                url = p.get("url")
                if liquidity <= 0 or price <= 0 or not safe_link(url):
                    continue
                venues.append(
                    {
                        "name": p.get("dexId", "unknown"),
                        "chain": chain,
                        "contract": address,
                        "pool": p["pairAddress"],
                        "url": url,
                        "liquidity_usd_reported": liquidity,
                        "price_usd_reported": price,
                        "volume_24h_reported": number((p.get("volume") or {}).get("h24"), None),
                        "observed_at": utcnow(),
                        "source": "DEX Screener",
                        "execution_verified": False,
                    }
                )
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        return {
            "venues": venues,
            "execution_verified": False,
            "prelisting_access": "not_established",
            "note": "Perechi cu piață raportată pentru contractul exact. Disponibilitatea ordinului, accesul presale și listările viitoare nu rezultă din aceste date.",
        }

    async def add_schedule(self, address, body, profile=None):
        target = VerificationInput(
            source_url=body.source_url, chain=body.chain, contract=body.contract
        )
        document = await self.service.research.announcements.document(body.source_url, force=True)
        if normalized(body.excerpt) not in document["text"] or not re.search(
            r"\blist(?:ing|ed|s)?\b|trading|spot market", body.excerpt, re.I
        ):
            raise ProviderError(
                "Extrasul nu există în document sau nu indică un anunț de listare/tranzacționare."
            )
        check = await self.service.research.announcements.verify(
            address, target, profile, force=False
        )
        supported = (
            check["effective_status"] == "manual_source_match"
            and check["payload"].get("relationship") == "listing"
            and body.reviewed
        )
        payload = body.model_dump(mode="json") | {
            "source_sha256": document["sha256"],
            "observed_at": document["observed_at"],
            "document_check": check,
            "state": "supported_manual_source_schedule" if supported else "unconfirmed_schedule",
            "execution_verified": False,
            "date_origin": "manual_transcription_from_source",
            "prelisting_access": "not_established",
        }
        with self.store.connect() as db:
            row = db.execute(
                "INSERT INTO listing_schedules(address,at,payload) VALUES(?,?,?)",
                (address, utcnow(), json.dumps(payload)),
            )
        return {"id": row.lastrowid, "payload": payload}

    def schedules(self, address):
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM listing_schedules WHERE address=? ORDER BY id DESC LIMIT 20",
                (address,),
            ).fetchall()
        # Preserve historical review while rechecking its current approval/age state.
        current = {c["id"]: c for c in self.service.research.announcements.checks(address)}
        result = []
        for row in rows:
            payload = json.loads(row["payload"])
            check = current.get(payload["document_check"]["id"])
            active = (
                check
                and check["effective_status"] == "manual_source_match"
                and check["payload"].get("relationship") == "listing"
            )
            result.append(
                dict(row)
                | {
                    "payload": payload,
                    "effective_state": payload["state"] if active else "unconfirmed_schedule",
                }
            )
        return result
