"""Sourced fundamentals: reported metadata, direct RPC observations and human reviews."""

import asyncio
import json

from app.announcements import PLATFORMS, inspect_contract
from app.errors import ProviderError
from app.models import freshness, utcnow

CATEGORIES = (
    "identity",
    "announcement",
    "product",
    "team",
    "tokenomics",
    "distribution",
    "unlocks",
    "audit",
    "contract_risk",
    "liquidity",
)


class Fundamentals:
    def __init__(self, service, onchain):
        self.service, self.store, self.onchain = service, service.store, onchain
        self.lock = asyncio.Lock()
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS fundamental_observations(id INTEGER PRIMARY KEY,address TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL)"
            )

    async def refresh(self, address):
        if self.lock.locked():
            raise ProviderError("O colectare fundamentală este deja în curs.")
        async with self.lock:
            profile, errors, facts, targets = None, [], [], []
            if address.startswith("asset:"):
                try:
                    profile = await self.service.assets.profile(address[6:])
                    for chain, contract in profile.get("contracts", {}).items():
                        if PLATFORMS.get(chain) in {"solana", "base"} and contract:
                            targets.append((PLATFORMS[chain], contract))
                    facts.append(
                        {
                            "category": "identity",
                            "origin": "provider_reported",
                            "source": "CoinGecko",
                            "observed_at": profile.get("observed_at", utcnow()),
                            "value": profile["contracts"],
                            "independently_verified": False,
                        }
                    )
                    facts.append(
                        {
                            "category": "product",
                            "origin": "provider_reported",
                            "source": "CoinGecko",
                            "value": profile.get("documents", []),
                            "independently_verified": False,
                        }
                    )
                except ProviderError as exc:
                    errors.append(str(exc))
            else:
                targets = [("solana", address)]
            for chain, contract in targets[:3]:
                try:
                    observation = await self.onchain.token(chain, contract)
                    if observation.get("distribution_error"):
                        errors.append(chain + " distribution: " + observation["distribution_error"])
                    facts.append(
                        {
                            "category": "contract_risk",
                            "origin": "rpc_observation",
                            "source": chain + " mainnet RPC",
                            "value": observation,
                            "independently_verified": False,
                        }
                    )
                    facts.append(
                        {
                            "category": "distribution",
                            "origin": "rpc_observation",
                            "source": chain + " mainnet RPC",
                            "value": {
                                k: observation.get(k)
                                for k in (
                                    "raw_supply",
                                    "decimals",
                                    "top10_token_accounts_pct",
                                    "distribution_note",
                                )
                            },
                            "independently_verified": False,
                        }
                    )
                except (ProviderError, ValueError, KeyError, TypeError, AttributeError) as exc:
                    errors.append(
                        str(exc)
                        if isinstance(exc, ProviderError)
                        else "Date on-chain incompatibile."
                    )
            market = (
                self.service.assets.get(address[6:])
                if address.startswith("asset:")
                else (self.store.latest(address) or {}).get("market")
            )
            if market:
                facts.append(
                    {
                        "category": "liquidity",
                        "origin": "market_observation",
                        "source": market.get("source", "market provider"),
                        "observed_at": market.get("observed_at"),
                        "value": {
                            k: market.get(k)
                            for k in ("liquidity_usd", "volume_24h", "market_cap", "fdv", "book")
                        },
                        "freshness": freshness(
                            market.get("observed_at"),
                            market.get("source_updated_at", market.get("observed_at")),
                        ),
                        "independently_verified": False,
                    }
                )
            payload = {
                "address": address,
                "observed_at": utcnow(),
                "facts": facts,
                "errors": errors,
                "complete": False,
                "fundamentals_verified": False,
                "note": "RPC arată starea observată, metadata sunt declarații ale furnizorului, evaluările sunt manuale. Produsul, echipa, vesting-ul și auditurile cer dovezi separate; existența unui contract nu validează calitatea proiectului.",
            }
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO fundamental_observations(address,at,payload) VALUES(?,?,?)",
                    (address, utcnow(), json.dumps(payload)),
                )
            return self.report(address)

    def report(self, address):
        case = self.service.research.case(address)
        with self.store.connect() as db:
            row = db.execute(
                "SELECT at,payload FROM fundamental_observations WHERE address=? ORDER BY id DESC LIMIT 1",
                (address,),
            ).fetchone()
        observation = json.loads(row["payload"]) if row else None
        checks = {c["key"]: c["status"] for c in case["checks"]}
        return {
            "address": address,
            "categories": [
                {"key": category, "review_state": checks.get(category, "unknown")}
                for category in CATEGORIES
            ],
            "observations": observation,
            "manual_evidence": case["evidence"],
            "ai_interpretations": case["ai"],
            "observations_fresh": freshness(row["at"], row["at"], 86400)["fresh"] if row else False,
            "fundamentals_verified": False,
            "missing": [c for c in CATEGORIES if checks.get(c) != "supported_manual"],
        }

    async def identity(self, address, body, profile=None):
        check = await self.service.research.announcements.verify(address, body, profile)
        checks = self.service.research.announcements.checks(address)
        conflicting = [
            c
            for c in checks
            if c["effective_status"] in {"negative_context", "identity_mismatch", "chain_mismatch"}
        ]
        return {
            "subject": address,
            "document_check": check,
            "conflicting_observations": conflicting,
            "official_status": "conflicting_evidence"
            if conflicting
            else "supported_manual_source"
            if check["effective_status"] == "manual_source_match"
            else "unverified",
            "official_verified": False,
            "note": "Adrese diferite cu același nume sunt candidați de clonă/variantă, nu dovadă automată de fraudă. Emitentul necesită verificare independentă.",
        }

    async def circle_usdc(self, chain, contract):
        """Scoped official registry comparison, never generalized to namesake assets."""
        document = await self.service.research.announcements.document(
            "https://developers.circle.com/stablecoins/usdc-contract-addresses", force=True
        )
        observed = inspect_contract(document, chain, contract)
        return {
            "project": "Circle USDC",
            "chain": chain,
            "contract": contract,
            "issuer_registry_match": bool(
                observed["exact_contract_found"]
                and observed["chain_supported"]
                and not observed["negative_context"]
            ),
            "observations": observed,
            "source_url": document["url"],
            "sha256": document["sha256"],
            "observed_at": document["observed_at"],
            "claim_scope": "contract listed on Circle USDC registry page; not a full contract security audit",
            "fundamentals_verified": False,
        }
