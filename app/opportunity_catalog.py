"""Rebuildable UI projections; original research and financial rules stay untouched.

Native SQLite triggers only enqueue changed subjects. JSON decoding happens in
bounded refresh transactions, never in the collector's write triggers.
"""

import asyncio
import json
import time
from datetime import UTC, datetime
from threading import Lock

from app import opportunity_lifecycle as lifecycle
from app.models import epoch, solana_address
from app.providers import ProviderError

VERSION = 1
OBS = "CASE WHEN typeof(o.payload)='blob' THEN archive_text(o.payload) ELSE o.payload END"
CURRENT = "'$.market.price_usd','$.market.observed_at','$.security.observed_at','$.decision.verdict','$.decision.security_filter_passed','$.decision.liquidity_filter_passed'"
BASELINE = "'$.features.changes.5m.volume_5m_ratio','$.features.excessive_extension','$.narrative.supported','$.decision.security_filter_passed','$.decision.liquidity_filter_passed','$.decision.verdict'"


def available(db):
    if db.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN ('ui_catalog_state','ui_catalog_dirty','ui_catalog_candidates','ui_catalog_baselines')").fetchone()[0] != 4:
        return False
    row = db.execute("SELECT version FROM ui_catalog_state WHERE id=1").fetchone()
    return bool(row and row[0] == VERSION)


def ready(db):
    return available(db) and not db.execute("SELECT 1 FROM ui_catalog_dirty LIMIT 1").fetchone()


class OpportunityCatalog:
    def __init__(self, engine):
        self.engine, self.store = engine, engine.store
        self.lock = Lock()
        with self.store.connect() as db:
            intact = available(db)
            db.executescript("""
              CREATE TABLE IF NOT EXISTS ui_catalog_state(id INTEGER PRIMARY KEY CHECK(id=1),version INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS ui_catalog_dirty(candidate_id INTEGER PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 1);
              CREATE TABLE IF NOT EXISTS ui_catalog_candidates(
                candidate_id INTEGER PRIMARY KEY,observation_id INTEGER,chain TEXT,contract TEXT,
                search_text TEXT,verdict,rank_score,market_at,security_at,initial_price,current_fields TEXT);
              CREATE INDEX IF NOT EXISTS ui_catalog_identity ON ui_catalog_candidates(chain,contract);
              CREATE INDEX IF NOT EXISTS ui_catalog_verdict ON ui_catalog_candidates(verdict,candidate_id DESC);
              CREATE TABLE IF NOT EXISTS ui_catalog_baselines(signal_id INTEGER PRIMARY KEY,candidate_id INTEGER,fields TEXT);
              CREATE INDEX IF NOT EXISTS ui_catalog_baseline_subject ON ui_catalog_baselines(candidate_id);
            """)
            db.execute("BEGIN IMMEDIATE")
            upgrade = "revision" not in {r[1] for r in db.execute("PRAGMA table_info(ui_catalog_dirty)")}
            if upgrade:
                db.execute("ALTER TABLE ui_catalog_dirty ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
            for table, subject in [("opportunity_candidates", "id"),
                                   ("opportunity_observations", "candidate_id"),
                                   ("opportunity_signals", "candidate_id")]:
                for event in ["INSERT", "UPDATE", "DELETE"]:
                    refs = ["OLD", "NEW"] if event == "UPDATE" else ["OLD" if event == "DELETE" else "NEW"]
                    body = " ".join(f"INSERT INTO ui_catalog_dirty(candidate_id) VALUES({ref}.{subject}) ON CONFLICT(candidate_id) DO UPDATE SET revision=revision+1;" for ref in refs)
                    changed = {"opportunity_candidates": "id,chain,contract,discovery",
                               "opportunity_observations": "id,candidate_id,payload",
                               "opportunity_signals": "id,candidate_id,observation_id,kind"}
                    trigger_event = "UPDATE OF " + changed[table] if event == "UPDATE" else event
                    db.execute(f"DROP TRIGGER IF EXISTS ui_catalog_{table}_{event}")
                    db.execute(f"CREATE TRIGGER ui_catalog_{table}_{event} AFTER {trigger_event} ON {table} BEGIN {body} END")
            version = db.execute("SELECT version FROM ui_catalog_state WHERE id=1").fetchone()
            if not intact or not version or version[0] != VERSION:
                db.execute("INSERT OR IGNORE INTO ui_catalog_dirty(candidate_id) SELECT id FROM opportunity_candidates")
                db.execute("INSERT OR IGNORE INTO ui_catalog_dirty(candidate_id) SELECT candidate_id FROM opportunity_signals WHERE kind='baseline'")
                db.execute("INSERT OR REPLACE INTO ui_catalog_state VALUES(1,?)", (VERSION,))

    def status(self):
        with self.store.connect() as db:
            pending = db.execute("SELECT count(*) FROM ui_catalog_dirty").fetchone()[0]
            indexed = db.execute("SELECT count(*) FROM ui_catalog_candidates").fetchone()[0]
        state = "ready" if not pending else "updating" if indexed and pending <= 1000 else "preparing"
        return {"state": state, "pending_subjects": pending,
                "indexed_candidates": indexed, "version": VERSION, "derived_data_only": True}

    def refresh(self, limit=1000, wait=False):
        acquired = self.lock.acquire(timeout=1) if wait else self.lock.acquire(blocking=False)
        if not acquired:
            return
        try:
            with self.store.connect() as db:
                if not db.execute("SELECT 1 FROM ui_catalog_dirty LIMIT 1").fetchone():
                    return
                db.execute("BEGIN")
                revisions = dict(db.execute("SELECT candidate_id,revision FROM ui_catalog_dirty ORDER BY candidate_id DESC LIMIT ?", (limit,)))
                ids = list(revisions)
                if not ids:
                    return
                wanted = (json.dumps(ids),)
                subjects = "(SELECT value FROM json_each(?))"
                rows = db.execute(f"""
                  SELECT c.id,o.id AS observation_id,c.chain,c.contract,
                    c.contract || ' ' || coalesce(json_extract(c.discovery,'$.name'),'') || ' ' ||
                    coalesce(json_extract({OBS},'$.market.name'),'') || ' ' ||
                    coalesce(json_extract({OBS},'$.market.symbol'),'') AS search_text,
                    coalesce(json_extract({OBS},'$.decision.verdict'),'PENDING') AS verdict,
                    json_extract({OBS},'$.decision.rank_score') AS rank_score,
                    json_extract({OBS},'$.market.observed_at') AS market_at,
                    json_extract({OBS},'$.security.observed_at') AS security_at,
                    json_extract(c.discovery,'$.price_usd') AS initial_price,
                    json_extract({OBS},{CURRENT}) AS current_fields
                  FROM opportunity_candidates c LEFT JOIN opportunity_observations o ON o.id=(
                    SELECT id FROM opportunity_observations WHERE candidate_id=c.id ORDER BY id DESC LIMIT 1)
                  WHERE c.id IN {subjects}
                """, wanted).fetchall()
                baselines = db.execute(f"""
                  SELECT s.id,s.candidate_id,json_extract({OBS},{BASELINE})
                  FROM opportunity_signals s JOIN opportunity_observations o ON o.id=s.observation_id
                  WHERE s.kind='baseline' AND s.candidate_id IN {subjects}""", wanted).fetchall()
            # JSON extraction holds only a WAL read snapshot. Publish small rows
            # under a short writer lock, and retry subjects changed while read.
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                unchanged = {r[0] for r in db.execute(f"SELECT candidate_id,revision FROM ui_catalog_dirty WHERE candidate_id IN {subjects}", wanted)
                             if revisions.get(r[0]) == r[1]}
                wanted = (json.dumps(sorted(unchanged)),)
                db.execute(f"DELETE FROM ui_catalog_candidates WHERE candidate_id IN {subjects}", wanted)
                db.executemany("INSERT INTO ui_catalog_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               [tuple(r[:4]) + (r["search_text"].casefold(),) + tuple(r[5:]) for r in rows if r[0] in unchanged])
                db.execute(f"DELETE FROM ui_catalog_baselines WHERE candidate_id IN {subjects}", wanted)
                db.executemany("INSERT OR REPLACE INTO ui_catalog_baselines VALUES(?,?,?)",
                               [tuple(r) for r in baselines if r[1] in unchanged])
                db.execute(f"DELETE FROM ui_catalog_dirty WHERE candidate_id IN {subjects}", wanted)
        finally:
            self.lock.release()

    async def run(self):
        while True:
            await self.engine._background(self.refresh)
            await asyncio.sleep(.2 if self.status()["pending_subjects"] else 1)

    def listing(self, limit=50, before=None, ranked=False, query="", verdict="all"):
        self.refresh(wait=True)
        now = time.time()
        config = self.engine.config()
        try:
            exact = solana_address(query.strip())
        except ValueError:
            exact = None
        with self.store.connect() as db:
            db.execute("BEGIN")
            pending = db.execute("SELECT count(*) FROM ui_catalog_dirty").fetchone()[0]
            if pending > 1000:
                if query.strip() or ranked or verdict != "all":
                    raise ProviderError("Indexul de căutare se pregătește în fundal. Candidații recenți rămân accesibili; reîncearcă după indexare.")
                fallback = True
            else:
                fallback = False
                prefix, table = "", "ui_catalog_candidates"
                if pending:
                    # Overlay a small, consistent dirty tail instead of serving
                    # stale rankings or waiting for the next background refresh.
                    db.create_function("casefold", 1, lambda v: str(v or "").casefold(), deterministic=True)
                    table = "catalog"
                    prefix = f"""WITH catalog AS (
                      SELECT candidate_id,chain,contract,search_text,verdict,rank_score,market_at,security_at
                      FROM ui_catalog_candidates x WHERE NOT EXISTS(
                        SELECT 1 FROM ui_catalog_dirty d WHERE d.candidate_id=x.candidate_id)
                      UNION ALL
                      SELECT c.id,c.chain,c.contract,casefold(c.contract || ' ' ||
                        coalesce(json_extract(c.discovery,'$.name'),'') || ' ' ||
                        coalesce(json_extract({OBS},'$.market.name'),'') || ' ' ||
                        coalesce(json_extract({OBS},'$.market.symbol'),'')),
                        coalesce(json_extract({OBS},'$.decision.verdict'),'PENDING'),
                        json_extract({OBS},'$.decision.rank_score'),
                        json_extract({OBS},'$.market.observed_at'),json_extract({OBS},'$.security.observed_at')
                      FROM opportunity_candidates c LEFT JOIN opportunity_observations o ON o.id=(
                        SELECT id FROM opportunity_observations WHERE candidate_id=c.id ORDER BY id DESC LIMIT 1)
                      WHERE c.id IN (SELECT candidate_id FROM ui_catalog_dirty)) """
                params = {"q": query.strip().casefold(), "exact": exact, "verdict": verdict,
                          "before": before, "limit": limit + 1,
                          "now": datetime.fromtimestamp(now, UTC).isoformat(),
                          "fresh_from": datetime.fromtimestamp(now - self.engine.service.settings.max_snapshot_age, UTC).isoformat()}
                where = "WHERE (:verdict='all' OR verdict=:verdict) AND " + (
                    "chain='solana' AND contract=:exact" if exact else "(:q='' OR instr(search_text,:q)>0)")
                count = db.execute(prefix + "SELECT count(*) FROM " + table + " " + where, params).fetchone()[0]
                order = ("coalesce(CASE WHEN julianday(market_at) BETWEEN julianday(:fresh_from) AND julianday(:now) "
                         "AND julianday(security_at) BETWEEN julianday(:fresh_from) AND julianday(:now) THEN rank_score END,-1) DESC,candidate_id DESC"
                         if ranked else "candidate_id DESC")
                selected = [r[0] for r in db.execute(prefix + "SELECT candidate_id FROM " + table + " " + where +
                            " AND (:before IS NULL OR candidate_id<:before) ORDER BY " + order + " LIMIT :limit", params)]
                items = self._items(db, selected[:limit], config, now)
        if fallback:
            return self.engine.listing(limit, before, ranked, query, verdict)
        return {"items": items, "matching_total": count,
                "ranking_limited": ranked and len(selected) > limit,
                "next_cursor": selected[limit - 1] if len(selected) > limit and not ranked else None,
                "status": self.engine.status, "config": config.model_dump(mode="json"),
                "coverage": "Solana provider pool/profile/paid-exposure feeds; not all launches, and meme classification is unverified. Base is discovery-only in Level 3.",
                "live_execution": False}

    def _items(self, db, ids, config, now):
        monitoring = lifecycle.candidates(self.engine, db, config, ids, now)
        items = []
        for candidate_id in ids:
            row = db.execute("SELECT * FROM opportunity_candidates WHERE id=?", (candidate_id,)).fetchone()
            latest = db.execute("SELECT * FROM opportunity_observations WHERE candidate_id=? ORDER BY id DESC LIMIT 1", (candidate_id,)).fetchone()
            initial = db.execute("SELECT * FROM opportunity_signals WHERE candidate_id=? AND kind='baseline' ORDER BY id LIMIT 1", (candidate_id,)).fetchone()
            last = json.loads(latest["payload"]) if latest else None
            market = (last or {}).get("market")
            items.append(dict(row) | {
                "discovery": json.loads(row["discovery"]), "latest": last,
                "latest_at": latest["at"] if latest else None, "monitoring": monitoring[candidate_id],
                "initial_signal": dict(initial) | {"payload": json.loads(initial["payload"])} if initial else None,
                "fresh": bool(market and 0 <= now - epoch(market["observed_at"]) <= self.engine.service.settings.max_snapshot_age
                              and (last or {}).get("security") and 0 <= now - epoch(last["security"]["observed_at"]) <= self.engine.service.settings.max_snapshot_age),
            })
        return items
