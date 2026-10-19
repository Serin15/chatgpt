"""Timestamped narrative evidence. A lexical match never establishes a token relationship."""

import json
import re
from urllib.parse import urlsplit

from app.ai_research import AIInput
from app.announcements import SOURCES
from app.errors import ProviderError
from app.models import epoch, utcnow
from app.story_evidence import StoryEvidence

TOPIC_WORDS = {
    "AI": r"\bclaude\b|\banthropic\b|\bartificial intelligence\b|\bAI\b",
    "public_figure": r"\btrump\b|\bmusk\b|\bzelensk",
    "animals": r"\bdog\b|\bcat\b|\bshib|\bdoge",
    "launch_listing": r"\blaunch|\blist(?:ing|ed)|\btoken",
}


class Narratives:
    def __init__(self, service):
        self.service = service
        self.store = service.store
        self.stories = StoryEvidence(self.store)
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS narrative_research_requests(news_id INTEGER PRIMARY KEY,at TEXT NOT NULL,state TEXT NOT NULL,error TEXT)"
            )

    def evidence(self, contract, at):
        now = epoch(at)
        supported = []
        uncertain = []
        contradictory = []
        market_references = []
        hosts = set()
        counts = {}
        ai = []
        indexed = self.stories.for_contract(contract, at)
        indexed_ids = {item["news_id"] for item in indexed}
        for item in indexed:
            item["categories"] = [
                k for k, p in TOPIC_WORDS.items() if re.search(p, item["title"], re.I)
            ]
            age = now - epoch(item["first_seen_at"])
            bucket = "0_1h" if age <= 3600 else "1_6h" if age <= 21600 else "6_24h"
            counts[bucket] = counts.get(bucket, 0) + 1
            if item["association"] == "exact_contract_document_mention":
                supported.append(item)
                hosts.add(urlsplit(item["url"]).hostname)
            elif item["association"] == "contradictory_context":
                contradictory.append(item)
            elif item["association"] == "resolved_market_pair_reference":
                market_references.append(item)
            else:
                uncertain.append(item)
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT n.*,m.market AS matched_market,m.first_matched_at FROM news n JOIN news_matches m ON m.news_id=n.id WHERE m.address=? ORDER BY n.id DESC LIMIT 100",
                (contract,),
            ).fetchall()
            for row in rows:
                if row["id"] in indexed_ids:
                    continue
                if epoch(row["first_seen_at"]) > now or epoch(row["first_matched_at"]) > now:
                    continue
                published = row["published_at"]
                if not published or not 0 <= now - epoch(published) <= 86400:
                    continue
                item = {
                    "news_id": row["id"],
                    "url": row["url"],
                    "title": row["title"],
                    "publisher_reported": row["publisher"],
                    "published_at": published,
                    "first_seen_at": row["first_seen_at"],
                    "categories": [
                        k for k, p in TOPIC_WORDS.items() if re.search(p, row["title"], re.I)
                    ],
                }
                checks = db.execute(
                    "SELECT at,payload FROM announcement_documents WHERE news_id=? AND julianday(at)<=julianday(?) ORDER BY id DESC LIMIT 1",
                    (row["id"], at),
                ).fetchall()
                matched = False
                for docrow in checks:
                    if epoch(docrow["at"]) > now or now - epoch(docrow["at"]) > 86400:
                        continue
                    try:
                        doc = json.loads(docrow["payload"])
                    except (ValueError, TypeError):
                        continue
                    if not isinstance(doc, dict):
                        continue
                    candidates = doc.get("contract_candidates", [])
                    if not isinstance(candidates, list):
                        continue
                    exact = [
                        c
                        for c in candidates
                        if isinstance(c, dict)
                        and c.get("contract") == contract
                        and c.get("networks_reported") == ["solana"]
                        and not c.get("negative_context")
                    ]
                    if doc.get("state") == "read" and exact:
                        item.update(
                            association="exact_contract_document_mention",
                            source_sha256=doc.get("sha256"),
                            document_observed_at=docrow["at"],
                            claim_verified=False,
                            endorsement_verified=False,
                        )
                        supported.append(item)
                        hosts.add(urlsplit(doc.get("url", row["url"])).hostname)
                        matched = True
                        break
                if not matched:
                    uncertain.append(item | {"association": "uncertain_name_or_headline_match"})
                bucket = (
                    "0_1h"
                    if now - epoch(row["first_seen_at"]) <= 3600
                    else "1_6h"
                    if now - epoch(row["first_seen_at"]) <= 21600
                    else "6_24h"
                )
                counts[bucket] = counts.get(bucket, 0) + 1
            for row in db.execute(
                "SELECT at,payload FROM ai_attempts WHERE address=? AND state='completed' ORDER BY id DESC LIMIT 5",
                (contract,),
            ):
                if not 0 <= now - epoch(row["at"]) <= 86400:
                    continue
                p = json.loads(row["payload"])
                if p.get("citations_checked"):
                    ai.append(
                        {
                            "at": row["at"],
                            "interpretation": p["interpretation"],
                            "relationship": p.get("relationship"),
                            "source_urls": [s["url"] for s in p["bundle"]["sources"]],
                            "semantic_truth_verified": False,
                        }
                    )
        return {
            "supported": supported,
            "uncertain": uncertain,
            "contradictory": contradictory,
            "market_references": market_references,
            "ranking_supported": bool(supported) and not contradictory,
            "publication_hosts": sorted(h for h in hosts if h),
            "news_recurrence_counts": counts,
            "social_mentions_growth": None,
            "community_activity": None,
            "score": min(100, 40 + 20 * len(hosts)) if supported and not contradictory else None,
            "ai_interpretations": ai,
            "note": "Distinct publication hosts are not proven editorial independence. RSS headline counts are not social audience growth. Exact contract mentions do not establish issuer endorsement.",
        }

    async def classify(self, contract, evidence, config):
        engine = self.service.research.ai
        if (
            not config.ai_narratives
            or not evidence["supported"]
            or engine.config().provider == "disabled"
        ):
            return
        if evidence["ai_interpretations"] or engine.lock.locked():
            return
        source = evidence["supported"][0]
        await engine.analyze(
            contract,
            AIInput(
                source_url=source["url"],
                news_id=source["news_id"],
                chain="solana",
                contract=contract,
            ),
        )

    async def refresh_trends(self, config):
        """One bounded primary-document classification per cycle, with normal AI accounting."""
        engine = self.service.research.ai
        if (
            not config.ai_narratives
            or engine.config().provider == "disabled"
            or engine.lock.locked()
        ):
            return
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT d.news_id,d.at,d.payload,n.url FROM announcement_documents d JOIN news n ON n.id=d.news_id ORDER BY d.id DESC LIMIT 20"
            ).fetchall()
            selected = None
            for row in rows:
                p = json.loads(row["payload"])
                if p.get("state") != "read" or epoch(row["at"]) < epoch(utcnow()) - 86400:
                    continue
                address = "asset:narrative-" + str(row["news_id"])
                attempted = db.execute(
                    "SELECT at FROM narrative_research_requests WHERE news_id=?", (row["news_id"],)
                ).fetchone()
                if attempted and epoch(utcnow()) - epoch(attempted["at"]) < 3600:
                    continue
                if db.execute(
                    "SELECT 1 FROM ai_attempts WHERE address=? AND at>=?", (address, row["at"])
                ).fetchone():
                    continue
                selected = (address, row)
                break
            if selected is None:
                # Read a permitted publisher's actual document, rather than asking
                # AI to turn an aggregator headline into a fact or endorsement.
                for row in db.execute(
                    "SELECT id AS news_id,url,published_at,first_seen_at FROM news ORDER BY id DESC LIMIT 100"
                ):
                    if (
                        urlsplit(row["url"]).hostname not in SOURCES
                        or not row["published_at"]
                        or not 0 <= epoch(utcnow()) - epoch(row["published_at"]) <= 86400
                    ):
                        continue
                    address = "asset:narrative-" + str(row["news_id"])
                    attempted = db.execute(
                        "SELECT at FROM narrative_research_requests WHERE news_id=?",
                        (row["news_id"],),
                    ).fetchone()
                    if attempted and epoch(utcnow()) - epoch(attempted["at"]) < 3600:
                        continue
                    if not db.execute(
                        "SELECT 1 FROM ai_attempts WHERE address=?", (address,)
                    ).fetchone():
                        selected = (address, row)
                        break
        if selected:
            address, row = selected
            with self.store.connect() as db:
                db.execute(
                    "INSERT OR REPLACE INTO narrative_research_requests VALUES(?,?,'pending',NULL)",
                    (row["news_id"], utcnow()),
                )
            try:
                result = await engine.analyze(
                    address,
                    AIInput(source_url=row["url"], news_id=row["news_id"], purpose="narrative"),
                )
                state = result.get("state", "completed")
                error = (result.get("payload") or {}).get("error")
            except (ProviderError, ValueError, TypeError):
                state = "source_or_ai_unavailable"
                error = "Permitted document or configured model unavailable; retry after backoff."
            with self.store.connect() as db:
                db.execute(
                    "UPDATE narrative_research_requests SET state=?,error=? WHERE news_id=?",
                    (state, error, row["news_id"]),
                )

    def trends(self):
        with self.store.connect() as db:
            requests = [
                dict(r)
                for r in db.execute(
                    "SELECT r.*,n.url,n.title FROM narrative_research_requests r JOIN news n ON n.id=r.news_id ORDER BY at DESC LIMIT 20"
                )
            ]
            rows = db.execute(
                "SELECT id,address,at,state,payload FROM ai_attempts WHERE address LIKE 'asset:narrative-%' ORDER BY id DESC LIMIT 20"
            ).fetchall()
        result = []
        for row in rows:
            p = json.loads(row["payload"])
            result.append(
                {
                    "id": row["id"],
                    "at": row["at"],
                    "state": row["state"],
                    "category": (p.get("interpretation") or {}).get("narrative_category"),
                    "interpretation": p.get("interpretation"),
                    "error": p.get("error"),
                    "citations_checked": p.get("citations_checked", False),
                    "sources": [
                        {k: s[k] for k in ("url", "publisher", "sha256") if k in s}
                        for s in p.get("bundle", {}).get("sources", [])
                    ],
                    "claim_verified": False,
                    "token_association": "none_without_contract_evidence",
                }
            )
        return {
            "items": result,
            "stories": self.stories.listing(),
            "document_requests": requests,
            "ai_configured": self.service.research.ai.config().provider != "disabled",
            "enabled": self.service.opportunities.config().ai_narratives,
            "social_api": "not_configured",
            "community_metrics": "not_available",
        }
