"""Append-only, point-in-time contract mentions from already permitted documents.

Indexing is independent of DEX quotes and AI. A mention never verifies an issuer.
"""

import json
import re
import time
from urllib.parse import urlsplit

from app.announcements import SOURCES
from app.assets import safe_link
from app.headline_groups import group_headlines
from app.models import epoch, solana_address, utcnow
from app.news import canonical_url, relevant_headline
from app.story_markets import validated_reference


class StoryEvidence:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS story_documents(document_id INTEGER PRIMARY KEY,news_id INTEGER NOT NULL,indexed_at TEXT NOT NULL,available_at REAL NOT NULL,state TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS story_document_news ON story_documents(news_id,document_id DESC);
                CREATE TABLE IF NOT EXISTS story_contracts(document_id INTEGER NOT NULL,contract TEXT NOT NULL,association TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(document_id,contract));
                CREATE INDEX IF NOT EXISTS story_contract_subject ON story_contracts(contract,document_id DESC);
            """)

    def index_documents(self, limit=250):
        """Bounded local work only; first indexed time is never backdated to publication."""
        at = utcnow()
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT d.*,n.url AS news_url FROM announcement_documents d JOIN news n ON n.id=d.news_id LEFT JOIN story_documents s ON s.document_id=d.id WHERE s.document_id IS NULL ORDER BY d.id LIMIT ?",
                (limit,),
            ).fetchall()
            for row in rows:
                state, payload, mentions = "invalid", {}, []
                available_at = epoch(at)
                try:
                    value = json.loads(row["payload"])
                    url = value.get("url", "")
                    if (
                        not safe_link(url)
                        or urlsplit(url).hostname not in SOURCES
                        or canonical_url(url) != canonical_url(row["news_url"])
                    ):
                        raise ValueError("Unpermitted or mismatched document URL")
                    payload = {
                        "url": url,
                        "source_sha256": value.get("sha256"),
                        "source_kind": SOURCES[urlsplit(url).hostname]["kind"],
                        "document_observed_at": value.get("observed_at", row["at"]),
                        "document_recorded_at": row["at"],
                        "excerpt": str(value.get("excerpt", ""))[:500],
                        "market_pair_references": [],
                    }
                    available_at = max(
                        available_at, epoch(row["at"]), epoch(payload["document_observed_at"])
                    )
                    state = "unavailable"
                    if value.get("state") == "read":
                        if not re.fullmatch(r"[a-fA-F0-9]{64}", value.get("sha256", "")):
                            raise ValueError("Missing content digest")
                        candidates = value.get("contract_candidates", [])
                        if not isinstance(candidates, list):
                            raise ValueError("Invalid contract candidates")
                        for candidate in candidates[:12]:
                            contract = candidate["contract"]
                            try:
                                solana_address(contract)
                            except ValueError:
                                continue  # EVM identities do not become Solana links.
                            networks = candidate["networks_reported"]
                            negative = candidate["negative_context"]
                            if (
                                not isinstance(networks, list)
                                or any(not isinstance(n, str) for n in networks)
                                or not isinstance(negative, bool)
                            ):
                                raise ValueError("Invalid chain/context evidence")
                            mentions.append(
                                (
                                    contract,
                                    "contradictory_context"
                                    if negative
                                    else "exact_contract_document_mention"
                                    if networks == ["solana"]
                                    else "uncertain_chain",
                                    {
                                        "networks_reported": networks,
                                        "excerpt": str(candidate.get("excerpt", ""))[:1500],
                                    },
                                )
                            )
                        references = value.get("market_pair_references", [])
                        if not isinstance(references, list):
                            raise ValueError("Invalid market references")
                        for ref in references[:2]:
                            if not isinstance(ref, dict):
                                continue
                            if ref.get("state") != "resolved":
                                payload["market_pair_references"].append(ref)
                                continue
                            try:
                                ref = validated_reference(ref)
                                if not 0 <= epoch(at) - epoch(ref["observed_at"]) <= 86400:
                                    continue
                            except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                                continue
                            payload["market_pair_references"].append(ref)
                            mentions.append(
                                (
                                    ref["base_contract"],
                                    "contradictory_context"
                                    if ref["negative_context"]
                                    else "resolved_market_pair_reference",
                                    {
                                        "networks_reported": ["solana"],
                                        "excerpt": ref.get("excerpt", ""),
                                        "market_reference": ref,
                                    },
                                )
                            )
                        state = "read"
                except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
                    state, mentions, payload = "invalid", [], {}
                db.execute(
                    "INSERT OR IGNORE INTO story_documents VALUES(?,?,?,?,?,?)",
                    (row["id"], row["news_id"], at, available_at, state, json.dumps(payload)),
                )
                for contract, association, evidence in mentions:
                    db.execute(
                        "INSERT OR IGNORE INTO story_contracts VALUES(?,?,?,?)",
                        (row["id"], contract, association, json.dumps(evidence)),
                    )
        return len(rows)

    def for_contract(self, contract, at):
        with self.store.connect() as db:
            rows = db.execute(
                """SELECT n.*,s.document_id,s.indexed_at,s.payload AS document,c.association,c.payload AS mention
                FROM story_contracts c JOIN story_documents s ON s.document_id=c.document_id
                JOIN news n ON n.id=s.news_id
                WHERE c.contract=? AND s.document_id=(
                    SELECT s2.document_id FROM story_documents s2
                    WHERE s2.news_id=s.news_id AND s2.available_at<=?
                    ORDER BY s2.document_id DESC LIMIT 1)
                ORDER BY s.document_id DESC LIMIT 100""",
                (contract, epoch(at)),
            ).fetchall()
        result = []
        now = epoch(at)
        for row in rows:
            if (
                epoch(row["first_seen_at"]) > now
                or not row["published_at"]
                or not 0 <= now - epoch(row["published_at"]) <= 86400
            ):
                continue
            document, mention = json.loads(row["document"]), json.loads(row["mention"])
            if not 0 <= now - epoch(document["document_observed_at"]) <= 86400:
                continue
            result.append(
                {
                    "news_id": row["id"],
                    "document_id": row["document_id"],
                    "url": row["url"],
                    "title": row["title"],
                    "publisher_reported": row["publisher"],
                    "published_at": row["published_at"],
                    "first_seen_at": row["first_seen_at"],
                    "evidence_indexed_at": row["indexed_at"],
                    "association": row["association"],
                    **document,
                    **mention,
                    "claim_verified": False,
                    "endorsement_verified": False,
                }
            )
        return result

    def listing(self, limit=20):
        """Read-only story feed; unpermitted headlines remain explicitly unread."""
        now, at = time.time(), utcnow()
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT * FROM news WHERE id IN (SELECT min(id) FROM news GROUP BY canonical_url) AND julianday(first_seen_at)<=julianday(?) ORDER BY coalesce(published_at,first_seen_at) DESC LIMIT 100",
                (at,),
            ).fetchall()
            stories = []
            for row in rows:
                if not row["published_at"] or not 0 <= now - epoch(row["published_at"]) <= 86400:
                    continue
                source = SOURCES.get(urlsplit(row["url"]).hostname)
                document = db.execute(
                    "SELECT * FROM story_documents WHERE news_id=? AND available_at<=? ORDER BY document_id DESC LIMIT 1",
                    (row["id"], now),
                ).fetchone()
                links = []
                if document:
                    for mention in db.execute(
                        "SELECT sc.*,c.id AS candidate_id,c.eligible,c.exclusion_reason FROM story_contracts sc LEFT JOIN opportunity_candidates c ON c.chain='solana' AND c.contract=sc.contract WHERE sc.document_id=?",
                        (document["document_id"],),
                    ):
                        links.append(dict(mention) | {"payload": json.loads(mention["payload"])})
                stories.append(
                    {
                        "news_id": row["id"],
                        "title": row["title"],
                        "memecoin_headline": relevant_headline(row["title"], "memecoins"),
                        "url": row["url"],
                        "publisher_reported": row["publisher"],
                        "published_at": row["published_at"],
                        "first_seen_at": row["first_seen_at"],
                        "document_state": document["state"]
                        if document
                        else "pending_permitted_document"
                        if source
                        else "headline_only_unpermitted_document",
                        "document": json.loads(document["payload"]) if document else None,
                        "source_kind": source["kind"] if source else "headline_only",
                        "contracts": links,
                        "claim_verified": False,
                        "endorsement_verified": False,
                    }
                )
            indexed = db.execute("SELECT count(*) FROM story_documents").fetchone()[0]
            pending = db.execute(
                "SELECT count(*) FROM announcement_documents d LEFT JOIN story_documents s ON s.document_id=d.id WHERE s.document_id IS NULL"
            ).fetchone()[0]
        stories.sort(
            key=lambda s: (
                bool(s["contracts"]),
                s["memecoin_headline"],
                s["source_kind"] != "headline_only",
                s["published_at"],
            ),
            reverse=True,
        )
        grouped = group_headlines(stories)
        return {
            "at": at,
            "items": grouped[:limit],
            "raw_headlines_in_window": len(stories),
            "display_groups_in_window": len(grouped),
            "indexed_documents": indexed,
            "pending_index": pending,
            "index_budget_per_cycle": 250,
            "note": "Headlines are reported claims; exact contract mentions are not issuer/endorsement verification. No global social growth measurements.",
        }
