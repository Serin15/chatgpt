"""Bounded document evidence and scoped, manually reviewed issuer relationships.

A document match is a mechanical observation, never proof of an endorsement or investment merit.
"""

import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from pydantic import BaseModel, Field, model_validator

from app.assets import safe_link
from app.models import epoch, solana_address, utcnow
from app.providers import ProviderError

SOURCES = {
    "blog.ethereum.org": {
        "publisher": "Ethereum Foundation",
        "kind": "primary",
        "relations": ["issuer"],
    },
    "blog.kraken.com": {"publisher": "Kraken", "kind": "primary", "relations": ["listing"]},
    "www.coindesk.com": {"publisher": "CoinDesk · redacție", "kind": "editorial", "relations": []},
    "www.anthropic.com": {"publisher": "Anthropic", "kind": "primary", "relations": ["issuer"]},
    "developers.circle.com": {"publisher": "Circle", "kind": "primary", "relations": ["issuer"]},
    "solana.com": {"publisher": "Solana", "kind": "primary", "relations": ["issuer"]},
}
Chain = Literal["solana", "ethereum", "base", "polygon", "bsc", "arbitrum", "avalanche"]
PLATFORMS = {
    "ethereum": "ethereum",
    "base": "base",
    "polygon-pos": "polygon",
    "binance-smart-chain": "bsc",
    "arbitrum-one": "arbitrum",
    "avalanche": "avalanche",
    "solana": "solana",
}
EXPLORERS = {
    "etherscan.io": "ethereum",
    "basescan.org": "base",
    "polygonscan.com": "polygon",
    "bscscan.com": "bsc",
    "arbiscan.io": "arbitrum",
    "snowtrace.io": "avalanche",
    "solscan.io": "solana",
    "explorer.solana.com": "solana",
}
NETWORKS = {
    "solana": r"\bsolana\b",
    "ethereum": r"\bethereum\b",
    "base": r"\bbase\s+(?:mainnet|network|chain|blockchain|contract)\b|\b(?:network|chain)\s*[:=]?\s*base\b|^base\s*[:|]?\s*0x",
    "polygon": r"\bpolygon\b",
    "bsc": r"\b(?:bsc|bnb smart chain|binance smart chain)\b",
    "arbitrum": r"\barbitrum\b",
    "avalanche": r"\bavalanche\b",
}
NEGATIVE = re.compile(
    r"\b(?:unofficial|counterfeit|scam|fake|not affiliated|not official|not issued|not our|do not buy|don't buy|denies|denied)\b",
    re.I,
)
EVM = re.compile(r"(?<![A-Za-z0-9])0x[a-fA-F0-9]{40}(?![A-Za-z0-9])")
SOL = re.compile(r"(?<![A-Za-z0-9])[1-9A-HJ-NP-Za-km-z]{32,44}(?![A-Za-z0-9])")


def normalized(text):
    return " ".join(text.split())


def contract_equal(left, right, chain):
    return left == right if chain == "solana" else left.lower() == right.lower()


class VerificationInput(BaseModel):
    source_url: str = Field(max_length=2000)
    chain: Chain
    contract: str = Field(max_length=80)
    news_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_target(self):
        if not safe_link(self.source_url):
            raise ValueError(
                "Anunțul trebuie să aibă URL HTTPS fără autentificare sau port special."
            )
        if self.chain == "solana":
            solana_address(self.contract)
        elif not re.fullmatch(r"0x[a-fA-F0-9]{40}", self.contract):
            raise ValueError("Contract EVM invalid.")
        return self


class ApprovalInput(VerificationInput):
    relation: Literal["issuer", "listing"]
    proof_url: str = Field(max_length=2000)
    reviewer_note: str = Field(min_length=20, max_length=2000)
    reviewed: Literal[True]

    @model_validator(mode="after")
    def validate_review(self):
        if not safe_link(self.proof_url):
            raise ValueError("Evaluarea emitentului cere un link public HTTPS de justificare.")
        if len(self.reviewer_note.strip()) < 20:
            raise ValueError("Explică verificarea emitentului în minimum 20 de caractere.")
        return self


class DocumentReader(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "header", "footer", "nav", "aside", "form"}
    VOID = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.stack, self.parts, self.links, self.blocks = url, [], [], [], []
        self.title, self.published_at = [], None
        self.open_blocks = []
        self.hidden_depths = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and attrs.get("property", attrs.get("name")) in {
            "article:published_time",
            "datePublished",
            "pubdate",
        }:
            self.published_at = attrs.get("content")
        if tag not in self.VOID:
            self.stack.append(tag)
            if (
                "hidden" in attrs
                or (attrs.get("aria-hidden") or "").lower() == "true"
                or re.search(
                    r"(?:display\s*:\s*none|visibility\s*:\s*hidden)",
                    attrs.get("style") or "",
                    re.I,
                )
            ):
                self.hidden_depths.append(len(self.stack))
        if self.hidden_depths or any(t in self.SKIP for t in self.stack):
            return
        if tag == "a" and len(self.links) < 1000:
            target = urljoin(self.url, attrs.get("href", ""))
            if safe_link(target):
                self.links.append(
                    {
                        "url": target,
                        "main": any(t in {"main", "article"} for t in self.stack),
                        "context_blocks": list(self.open_blocks),
                    }
                )
        if tag in {"p", "tr", "li"}:
            self.open_blocks.append(
                {
                    "depth": len(self.stack),
                    "parts": [],
                    "main": any(t in {"main", "article"} for t in self.stack),
                }
            )

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag not in self.stack:
            return
        index = len(self.stack) - 1 - self.stack[::-1].index(tag)
        for block in list(self.open_blocks):
            if block["depth"] > index:
                self.blocks.append(
                    {"text": normalized(" ".join(block["parts"])), "main": block["main"]}
                )
                self.open_blocks.remove(block)
        self.stack = self.stack[:index]
        self.hidden_depths = [depth for depth in self.hidden_depths if depth <= index]

    def handle_data(self, data):
        if "title" in self.stack:
            self.title.append(data)
        if "head" in self.stack or self.hidden_depths or any(t in self.SKIP for t in self.stack):
            return
        main = any(t in {"main", "article"} for t in self.stack)
        self.parts.append({"text": data, "main": main})
        for block in self.open_blocks:
            block["parts"].append(data)

    def document(self):
        has_main = any(p["main"] for p in self.parts)
        text = normalized(" ".join(p["text"] for p in self.parts if not has_main or p["main"]))
        blocks = [b["text"] for b in self.blocks if b["text"] and (not has_main or b["main"])]
        for block in self.open_blocks:
            if not has_main or block["main"]:
                blocks.append(normalized(" ".join(block["parts"])))
        context_cache = {}
        for link in self.links:
            for block in link["context_blocks"]:
                if id(block) not in context_cache:
                    context_cache[id(block)] = normalized(" ".join(block["parts"]))[:2000]
        return {
            "text": text[:200_000],
            "text_truncated": len(text) > 200_000,
            "blocks": blocks[:2000],
            "links": [p["url"] for p in self.links if not has_main or p["main"]],
            "link_contexts": [
                {
                    "url": p["url"],
                    "text": " ".join(context_cache[id(b)] for b in p["context_blocks"][-2:]),
                }
                for p in self.links
                if not has_main or p["main"]
            ],
            "title": normalized(" ".join(self.title))[:300],
            "published_at_reported": self.published_at,
        }


def inspect_contract(document, chain, contract):
    flags = 0 if chain == "solana" else re.I
    exact = re.compile(r"(?<![A-Za-z0-9])" + re.escape(contract) + r"(?![A-Za-z0-9])", flags)
    blocks = [b for b in document["blocks"] if exact.search(b)]
    found = bool(exact.search(document["text"]))
    networks, links, link_contexts = set(), [], []
    for block in blocks:
        # Multiple networks in a paragraph/table row are deliberately ambiguous.
        mentioned = {key for key, pattern in NETWORKS.items() if re.search(pattern, block, re.I)}
        if len(mentioned) == 1:
            networks |= mentioned
    for link in document["links"]:
        url = urlsplit(link)
        match = re.fullmatch(r"/(?:token|address)/([^/]+)/?", url.path)
        network = EXPLORERS.get(url.hostname)
        cluster = parse_qs(url.query).get("cluster", ["mainnet-beta"])
        if (
            network
            and match
            and contract_equal(match[1], contract, chain)
            and (network != "solana" or cluster == ["mainnet-beta"])
        ):
            found = True
            networks.add(network)
            links.append(link)
            link_contexts.extend(
                p["text"]
                for p in document.get("link_contexts", [])
                if p["url"] == link and p["text"]
            )
    contexts = blocks or [
        document["text"][max(0, m.start() - 150) : m.end() + 150]
        for m in list(exact.finditer(document["text"]))[:5]
    ]
    contexts = list(dict.fromkeys(contexts + link_contexts))
    return {
        "exact_contract_found": found,
        "networks_reported": sorted(networks),
        "chain_supported": chain in networks,
        "negative_context": any(NEGATIVE.search(b) for b in contexts),
        "excerpt": (contexts[0] if contexts else "")[:1500],
        "explorer_links": links[:5],
        "text_truncated": document["text_truncated"],
    }


def contract_candidates(document):
    """Candidate addresses in text/mainnet explorer links, not verified token identities."""
    candidates = [("evm", m.group()) for m in EVM.finditer(document["text"])]
    candidates += [("solana", m.group()) for m in SOL.finditer(document["text"])]
    for link in document["links"]:
        url = urlsplit(link)
        match = re.fullmatch(r"/(?:token|address)/([^/]+)/?", url.path)
        if match and url.hostname in EXPLORERS:
            candidates.append(
                ("solana" if EXPLORERS[url.hostname] == "solana" else "evm", match[1])
            )
    result, seen = [], set()
    for kind, contract in candidates[:80]:
        if (kind, contract) in seen:
            continue
        seen.add((kind, contract))
        try:
            body = VerificationInput(
                source_url=document["url"],
                chain="solana" if kind == "solana" else "ethereum",
                contract=contract,
            )
        except ValueError:
            continue
        observed = inspect_contract(document, body.chain, body.contract)
        result.append(
            {
                "contract": contract,
                "networks_reported": observed["networks_reported"],
                "negative_context": observed["negative_context"],
                "token_identity_verified": False,
            }
        )
        if len(result) >= 12:
            break
    return result


class Announcements:
    def __init__(self, store, client):
        self.store, self.client = store, client
        self.cache, self.lock = OrderedDict(), asyncio.Lock()
        self.status = {"state": "unverified", "at": None, "error": None}
        self.source_status = {}
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS source_approvals(id INTEGER PRIMARY KEY,address TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL,revoked_at TEXT);
                CREATE INDEX IF NOT EXISTS source_approval_subject ON source_approvals(address,id DESC);
                CREATE TABLE IF NOT EXISTS announcement_checks(id INTEGER PRIMARY KEY,address TEXT NOT NULL,news_id INTEGER,at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS announcement_subject ON announcement_checks(address,news_id,id DESC);
                CREATE TABLE IF NOT EXISTS announcement_documents(id INTEGER PRIMARY KEY,news_id INTEGER NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS announcement_news ON announcement_documents(news_id,id DESC);
            """)

    def catalog(self):
        return [
            {
                "host": host,
                **definition,
                "status": self.source_status.get(host, {"state": "unverified", "at": None}),
            }
            for host, definition in SOURCES.items()
        ]

    def source_result(self, host, error=None):
        self.source_status[host] = {
            "state": "error" if error else "ok",
            "at": utcnow(),
            "error": error,
        }
        failures = {h: r["error"] for h, r in self.source_status.items() if r["state"] == "error"}
        self.status = {
            "state": "error" if failures else "ok",
            "at": utcnow(),
            "error": failures or None,
            "sources": dict(self.source_status),
        }

    async def document(self, url, force=False):
        if not safe_link(url) or urlsplit(url).hostname not in SOURCES:
            raise ProviderError(
                "Domeniu neacceptat pentru citire. Sunt permise doar sursele din catalog; nu urmărim redirecturi sau linkuri propuse de pagină."
            )
        async with self.lock:
            cached = self.cache.get(url)
            if not force and cached and time.monotonic() - cached[0] < 300:
                self.cache.move_to_end(url)
                return dict(cached[1]) | {"cached": True}
            try:
                async with self.client.stream("GET", url, follow_redirects=False) as response:
                    response.raise_for_status()
                    content_type = (
                        response.headers.get("content-type", "").split(";")[0].strip().lower()
                    )
                    if content_type not in {"text/html", "text/plain", "application/xhtml+xml"}:
                        raise ProviderError("Documentul nu este HTML/text suportat.")
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 2_000_000:
                            raise ProviderError("Documentul depășește limita de 2 MB.")
                        chunks.append(chunk)
                raw = b"".join(chunks)
                text = raw.decode("utf-8", errors="replace")
                reader = DocumentReader(url)
                if content_type == "text/plain":
                    reader.parts = [{"text": text, "main": False}]
                    reader.blocks = [{"text": line, "main": False} for line in text.splitlines()]
                else:
                    reader.feed(text)
                document = reader.document() | {
                    "url": url,
                    **SOURCES[urlsplit(url).hostname],
                    "observed_at": utcnow(),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "cached": False,
                }
                if not document["text"]:
                    raise ProviderError(
                        "Nu am putut extrage text lizibil; verificarea rămâne necunoscută."
                    )
                self.cache[url] = (time.monotonic(), document)
                while len(self.cache) > 64:
                    self.cache.popitem(last=False)
                self.source_result(urlsplit(url).hostname)
                return document
            except (httpx.HTTPError, ValueError, ProviderError) as exc:
                self.source_result(urlsplit(url).hostname, type(exc).__name__)
                raise ProviderError(
                    "Sursa nu poate fi citită acum; nu confirmăm anunțul sau afilierea."
                ) from None

    @staticmethod
    def identity(address, body, profile=None):
        if not address.startswith("asset:"):
            if body.chain != "solana" or body.contract != address:
                return "identity_mismatch"
            return "matched_subject_address"
        contracts = (profile or {}).get("contracts", {})
        expected = [v for k, v in contracts.items() if PLATFORMS.get(k) == body.chain and v]
        if not expected:
            return "identity_unconfirmed"
        if not any(contract_equal(v, body.contract, body.chain) for v in expected):
            return "identity_mismatch"
        return "provider_reported_contract_match"

    def approvals(self, address):
        with self.store.connect() as db:
            rows = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(
                    "SELECT * FROM source_approvals WHERE address=? ORDER BY id DESC", (address,)
                )
            ]
        return [
            r | {"active": not r["revoked_at"] and 0 <= time.time() - epoch(r["at"]) <= 30 * 86400}
            for r in rows
        ]

    def approve(self, address, body, profile=None):
        host = urlsplit(body.source_url).hostname
        source = SOURCES.get(host)
        if not source or body.relation not in source["relations"]:
            raise ProviderError(
                "Această sursă nu poate susține relația selectată. O redacție nu este emitentul tokenului."
            )
        identity = self.identity(address, body, profile)
        if identity in {"identity_mismatch", "identity_unconfirmed"}:
            raise ProviderError(
                "Contractul/chain-ul nu corespund identității disponibile pentru activ."
            )
        payload = body.model_dump() | {
            "host": host,
            "publisher": source["publisher"],
            "origin": "manual_review",
            "identity_reference": identity,
            "identity_document": profile
            if profile
            else {"source": "tracked_solana_mint", "address": address},
        }
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for previous in db.execute(
                "SELECT id,payload FROM source_approvals WHERE address=? AND revoked_at IS NULL",
                (address,),
            ).fetchall():
                old = json.loads(previous["payload"])
                if (
                    old["host"] == host
                    and old["chain"] == body.chain
                    and contract_equal(old["contract"], body.contract, body.chain)
                ):
                    db.execute(
                        "UPDATE source_approvals SET revoked_at=? WHERE id=?",
                        (utcnow(), previous["id"]),
                    )
            row = db.execute(
                "INSERT INTO source_approvals(address,at,payload) VALUES(?,?,?)",
                (address, utcnow(), json.dumps(payload)),
            )
            return row.lastrowid

    def revoke(self, address, approval_id):
        with self.store.connect() as db:
            return (
                db.execute(
                    "UPDATE source_approvals SET revoked_at=? WHERE id=? AND address=? AND revoked_at IS NULL",
                    (utcnow(), approval_id, address),
                ).rowcount
                > 0
            )

    def approval(self, address, body):
        return next(
            (
                r
                for r in self.approvals(address)
                if r["active"]
                and r["payload"]["host"] == urlsplit(body.source_url).hostname
                and r["payload"]["chain"] == body.chain
                and contract_equal(r["payload"]["contract"], body.contract, body.chain)
            ),
            None,
        )

    async def verify(self, address, body, profile=None, force=True):
        identity = self.identity(address, body, profile)
        payload = body.model_dump() | {
            "identity_reference": identity,
            "identity_document": profile
            if profile
            else {"source": "tracked_solana_mint", "address": address}
            if not address.startswith("asset:")
            else None,
            "verification_version": 1,
            "status": identity,
            "claim_verified": False,
            "endorsement_verified": False,
            "fundamentals_verified": False,
            "relationship": None,
            "approval_id": None,
            "document": None,
            "observations": None,
            "error": None,
        }
        if identity not in {"identity_mismatch", "identity_unconfirmed"}:
            try:
                document = await self.document(body.source_url, force=force)
                observed = inspect_contract(document, body.chain, body.contract)
                approval = self.approval(address, body)
                payload["document"] = {
                    k: document[k]
                    for k in (
                        "url",
                        "publisher",
                        "kind",
                        "title",
                        "published_at_reported",
                        "observed_at",
                        "sha256",
                        "cached",
                    )
                }
                payload["observations"] = observed
                payload["status"] = (
                    "contract_not_found"
                    if not observed["exact_contract_found"]
                    else "negative_context"
                    if observed["negative_context"]
                    else "chain_mismatch"
                    if observed["networks_reported"] and not observed["chain_supported"]
                    else "chain_unconfirmed"
                    if not observed["chain_supported"]
                    else "manual_source_match"
                    if approval
                    else "address_match_requires_review"
                )
                if payload["status"] == "manual_source_match":
                    payload.update(
                        approval_id=approval["id"],
                        relationship=approval["payload"]["relation"],
                        source_review={k: approval[k] for k in ("id", "at", "payload")},
                    )
            except ProviderError as exc:
                payload.update(status="source_unavailable", error=str(exc))
        at = utcnow()
        with self.store.connect() as db:
            row = db.execute(
                "INSERT INTO announcement_checks(address,news_id,at,payload) VALUES(?,?,?,?)",
                (address, body.news_id, at, json.dumps(payload)),
            )
            result = {
                "id": row.lastrowid,
                "at": at,
                "address": address,
                "news_id": body.news_id,
                "payload": payload,
            }
        return self.effective(result)

    def effective(self, record):
        result = dict(record)
        payload = result["payload"]
        status = payload["status"]
        document_at = (payload.get("document") or {}).get("observed_at", record["at"])
        if not 0 <= time.time() - epoch(document_at) <= 86400:
            status = "stale"
        elif status == "manual_source_match":
            active = {r["id"] for r in self.approvals(record["address"]) if r["active"]}
            if payload.get("approval_id") not in active:
                status = "approval_inactive"
        return result | {
            "effective_status": status,
            "official_affiliation": "supported_manual_source"
            if status == "manual_source_match" and payload.get("relationship") == "issuer"
            else "unverified",
        }

    def checks(self, address, news_id=None):
        with self.store.connect() as db:
            query, params = "SELECT * FROM announcement_checks WHERE address=?", [address]
            if news_id is not None:
                query += " AND news_id=?"
                params.append(news_id)
            rows = [
                dict(r) | {"payload": json.loads(r["payload"])}
                for r in db.execute(query + " ORDER BY id DESC LIMIT 20", params)
            ]
        return [self.effective(r) for r in rows]

    def summary(self, address):
        return {
            "checks": self.checks(address),
            "approvals": self.approvals(address),
            "sources": self.catalog(),
            "note": "Potrivirea verifică textul și chain-ul raportat. Relația cu emitentul/listarea cere o evaluare manuală separată a sursei, valabilă 30 de zile. Rezultatele cer reverificare după 24h; nu confirmă adevărul integral, susținerea unei persoane sau profitabilitatea.",
        }

    def news_document(self, news_id):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT at,payload FROM announcement_documents WHERE news_id=? ORDER BY id DESC LIMIT 1",
                (news_id,),
            ).fetchone()
        return (
            {
                "at": row[0],
                **json.loads(row[1]),
                "stale": not 0 <= time.time() - epoch(row[0]) <= 86400,
            }
            if row
            else None
        )

    async def enrich_news(self, news, assets, limit=3):
        """Inspect a bounded set of primary documents, never arbitrary links from RSS."""
        done = 0
        for article in news.listing():
            source = SOURCES.get(urlsplit(article["url"]).hostname)
            previous = self.news_document(article["id"])
            if (
                not source
                or source["kind"] != "primary"
                or (previous and time.time() - epoch(previous["at"]) < 3600)
            ):
                continue
            if done >= limit:
                break
            done += 1
            try:
                document = await self.document(article["url"])
                saved = {
                    k: document[k]
                    for k in (
                        "url",
                        "title",
                        "publisher",
                        "kind",
                        "observed_at",
                        "sha256",
                        "published_at_reported",
                        "text_truncated",
                    )
                }
                saved.update(
                    state="read", excerpt=document["text"][:500], claim_verified=False, error=None
                )
                candidates = contract_candidates(document)
                saved["contract_candidates"] = candidates
                linked = []
                for candidate in [
                    c
                    for c in candidates
                    if c["networks_reported"] == ["solana"] and not c["negative_context"]
                ][:2]:
                    if not news.providers:
                        continue
                    try:
                        market = await news.providers.market(candidate["contract"])
                    except ProviderError:
                        continue
                    if market.address == candidate["contract"]:
                        self.store.add_token(market.address, "source_document")
                        linked.append(
                            market.model_dump()
                            | {"news_relation": "primary_document_contract_mention"}
                        )
                news.replace_matches(
                    article["id"], linked, topic="document:" + urlsplit(article["url"]).hostname
                )
                refreshed = news.listing(news_id=article["id"])
                if refreshed:
                    article = refreshed[0]
                for match in article["matches"][:4]:
                    market = match["market"]
                    profile = None
                    targets = [("solana", market["address"])]
                    if market["address"].startswith("asset:"):
                        try:
                            profile = await assets.profile(market["address"][6:])
                        except ProviderError:
                            continue
                        targets = [
                            (PLATFORMS[k], v)
                            for k, v in profile.get("contracts", {}).items()
                            if k in PLATFORMS and v
                        ][:8]
                        present = [
                            (chain, contract)
                            for chain, contract in targets
                            if inspect_contract(document, chain, contract)["exact_contract_found"]
                        ]
                        targets = present or targets[:1]
                    for chain, contract in targets:
                        try:
                            body = VerificationInput(
                                source_url=article["url"],
                                chain=chain,
                                contract=contract,
                                news_id=article["id"],
                            )
                        except ValueError:
                            continue
                        await self.verify(market["address"], body, profile, force=False)
            except ProviderError as exc:
                saved = {
                    "state": "unavailable",
                    "url": article["url"],
                    "claim_verified": False,
                    "error": str(exc),
                }
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO announcement_documents(news_id,at,payload) VALUES(?,?,?)",
                    (article["id"], utcnow(), json.dumps(saved)),
                )
