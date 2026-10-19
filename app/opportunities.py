"""Persistent Solana discovery -> evidence -> decision -> outbox -> outcome workflow."""

import asyncio
import hashlib
import json
import logging
import os
import time
import uuid
from concurrent.futures import Future
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from app.credentials import secret
from app.errors import ProviderError
from app.models import Market, epoch, solana_address, utcnow
from app.narratives import Narratives
from app.notifications import telegram_receipt
from app.opportunity_routes import Routes
from app.opportunity_rules import RULE_VERSION, EngineConfig, evaluate, features
from app.opportunity_sampling import SAMPLING_VERSION, Sampling
from app.opportunity_sources import (
    fallback_pool,
    gecko_markets,
    monitored_wallets,
    pool_activity,
    pool_markets,
)
from app.story_discovery import StoryDiscovery

log = logging.getLogger(__name__)
ENGINE_SOURCE_SHA256 = hashlib.sha256(
    b"".join(
        Path(__file__).with_name(name).read_bytes()
        for name in (
            "opportunities.py",
            "opportunity_rules.py",
            "opportunity_sources.py",
            "narratives.py",
            "story_evidence.py",
            "story_discovery.py",
            "story_markets.py",
            "announcements.py",
            "news.py",
            "opportunity_outcomes.py",
            "opportunity_sampling.py",
            "opportunity_routes.py",
            "analysis.py",
            "paper.py",
            "models.py",
        )
    )
).hexdigest()
PAPER_SOURCE_SHA256 = hashlib.sha256(Path(__file__).with_name("paper.py").read_bytes()).hexdigest()
QUOTE_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


class Opportunities:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.owner = uuid.uuid4().hex
        self.lock = asyncio.Lock()
        self._report_lock = Lock()
        self._report_future = None
        self.narratives = Narratives(service)
        self.story_discovery = StoryDiscovery(service, self.narratives.stories)
        self.ai_task = None
        self.wallet_task = None
        self.route_task = None
        with self.store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS opportunity_config(id INTEGER PRIMARY KEY CHECK(id=1),at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS opportunity_policies(id INTEGER PRIMARY KEY,sha256 TEXT UNIQUE NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS opportunity_runtime(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS opportunity_lease(id INTEGER PRIMARY KEY CHECK(id=1),owner TEXT NOT NULL,expires_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS opportunity_candidates(id INTEGER PRIMARY KEY,chain TEXT NOT NULL,contract TEXT NOT NULL,pool TEXT NOT NULL,discovered_at TEXT NOT NULL,ingested_at TEXT NOT NULL,discovery TEXT NOT NULL,eligible INTEGER NOT NULL,exclusion_reason TEXT,next_due REAL NOT NULL,last_attempt_at TEXT,failures INTEGER NOT NULL DEFAULT 0,UNIQUE(chain,contract));
                CREATE TABLE IF NOT EXISTS opportunity_observations(id INTEGER PRIMARY KEY,candidate_id INTEGER NOT NULL,at TEXT NOT NULL,status TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS opportunity_observation_subject ON opportunity_observations(candidate_id,id DESC);
                CREATE INDEX IF NOT EXISTS opportunity_observation_time ON opportunity_observations(candidate_id,at,id);
                CREATE TABLE IF NOT EXISTS opportunity_signals(id INTEGER PRIMARY KEY,candidate_id INTEGER NOT NULL,observation_id INTEGER,at TEXT NOT NULL,kind TEXT NOT NULL,verdict TEXT NOT NULL,policy_id INTEGER NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS opportunity_signal_subject ON opportunity_signals(candidate_id,id);
                CREATE TABLE IF NOT EXISTS opportunity_alerts(id INTEGER PRIMARY KEY,candidate_id INTEGER NOT NULL,signal_id INTEGER UNIQUE NOT NULL,at TEXT NOT NULL,severity TEXT NOT NULL,fingerprint TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,delivered_in_app_at TEXT,seen_at TEXT,telegram_state TEXT NOT NULL DEFAULT 'pending',telegram_details TEXT);
                CREATE TABLE IF NOT EXISTS opportunity_outcomes(signal_id INTEGER NOT NULL,horizon_seconds INTEGER NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(signal_id,horizon_seconds));
            """)
            row = db.execute("SELECT payload FROM opportunity_runtime WHERE id=1").fetchone()
            self.status = (
                json.loads(row[0]) if row else {"state": "unverified", "at": None, "cycles": 0}
            )
            if not db.execute("SELECT 1 FROM opportunity_config").fetchone():
                config = EngineConfig(
                    enabled=os.getenv("OPPORTUNITY_ENGINE_ENABLED", "1") != "0",
                    interval_seconds=int(os.getenv("OPPORTUNITY_INTERVAL_SECONDS", "60")),
                    security_budget=int(os.getenv("OPPORTUNITY_SECURITY_BUDGET", "8")),
                    activity_samples=int(os.getenv("OPPORTUNITY_ACTIVITY_SAMPLES", "0")),
                    ai_narratives=os.getenv("OPPORTUNITY_AI_NARRATIVES") == "1",
                    telegram_enabled=os.getenv("OPPORTUNITY_TELEGRAM_ENABLED") == "1",
                    routed_quotes_enabled=os.getenv("OPPORTUNITY_ROUTED_QUOTES", "1") != "0",
                    test_from=os.getenv("OPPORTUNITY_TEST_FROM") or None,
                ).validated()
                db.execute(
                    "INSERT INTO opportunity_config VALUES(1,?,?)",
                    (utcnow(), config.model_dump_json()),
                )
        self.sampling = Sampling(self)
        self.routes = Routes(self)

    def config(self):
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM opportunity_config WHERE id=1").fetchone()
        return EngineConfig.model_validate_json(row[0]).validated()

    def configure(self, body):
        body.validated()
        old = self.config()
        if (
            body.test_from
            and body.test_from != old.test_from
            and body.test_from.timestamp() < time.time()
        ):
            raise ValueError(
                "A test split must be declared before its future observations, not selected retrospectively."
            )
        with self.store.connect() as db:
            db.execute(
                "UPDATE opportunity_config SET at=?,payload=? WHERE id=1",
                (utcnow(), body.model_dump_json()),
            )
        return self.config().model_dump(mode="json")

    def policy(self, config):
        payload = {
            "rule_version": RULE_VERSION,
            "config": config.model_dump(mode="json"),
            "paper_rules": self.service.frozen_rules(),
            "source_sha256": ENGINE_SOURCE_SHA256,
            "paper_source_sha256": PAPER_SOURCE_SHA256,
            "sampling_version": SAMPLING_VERSION,
            "forward_quote_window_version": 2,
            "routed_policy": self.routes.policy(config),
            "observation_rules": {
                k: getattr(self.service.settings, k)
                for k in ("min_signal_delay", "max_snapshot_age")
            },
        }
        fingerprint = hashlib.sha256(encode(payload).encode()).hexdigest()
        with self.store.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO opportunity_policies(sha256,at,payload) VALUES(?,?,?)",
                (fingerprint, utcnow(), encode(payload)),
            )
            row = db.execute(
                "SELECT * FROM opportunity_policies WHERE sha256=?", (fingerprint,)
            ).fetchone()
        return dict(row) | {"payload": payload}

    def acquire(self):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT owner,expires_at FROM opportunity_lease WHERE id=1").fetchone()
            if row and row["expires_at"] > time.time() and row["owner"] != self.owner:
                return False
            db.execute(
                "INSERT OR REPLACE INTO opportunity_lease VALUES(1,?,?)",
                (self.owner, time.time() + 600),
            )
        return True

    def release(self):
        with self.store.connect() as db:
            db.execute("DELETE FROM opportunity_lease WHERE id=1 AND owner=?", (self.owner,))

    def ingest(self, policy):
        now = utcnow()
        added = 0
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM discovered_pools p WHERE chain='solana' AND NOT EXISTS(SELECT 1 FROM opportunity_candidates c WHERE c.chain=p.chain AND c.contract=p.contract) ORDER BY first_seen_at,pool"
            ).fetchall()
            for row in rows:
                try:
                    solana_address(row["contract"])
                    solana_address(row["pool"])
                except (TypeError, ValueError):
                    continue
                first = json.loads(row["first_payload"]) if row["first_payload"] else None
                source = first or json.loads(row["payload"])
                discovery = source | {
                    "first_capture_available": first is not None,
                    "source_first_seen_at": row["first_seen_at"],
                    "imported_from_cache": first is None,
                }
                if first is None:
                    discovery.update(price_usd=None, liquidity_usd=None)
                reason = (
                    "known_quote_or_infrastructure_asset"
                    if row["contract"] in QUOTE_MINTS
                    else None
                )
                result = db.execute(
                    "INSERT OR IGNORE INTO opportunity_candidates(chain,contract,pool,discovered_at,ingested_at,discovery,eligible,exclusion_reason,next_due) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        row["chain"],
                        row["contract"],
                        row["pool"],
                        row["first_seen_at"],
                        now,
                        encode(discovery),
                        int(reason is None),
                        reason,
                        time.time(),
                    ),
                )
                if not result.rowcount:
                    continue
                candidate_id = result.lastrowid
                self.sampling.enroll(db, candidate_id, row["contract"], now)
                added += 1
                payload = {
                    "verdict": "REJECT" if reason else "MONITOR",
                    "scores": {},
                    "positive": [],
                    "negative": [reason] if reason else [],
                    "unknown": ["Discovery metadata only; enrichment has not yet completed."],
                    "discovery": discovery,
                    "decision_at": now,
                    "no_future_data": True,
                }
                discovery_signal = db.execute(
                    "INSERT INTO opportunity_signals(candidate_id,at,kind,verdict,policy_id,payload) VALUES(?,?,?,?,?,?)",
                    (
                        candidate_id,
                        now,
                        "discovery",
                        payload["verdict"],
                        policy["id"],
                        encode(payload),
                    ),
                )
                if reason is None and self.sampling.enrolled_control(db, candidate_id):
                    for h in policy["payload"]["config"]["horizons_seconds"]:
                        target = epoch(row["first_seen_at"]) + h
                        self.sampling.job(
                            db,
                            candidate_id,
                            discovery_signal.lastrowid,
                            "checkpoint",
                            h,
                            target,
                            target + policy["payload"]["config"]["exit_window_seconds"],
                            control=True,
                        )
        return added

    def history(self, candidate_id, before=None, limit=1000):
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM opportunity_observations WHERE candidate_id=? ORDER BY id DESC LIMIT ?",
                (candidate_id, limit),
            ).fetchall()
        return [
            dict(r) | json.loads(r["payload"])
            for r in reversed(rows)
            if before is None or epoch(r["at"]) <= epoch(before)
        ]

    def due(self, config):
        return self.sampling.choose(config)

    def save_observation(self, candidate, payload, policy, config, at=None):
        at = at or utcnow()
        decision = payload.get("decision")
        state = "ok" if payload.get("market") else "unavailable"
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "INSERT INTO opportunity_observations(candidate_id,at,status,payload) VALUES(?,?,?,?)",
                (candidate["id"], at, state, encode(payload)),
            )
            observation_id = row.lastrowid
            self.sampling.record(db, candidate["id"], observation_id, payload, at)
            delay = config.interval_seconds
            if state != "ok":
                delay = min(900, delay * 2 ** min(candidate.get("failures", 0) + 1, 4))
            elif decision["verdict"] == "REJECT":
                delay = max(delay, 300)
            if epoch(at) - epoch(candidate["ingested_at"]) >= config.active_watch_seconds:
                delay = max(delay, config.background_interval_seconds)
            db.execute(
                "UPDATE opportunity_candidates SET last_attempt_at=?,next_due=?,failures=? WHERE id=?",
                (
                    at,
                    epoch(at) + delay,
                    0 if state == "ok" else candidate.get("failures", 0) + 1,
                    candidate["id"],
                ),
            )
            if not decision:
                return observation_id, None
            previous = db.execute(
                "SELECT * FROM opportunity_signals WHERE candidate_id=? AND kind!='discovery' ORDER BY id DESC LIMIT 1",
                (candidate["id"],),
            ).fetchone()
            create = (
                not previous
                or previous["verdict"] != decision["verdict"]
                or previous["policy_id"] != policy["id"]
            )
            signal_id = None
            if create:
                signal_id = self._signal(
                    db,
                    candidate["id"],
                    observation_id,
                    at,
                    "baseline" if not previous else "decision_change",
                    decision,
                    policy,
                    config,
                )
            last = db.execute(
                "SELECT * FROM opportunity_alerts WHERE candidate_id=? ORDER BY id DESC LIMIT 1",
                (candidate["id"],),
            ).fetchone()
            meaningful = last is None
            upgrade = False
            if last:
                old = json.loads(last["payload"])
                upgrade = decision["verdict"] == "CONSIDER" and old["verdict"] != "CONSIDER"
                meaningful = (
                    upgrade
                    or (decision.get("rank_score") or 0) >= (old.get("rank_score") or 0) + 10
                )
            risk_update = bool(
                last
                and last["severity"] != "critical"
                and decision["verdict"] == "REJECT"
                and (
                    decision["screening"]["critical"]
                    or any(f["severity"] == "high" for f in payload["features"]["suspicions"])
                )
            )
            if risk_update or (
                decision["verdict"] in config.alert_verdicts
                and meaningful
                and (
                    not last or epoch(at) - epoch(last["at"]) >= config.cooldown_seconds or upgrade
                )
            ):
                if signal_id is None:
                    signal_id = self._signal(
                        db, candidate["id"], observation_id, at, "alert", decision, policy, config
                    )
                alert = self.alert_payload(candidate, payload, at, signal_id)
                alert["alert_kind"] = "risk_update" if risk_update else "opportunity"
                fingerprint = hashlib.sha256(
                    f"{candidate['id']}:{policy['id']}:{decision['verdict']}:{int(epoch(at) // config.cooldown_seconds)}".encode()
                ).hexdigest()
                db.execute(
                    "INSERT OR IGNORE INTO opportunity_alerts(candidate_id,signal_id,at,severity,fingerprint,payload) VALUES(?,?,?,?,?,?)",
                    (
                        candidate["id"],
                        signal_id,
                        at,
                        "critical"
                        if risk_update
                        else "high"
                        if decision["verdict"] == "CONSIDER"
                        else "research",
                        fingerprint,
                        encode(alert),
                    ),
                )
                if not risk_update:
                    db.execute(
                        "UPDATE observation_jobs SET selected=1 WHERE signal_id=?", (signal_id,)
                    )
                    db.execute(
                        "UPDATE routed_experiments SET selected=1 WHERE signal_id=?", (signal_id,)
                    )
        return observation_id, signal_id

    def _signal(self, db, candidate_id, observation_id, at, kind, decision, policy, config):
        payload = decision | {"policy": policy, "decision_at": at, "no_future_data": True}
        row = db.execute(
            "INSERT INTO opportunity_signals(candidate_id,observation_id,at,kind,verdict,policy_id,payload) VALUES(?,?,?,?,?,?,?)",
            (
                candidate_id,
                observation_id,
                at,
                kind,
                decision["verdict"],
                policy["id"],
                encode(payload),
            ),
        )
        for h in config.horizons_seconds:
            db.execute(
                "INSERT INTO opportunity_outcomes VALUES(?,?,?,?,?)",
                (
                    row.lastrowid,
                    h,
                    "pending",
                    encode({"pnl_usd": None, "execution_verified": False}),
                    utcnow(),
                ),
            )
        e = db.execute(
            "SELECT control_member FROM sampling_enrollment WHERE candidate_id=?", (candidate_id,)
        ).fetchone()
        self.sampling.job(
            db,
            candidate_id,
            row.lastrowid,
            "entry",
            0,
            epoch(at) + self.service.settings.min_signal_delay,
            epoch(at) + config.entry_window_seconds,
            control=bool(e and e[0] and kind == "baseline"),
        )
        self.routes.enroll(db, candidate_id, row.lastrowid, at, kind, decision, policy)
        return row.lastrowid

    @staticmethod
    def alert_payload(candidate, payload, at, signal_id):
        m = payload["market"]
        d = payload["decision"]
        return {
            "signal_id": signal_id,
            "name": m["name"],
            "symbol": m["symbol"],
            "contract": candidate["contract"],
            "chain": candidate["chain"],
            "discovered_at": candidate["discovered_at"],
            "data_observed_at": m["observed_at"],
            "decision_at": at,
            "price_usd": m["price_usd"],
            "liquidity_usd": m["liquidity_usd"],
            "verdict": d["verdict"],
            "rank_score": d["rank_score"],
            "scores": d["scores"],
            "positive": d["positive"],
            "negative": d["negative"],
            "unknown": d["unknown"],
            "invalidation": d["invalidation"],
            "features": payload["features"],
            "costs": d["costs"],
            "narrative": payload["narrative"],
            "links": {
                "explorer": "https://solscan.io/token/" + candidate["contract"],
                "market": "https://dexscreener.com/solana/" + candidate["pool"],
            },
            "live_execution": False,
            "purpose": "research_candidate_not_buy_instruction",
        }

    async def cycle(self, refresh_discovery=True):
        if self.lock.locked():
            return {"state": "busy"}
        async with self.lock:
            if not self.acquire():
                return {"state": "busy_other_process"}
            errors = []
            observed = 0
            started = utcnow()
            config = self.config()
            try:
                if not config.enabled:
                    self.status = {
                        "state": "disabled",
                        "at": utcnow(),
                        "cycles": self.status.get("cycles", 0),
                    }
                    return self.status
                policy = self.policy(config)
                self.narratives.stories.index_documents()
                await self.story_discovery.cycle()
                self.status = {**self.status, "state": "running", "started_at": started}
                page = (self.status.get("cycles", 0) % config.discovery_pages) + 1
                if refresh_discovery:
                    try:
                        await asyncio.wait_for(self.service.discovery.refresh("solana", page), 60)
                    except (ProviderError, TimeoutError, ValueError):
                        errors.append("discovery_temporarily_unavailable")
                    try:
                        await asyncio.wait_for(self.service.discovery.boosts(), 25)
                    except (ProviderError, TimeoutError, ValueError, TypeError):
                        errors.append("paid_exposure_feed_unavailable")
                        self.service.discovery.status["boosts"] = {
                            "state": "error",
                            "at": utcnow(),
                            "error": "Paid-exposure source unavailable.",
                        }
                    if any(
                        s.get("state") in {"error", "partial"}
                        for s in self.service.discovery.status.values()
                    ):
                        errors.append("discovery_source_incomplete")
                added = self.ingest(policy)
                due = self.due(config)
                self.sampling.dispatch(due)
                markets = {}
                for i in range(0, len(due), 30):
                    try:
                        markets.update(
                            await asyncio.wait_for(
                                pool_markets(self.service.providers, due[i : i + 30]), 35
                            )
                        )
                    except (ProviderError, TimeoutError, ValueError, TypeError, AttributeError):
                        errors.append("batch_pool_quotes_unavailable")
                # Prefer a single anchored-pool source with reported buyer/seller counts where available.
                try:
                    if due:
                        markets.update(
                            await asyncio.wait_for(gecko_markets(self.service.discovery, due), 25)
                        )
                except (ProviderError, TimeoutError, ValueError, TypeError, KeyError):
                    errors.append("gecko_participation_unavailable")
                security_left = config.security_budget
                fallback_left = 3
                activity_left = 1
                for candidate in due:
                    with self.store.connect() as db:
                        renewed = db.execute(
                            "UPDATE opportunity_lease SET expires_at=? WHERE id=1 AND owner=?",
                            (time.time() + 600, self.owner),
                        ).rowcount
                    if not renewed:
                        raise ProviderError(
                            "Opportunity worker lease expired; another process owns collection."
                        )
                    try:
                        market = markets.get((candidate["pool"], candidate["contract"]))
                        if not market and fallback_left:
                            fallback_left -= 1
                            try:
                                market = await asyncio.wait_for(
                                    fallback_pool(self.service.discovery, candidate), 15
                                )
                            except (ProviderError, TimeoutError, ValueError, KeyError, TypeError):
                                pass
                        if not market:
                            errors.append("anchored_pool_observation_missing")
                            self.save_observation(
                                candidate,
                                {
                                    "market": None,
                                    "error": "Anchored pool quote unavailable; disappearance, outage and unsellability are not interchangeable.",
                                },
                                policy,
                                config,
                            )
                            continue
                        history = self.history(candidate["id"])
                        previous = next(
                            (
                                h
                                for h in reversed(history)
                                if h.get("security")
                                and h["security"].get("rpc")
                                and h["security"].get("goplus")
                            ),
                            None,
                        )
                        security = (previous or {}).get("security")
                        if (
                            not security
                            or not 0
                            <= time.time() - epoch(security["observed_at"])
                            <= self.service.settings.max_snapshot_age
                        ):
                            security = None
                            if security_left and market["liquidity_usd"] >= float(
                                self.service.settings.min_liquidity
                            ):
                                security_left -= 1
                                try:
                                    security = await asyncio.wait_for(
                                        self.service.providers.security(candidate["contract"]), 30
                                    )
                                except (ProviderError, TimeoutError):
                                    security = None
                            if not security:
                                security = {
                                    "rpc": None,
                                    "goplus": None,
                                    "observed_at": utcnow(),
                                    "errors": [
                                        "Security budget/provider unavailable; screening unknown."
                                    ],
                                }
                        if market["liquidity_usd"] >= float(
                            self.service.settings.min_liquidity
                        ) and (not security.get("rpc") or not security.get("goplus")):
                            errors.append("security_evidence_missing_or_deferred")
                        activity = None
                        distribution = None
                        if config.activity_samples and activity_left:
                            activity_left -= 1
                            try:
                                activity = await asyncio.wait_for(
                                    pool_activity(
                                        self.service.onchain, candidate, config.activity_samples
                                    ),
                                    25,
                                )
                            except (ProviderError, TimeoutError, ValueError, KeyError):
                                errors.append("sampled_activity_unavailable")
                            try:
                                distribution = await asyncio.wait_for(
                                    self.service.onchain.token("solana", candidate["contract"]), 20
                                )
                            except (ProviderError, TimeoutError):
                                errors.append("distribution_unavailable")
                        at = utcnow()
                        f = features(
                            market,
                            history,
                            candidate["discovery"],
                            at,
                            config,
                            activity,
                            distribution,
                        )
                        promotion = candidate["discovery"].get("promotion")
                        if not promotion:
                            with self.store.connect() as db:
                                promoted = db.execute(
                                    "SELECT payload FROM discovered_pools WHERE chain='solana' AND contract=? AND json_extract(payload,'$.promotion') IS NOT NULL ORDER BY last_seen_at DESC LIMIT 1",
                                    (candidate["contract"],),
                                ).fetchone()
                            promotion = (
                                json.loads(promoted[0]).get("promotion") if promoted else None
                            )
                        if promotion:
                            f["suspicions"].append(
                                {
                                    "kind": "paid_boost_reported",
                                    "severity": "medium",
                                    "origin": "provider_reported_promotion",
                                    "evidence": promotion,
                                    "note": "Paid exposure is not proof of manipulation or organic social demand.",
                                }
                            )
                        narrative = self.narratives.evidence(candidate["contract"], at)
                        wallet = monitored_wallets(self.service.wallets, candidate["contract"], at)
                        decision = evaluate(
                            market,
                            security,
                            f,
                            narrative,
                            wallet,
                            self.service.settings,
                            config,
                            at,
                        )
                        payload = {
                            "market": market,
                            "security": security,
                            "features": f,
                            "narrative": narrative,
                            "wallet": wallet,
                            "decision": decision,
                            "policy_id": policy["id"],
                            "source_kind": "live_provider_observation",
                            "execution_verified": False,
                            "collection_lane": candidate.get("collection_lane"),
                        }
                        self.save_observation(candidate, payload, policy, config, at)
                        observed += 1
                        self.service.store.add_token(candidate["contract"], "opportunity_engine")
                        # Reuse real observations in existing research and manual paper screens.
                        self.service.store.save_snapshot(
                            Market(**market),
                            security,
                            decision["screening"],
                        )
                        if (
                            config.ai_narratives
                            and narrative["supported"]
                            and not narrative.get("ai_interpretations")
                            and (self.ai_task is None or self.ai_task.done())
                        ):
                            self.ai_task = asyncio.create_task(
                                self.classify(candidate["contract"], narrative, config)
                            )
                    except (
                        ProviderError,
                        ValueError,
                        TypeError,
                        KeyError,
                        AttributeError,
                        ArithmeticError,
                        TimeoutError,
                    ) as exc:
                        log.warning("Opportunity candidate error: %s", type(exc).__name__)
                        self.save_observation(
                            candidate,
                            {
                                "market": None,
                                "error": "Incomplete provider evidence; candidate retained.",
                            },
                            policy,
                            config,
                        )
                        errors.append("candidate_evidence_error")
                self.update_outcomes()
                if self.route_task is None or self.route_task.done():
                    self.route_task = asyncio.create_task(self.routes.cycle())
                self.service.notifications.collect()
                if self.wallet_task is None or self.wallet_task.done():
                    self.wallet_task = asyncio.create_task(self.refresh_wallet())
                if config.ai_narratives and (self.ai_task is None or self.ai_task.done()):
                    self.ai_task = asyncio.create_task(self.refresh_narratives(config))
                await self.deliver_telegram(config)
                self.status = {
                    "state": "partial" if errors else "ok",
                    "at": utcnow(),
                    "started_at": started,
                    "cycles": self.status.get("cycles", 0) + 1,
                    "new_candidates": added,
                    "observed": observed,
                    "errors": sorted(set(errors)),
                    "discovery_sources": self.service.discovery.status,
                    "queue": self.queue_health(),
                    "collection": self.sampling.coverage(),
                    "routed_quotes": self.routes.status,
                }
                with self.store.connect() as db:
                    db.execute(
                        "INSERT OR REPLACE INTO opportunity_runtime VALUES(1,?)",
                        (encode(self.status),),
                    )
                return self.status
            finally:
                self.release()

    async def classify(self, contract, evidence, config):
        try:
            await self.narratives.classify(contract, evidence, config)
        except (ProviderError, ValueError, TypeError):
            log.warning("Narrative AI unavailable; original evidence retained.")

    async def refresh_narratives(self, config):
        try:
            await self.narratives.refresh_trends(config)
        except (ProviderError, ValueError, TypeError):
            log.warning("Narrative classification unavailable; no synthetic result substituted.")

    async def refresh_wallet(self):
        wallets = [w for w in self.service.wallets.listing() if w["chain"] == "solana"]
        if not wallets:
            return
        wallet = min(wallets, key=lambda w: w["status"].get("at") or "")
        try:
            await asyncio.wait_for(self.service.wallets.refresh(wallet["id"]), 30)
        except (ProviderError, TimeoutError, ValueError):
            log.warning("Monitored wallet observation unavailable; existing evidence retained.")

    def queue_health(self):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT count(*) AS due,min(next_due) AS oldest FROM opportunity_candidates WHERE eligible=1 AND next_due<=?",
                (time.time(),),
            ).fetchone()
            pending = db.execute(
                "SELECT count(*) FROM opportunity_candidates WHERE eligible=1 AND last_attempt_at IS NULL"
            ).fetchone()[0]
        return {
            "due": row["due"],
            "not_enriched": pending,
            "oldest_due_delay_seconds": round(max(0, time.time() - (row["oldest"] or time.time()))),
            "capacity_note": "Bounded API budget; queue delays can invalidate forward entry/exit windows. Missing observations remain unknown.",
        }

    async def close(self):
        if self.route_task and not self.route_task.done():
            self.route_task.cancel()
            try:
                await self.route_task
            except asyncio.CancelledError:
                pass
        if self.wallet_task and not self.wallet_task.done():
            self.wallet_task.cancel()
            try:
                await self.wallet_task
            except asyncio.CancelledError:
                pass
        if self.ai_task and not self.ai_task.done():
            self.ai_task.cancel()
            try:
                await self.ai_task
            except asyncio.CancelledError:
                pass
        self.release()

    async def run(self):
        while True:
            cycle_started = time.monotonic()
            try:
                await self.cycle()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.status = {
                    "state": "error",
                    "at": utcnow(),
                    "error": type(exc).__name__,
                    "cycles": self.status.get("cycles", 0),
                }
                log.error("Opportunity cycle failed: %s", type(exc).__name__)
            await asyncio.sleep(
                max(1, self.config().interval_seconds - (time.monotonic() - cycle_started))
            )

    def alerts(self, limit=100, before=None, pending_only=False):
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM opportunity_alerts WHERE (? IS NULL OR id<?) AND (?=0 OR telegram_state='pending') ORDER BY id "
                + ("ASC" if pending_only else "DESC")
                + " LIMIT ?",
                (before, before, int(pending_only), limit),
            ).fetchall()
        return [
            dict(r)
            | {
                "payload": json.loads(r["payload"]),
                "telegram_details": json.loads(r["telegram_details"])
                if r["telegram_details"]
                else None,
            }
            for r in rows
        ]

    def receipt(self, alert_id, seen=False):
        with self.store.connect() as db:
            db.execute(
                "UPDATE opportunity_alerts SET delivered_in_app_at=coalesce(delivered_in_app_at,?) WHERE id=?",
                (utcnow(), alert_id),
            )
            if seen:
                db.execute(
                    "UPDATE opportunity_alerts SET seen_at=coalesce(seen_at,?) WHERE id=?",
                    (utcnow(), alert_id),
                )
            row = db.execute(
                "SELECT id,delivered_in_app_at,seen_at FROM opportunity_alerts WHERE id=?",
                (alert_id,),
            ).fetchone()
        if not row:
            raise ValueError("Unknown opportunity alert.")
        return dict(row)

    async def deliver_telegram(self, config):
        if not config.telegram_enabled:
            return
        if not secret("TELEGRAM_BOT_TOKEN") or not secret("TELEGRAM_CHAT_ID"):
            return
        for alert in self.alerts(1, pending_only=True):
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                changed = db.execute(
                    "UPDATE opportunity_alerts SET telegram_state='sending' WHERE id=? AND telegram_state='pending'",
                    (alert["id"],),
                ).rowcount
            if not changed:
                continue
            p = alert["payload"]
            state = "delivery_unknown"
            details = {}
            text = (
                f"MemeScope {p['verdict']} | {p['symbol']}\nSolana {p['contract']}\nPrice ${p['price_usd']:.12g} | liquidity ${p['liquidity_usd']:,.0f}\nObserved: {p['data_observed_at']}\n"
                + "\n".join(p["positive"][:2])
                + f"\nRisks/unknowns: {'; '.join((p['negative'] + p['unknown'])[:3])}\nPaper costs: {p['costs'].get('roundtrip_cost_pct', 'unknown')}% estimated round trip\n{p['links']['market']}\nResearch only; no real transaction. Full evidence in the application."
            )
            try:
                result = await asyncio.wait_for(
                    self.service.notifications.telegram(
                        "sendMessage",
                        {
                            "chat_id": secret("TELEGRAM_CHAT_ID"),
                            "text": text[:4000],
                            "disable_web_page_preview": True,
                        },
                    ),
                    20,
                )
                message_id = telegram_receipt(result, secret("TELEGRAM_CHAT_ID"))
                state = "acknowledged_by_api"
                details = {
                    "message_id": message_id,
                    "acknowledged_at": utcnow(),
                    "read_by_user": False,
                }
            except (ProviderError, TimeoutError, AttributeError):
                details = {
                    "error": "Delivery uncertain; automatic retry disabled to prevent duplicates."
                }
            with self.store.connect() as db:
                db.execute(
                    "UPDATE opportunity_alerts SET telegram_state=?,telegram_details=? WHERE id=?",
                    (state, encode(details), alert["id"]),
                )
            break

    def update_outcomes(self, now=None):
        from app.opportunity_outcomes import update_outcomes

        return update_outcomes(self, now)

    def report(self):
        from app.opportunity_outcomes import report

        # Concurrent browser refreshes share the same in-flight read. Once it
        # finishes, the next request computes fresh data; no historical cache.
        with self._report_lock:
            pending = self._report_future
            owner = pending is None
            if owner:
                pending = self._report_future = Future()
        if not owner:
            return deepcopy(pending.result())
        try:
            result = report(self)
            pending.set_result(deepcopy(result))
            return result
        except BaseException as error:
            pending.set_exception(error)
            raise
        finally:
            with self._report_lock:
                self._report_future = None

    def listing(self, limit=50, before=None, ranked=False, query="", verdict="all"):
        now = time.time()
        with self.store.connect() as db:
            db.create_function(
                "casefold", 1, lambda value: str(value or "").casefold(), deterministic=True
            )
            base = """
                FROM opportunity_candidates c LEFT JOIN opportunity_observations o
                ON o.id=(SELECT id FROM opportunity_observations WHERE candidate_id=c.id ORDER BY id DESC LIMIT 1)
                WHERE (:verdict='all' OR coalesce(json_extract(o.payload,'$.decision.verdict'),'PENDING')=:verdict)
                AND (:q='' OR instr(casefold(c.contract || ' ' ||
                    coalesce(json_extract(c.discovery,'$.name'),'') || ' ' ||
                    coalesce(json_extract(o.payload,'$.market.name'),'') || ' ' ||
                    coalesce(json_extract(o.payload,'$.market.symbol'),'')),:q)>0)
            """
            params = {
                "q": query.strip().casefold(),
                "verdict": verdict,
                "before": before,
                "limit": limit + 1,
                "now": datetime.fromtimestamp(now, UTC).isoformat(),
                "fresh_from": datetime.fromtimestamp(
                    now - self.service.settings.max_snapshot_age, UTC
                ).isoformat(),
            }
            order = (
                "coalesce(CASE WHEN julianday(json_extract(o.payload,'$.market.observed_at')) BETWEEN julianday(:fresh_from) AND julianday(:now) AND julianday(json_extract(o.payload,'$.security.observed_at')) BETWEEN julianday(:fresh_from) AND julianday(:now) THEN json_extract(o.payload,'$.decision.rank_score') END,-1) DESC,c.id DESC"
                if ranked
                else "c.id DESC"
            )
            matching_total = db.execute("SELECT count(*) " + base, params).fetchone()[0]
            rows = db.execute(
                "SELECT c.* "
                + base
                + " AND (:before IS NULL OR c.id<:before) ORDER BY "
                + order
                + " LIMIT :limit",
                params,
            ).fetchall()
            items = []
            for r in rows[:limit]:
                latest = db.execute(
                    "SELECT * FROM opportunity_observations WHERE candidate_id=? ORDER BY id DESC LIMIT 1",
                    (r["id"],),
                ).fetchone()
                initial = db.execute(
                    "SELECT * FROM opportunity_signals WHERE candidate_id=? AND kind='baseline' ORDER BY id LIMIT 1",
                    (r["id"],),
                ).fetchone()
                last = json.loads(latest["payload"]) if latest else None
                market = (last or {}).get("market")
                items.append(
                    dict(r)
                    | {
                        "discovery": json.loads(r["discovery"]),
                        "latest": last,
                        "latest_at": latest["at"] if latest else None,
                        "initial_signal": dict(initial)
                        | {"payload": json.loads(initial["payload"])}
                        if initial
                        else None,
                        "fresh": bool(
                            market
                            and 0
                            <= now - epoch(market["observed_at"])
                            <= self.service.settings.max_snapshot_age
                            and (last or {}).get("security")
                            and 0
                            <= now - epoch(last["security"]["observed_at"])
                            <= self.service.settings.max_snapshot_age
                        ),
                    }
                )
        return {
            "items": items,
            "matching_total": matching_total,
            "ranking_limited": ranked and len(rows) > limit,
            "next_cursor": rows[limit - 1]["id"] if len(rows) > limit and not ranked else None,
            "status": self.status,
            "config": self.config().model_dump(mode="json"),
            "coverage": "Solana provider pool/profile/paid-exposure feeds; not all launches, and meme classification is unverified. Base is discovery-only in Level 3.",
            "live_execution": False,
        }

    def detail(self, candidate_id):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT * FROM opportunity_candidates WHERE id=?", (candidate_id,)
            ).fetchone()
            if not row:
                raise ValueError("Unknown candidate.")
            signals = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT * FROM opportunity_signals WHERE candidate_id=? ORDER BY id",
                    (candidate_id,),
                )
            ]
            outcomes = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT o.* FROM opportunity_outcomes o JOIN opportunity_signals s ON s.id=o.signal_id WHERE s.candidate_id=? ORDER BY s.id,o.horizon_seconds",
                    (candidate_id,),
                )
            ]
            count = db.execute(
                "SELECT count(*) FROM opportunity_observations WHERE candidate_id=?",
                (candidate_id,),
            ).fetchone()[0]
        return dict(row) | {
            "discovery": json.loads(row["discovery"]),
            "signals": signals,
            "observations": self.history(candidate_id),
            "observations_total": count,
            "history_truncated": count > 1000,
            "outcomes": outcomes,
            "live_execution": False,
            "sampling_enrollment": self.sampling.enrollment(candidate_id),
            "routed": self.routes.detail(candidate_id),
            "current_narrative": self.narratives.evidence(row["contract"], utcnow()),
        }
