"""Durable, bounded document-contract -> market-pool handoff.

Unresolved addresses remain recorded. A market lookup cannot verify an issuer,
and a pool discovered from a news story is never labeled a new token launch.
"""

import asyncio
import json
import time
from datetime import UTC, datetime

import httpx

from app.errors import ProviderError
from app.models import Market, epoch, solana_address, utcnow


class StoryDiscovery:
    def __init__(self, service, stories):
        self.service, self.store, self.stories = service, service.store, stories
        self.status = {"state": "unverified", "at": None}
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS story_pool_lookups(
                    contract TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL,
                    next_due REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS story_pool_due ON story_pool_lookups(state,next_due);
            """)

    def enqueue(self, at):
        now = epoch(at)
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT c.contract FROM story_contracts c
                JOIN story_documents s ON s.document_id=c.document_id
                JOIN news n ON n.id=s.news_id
                LEFT JOIN story_pool_lookups l ON l.contract=c.contract
                WHERE c.association='exact_contract_document_mention' AND s.available_at<=?
                AND julianday(n.published_at) BETWEEN julianday(?)-1 AND julianday(?)
                AND (l.contract IS NULL OR s.document_id>coalesce(json_extract(l.payload,'$.last_enqueued_document_id'),0))
                AND s.document_id=(SELECT s2.document_id FROM story_documents s2
                    WHERE s2.news_id=s.news_id AND s2.available_at<=?
                    ORDER BY s2.document_id DESC LIMIT 1)
                GROUP BY c.contract ORDER BY min(s.document_id) LIMIT 250""",
                (now, at, at, now),
            ).fetchall()
        for row in rows:
            evidence = self.current(row["contract"], at)
            if evidence:
                with self.store.connect() as db:
                    existing = db.execute(
                        "SELECT * FROM story_pool_lookups WHERE contract=?", (row["contract"],)
                    ).fetchone()
                    payload = (
                        json.loads(existing["payload"])
                        if existing
                        else {"first_evidence": evidence}
                    )
                    prior = payload.get("latest_evidence", {})
                    changed = (
                        prior.get("news_id") != evidence["news_id"]
                        or prior.get("source_sha256") != evidence["source_sha256"]
                    )
                    payload.update(
                        last_enqueued_document_id=evidence["document_id"], latest_evidence=evidence
                    )
                    db.execute(
                        "INSERT INTO story_pool_lookups VALUES(?,?,?,0,'pending',?) ON CONFLICT(contract) DO UPDATE SET payload=excluded.payload,state=CASE WHEN ? THEN 'pending' ELSE story_pool_lookups.state END,next_due=CASE WHEN ? THEN excluded.next_due ELSE story_pool_lookups.next_due END",
                        (row["contract"], at, now, json.dumps(payload), changed, changed),
                    )

    def current(self, contract, at):
        evidence = self.stories.for_contract(contract, at)
        return next(
            (e for e in evidence if e["association"] == "exact_contract_document_mention"), None
        )

    def finish(self, contract, state, payload, *, attempts, delay=0):
        with self.store.connect() as db:
            db.execute(
                "UPDATE story_pool_lookups SET state=?,payload=?,attempts=?,next_due=? WHERE contract=?",
                (
                    state,
                    json.dumps(payload, allow_nan=False),
                    attempts,
                    time.time() + delay,
                    contract,
                ),
            )

    async def resolve(self, row):
        contract, at = row["contract"], utcnow()
        payload = json.loads(row["payload"])
        evidence = self.current(contract, at)
        payload.update(last_checked_at=at, current_evidence=evidence)
        if not evidence:
            # Keep the address and original evidence. Recheck without HTTP in
            # case a later document corrects an unavailable/contradictory source.
            state = (
                "evidence_expired"
                if epoch(at) - epoch(row["first_seen_at"]) > 86400
                else "evidence_unavailable"
            )
            self.finish(contract, state, payload, attempts=row["attempts"], delay=300)
            return
        with self.store.connect() as db:
            existing = db.execute(
                "SELECT id FROM opportunity_candidates WHERE chain='solana' AND contract=?",
                (contract,),
            ).fetchone()
        if existing:
            with self.store.connect() as db:
                db.execute(
                    "UPDATE opportunity_candidates SET next_due=min(next_due,?) WHERE id=? AND eligible=1",
                    (time.time(), existing[0]),
                )
            self.finish(
                contract,
                "existing_candidate",
                payload | {"candidate_id": existing[0]},
                attempts=row["attempts"],
            )
            return
        attempts = row["attempts"] + 1
        # Persistent lease/backoff also covers interrupted requests after restart.
        self.finish(contract, "lookup_in_progress", payload, attempts=attempts, delay=60)
        try:
            async with asyncio.timeout(8):
                result = await self.service.providers.market(contract)
            market = Market.model_validate(
                result.model_dump() if isinstance(result, Market) else result
            ).model_dump()
            solana_address(market["address"])
            solana_address(market["pair_address"])
            if (
                market["address"] != contract
                or not 0 <= time.time() - epoch(market["observed_at"]) <= 120
                or market["liquidity_usd"] <= 0
            ):
                raise ValueError("Incompatible market identity/freshness/liquidity")
            # A denial/removal may arrive while the market request is in flight.
            evidence = self.current(contract, utcnow())
            if not evidence:
                raise ValueError("Evidence no longer current")
            created = market.get("pool_created_at")
            created_at = (
                datetime.fromtimestamp(created / 1000, UTC).isoformat()
                if created and 0 < created / 1000 <= time.time()
                else None
            )
            self.service.discovery.save(
                {
                    "chain": "solana",
                    "pool": market["pair_address"],
                    "contract": contract,
                    "name": market["name"],
                    "price_usd": market["price_usd"],
                    "liquidity_usd": market["liquidity_usd"],
                    "observed_at": market["observed_at"],
                    "pool_created_at_reported": created_at,
                    "token_launched_at": None,
                    "indexed_at": None,
                    "discovery_basis": "exact_contract_news_mention_not_launch",
                    "source": market["source"],
                    "official_affiliation": "unverified",
                    "story_evidence": evidence,
                }
            )
            self.finish(
                contract,
                "resolved_pool",
                payload
                | {
                    "current_evidence": evidence,
                    "pool": market["pair_address"],
                    "resolved_at": utcnow(),
                },
                attempts=attempts,
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
            self.finish(
                contract,
                "market_unavailable",
                payload
                | {
                    "error": "No validated fresh base-token pool; lookup failed or data incompatible. This is not confirmed unsellability."
                },
                attempts=attempts,
                delay=min(3600, 300 * 2 ** min(attempts - 1, 4)),
            )

    async def cycle(self):
        at = utcnow()
        self.enqueue(at)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM story_pool_lookups WHERE state NOT IN ('resolved_pool','existing_candidate','evidence_expired') AND next_due<=? ORDER BY next_due,first_seen_at,contract LIMIT 3",
                (time.time(),),
            ).fetchall()
        await asyncio.gather(*(self.resolve(row) for row in rows))
        summary = self.summary()
        self.status = {
            "state": "partial"
            if summary["states"].get("market_unavailable")
            or summary["states"].get("evidence_unavailable")
            else "ok",
            "at": utcnow(),
            "attempted_jobs": len(rows),
            **summary,
            "error": "Unele contracte nu au piață sau dovezi curente verificabile; reîncercările sunt programate."
            if summary["states"].get("market_unavailable")
            or summary["states"].get("evidence_unavailable")
            else None,
        }
        return self.status

    def recent(self):
        with self.store.connect() as db:
            return [
                dict(row) | {"payload": json.loads(row["payload"])}
                for row in db.execute(
                    "SELECT l.*,c.id AS candidate_id FROM story_pool_lookups l LEFT JOIN opportunity_candidates c ON c.chain='solana' AND c.contract=l.contract ORDER BY l.first_seen_at DESC,l.contract LIMIT 20"
                )
            ]

    def summary(self):
        with self.store.connect() as db:
            states = dict(
                db.execute("SELECT state,count(*) FROM story_pool_lookups GROUP BY state")
            )
        return {
            "states": states,
            "tracked_contracts": sum(states.values()),
            "lookup_budget_per_cycle": 3,
            "timeout_seconds": 8,
            "note": "Exact document references only. Unknown pools and failed lookups remain recorded; they are not zero-loss trades or verified launches.",
        }
