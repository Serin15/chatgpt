"""Evidence dossiers. Human reviews and document retrieval never imply automated fact verification."""

import json
import re
import time
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.ai_research import AIResearch
from app.announcements import Announcements, normalized
from app.assets import safe_link
from app.models import epoch, solana_address, utcnow

CHECKS = {
    "identity": "Identitate / contract",
    "announcement": "Anunț original / emitent",
    "product": "Produs funcțional",
    "team": "Echipă",
    "tokenomics": "Tokenomics / vesting",
    "audit": "Audit / permisiuni",
    "liquidity": "Piață / lichiditate",
}


class EvidenceInput(BaseModel):
    category: Literal[
        "identity", "announcement", "product", "team", "tokenomics", "audit", "liquidity"
    ]
    claim: str = Field(min_length=3, max_length=1000)
    status: Literal["unknown", "supported", "disputed"] = "unknown"
    source_url: str | None = Field(default=None, max_length=2000)
    excerpt: str = Field(default="", max_length=2000)
    reviewer_note: str = Field(default="", max_length=2000)
    issuer: str = Field(default="", max_length=200)
    chain: (
        Literal[
            "solana",
            "ethereum",
            "base",
            "polygon",
            "bsc",
            "arbitrum",
            "avalanche",
            "bitcoin",
            "other",
        ]
        | None
    ) = None
    contract: str = Field(default="", max_length=80)
    published_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_evidence(self):
        if self.source_url and not safe_link(self.source_url):
            raise ValueError("Sursa trebuie să fie un URL public HTTPS fără date de autentificare.")
        if self.status != "unknown" and (
            not self.source_url or len(self.reviewer_note.strip()) < 5
        ):
            raise ValueError("O verificare manuală cere sursă și motivul evaluării.")
        if self.contract:
            if self.chain == "solana":
                solana_address(self.contract)
            elif self.chain in {"ethereum", "base", "polygon", "bsc", "arbitrum", "avalanche"}:
                if not re.fullmatch(r"0x[a-fA-F0-9]{40}", self.contract):
                    raise ValueError("Contract EVM invalid.")
            else:
                raise ValueError("Selectează chain-ul contractului.")
        if self.published_at and self.published_at.timestamp() > time.time() + 300:
            raise ValueError(
                "Data publicării nu poate fi în viitor; data unui eveniment este separată."
            )
        return self


class SourceInput(BaseModel):
    url: str = Field(max_length=2000)
    excerpt: str = Field(min_length=20, max_length=2000)


class Research:
    def __init__(self, store, client=None):
        self.store = store
        self.client = client or httpx.AsyncClient(
            timeout=15, follow_redirects=False, headers={"User-Agent": "PulseResearch/0.4"}
        )
        self.announcements = Announcements(store, self.client)
        self.ai = AIResearch(store, self.announcements)
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS research_evidence(id INTEGER PRIMARY KEY,address TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL,revoked_at TEXT);
                CREATE INDEX IF NOT EXISTS evidence_subject ON research_evidence(address,id DESC);
            """)

    async def close(self):
        await self.ai.close()
        await self.client.aclose()

    def add(self, address, evidence):
        payload = evidence.model_dump(mode="json") | {
            "review_origin": "manual",
            "automatically_verified": False,
            "document_match_verifies_claim": False,
        }
        with self.store.connect() as db:
            row = db.execute(
                "INSERT INTO research_evidence(address,at,payload) VALUES(?,?,?)",
                (address, utcnow(), json.dumps(payload)),
            )
            return row.lastrowid

    def revoke(self, address, evidence_id):
        with self.store.connect() as db:
            return (
                db.execute(
                    "UPDATE research_evidence SET revoked_at=? WHERE id=? AND address=? AND revoked_at IS NULL",
                    (utcnow(), evidence_id, address),
                ).rowcount
                > 0
            )

    def case(self, address):
        with self.store.connect() as db:
            records = [
                dict(row) | {"payload": json.loads(row["payload"])}
                for row in db.execute(
                    "SELECT * FROM research_evidence WHERE address=? ORDER BY id DESC", (address,)
                )
            ]
        checks = []
        for key, label in CHECKS.items():
            current = [
                r
                for r in records
                if not r["revoked_at"]
                and r["payload"]["category"] == key
                and (
                    r["payload"]["status"] == "disputed"
                    or 0 <= time.time() - epoch(r["at"]) <= 30 * 86400
                )
            ]
            states = {r["payload"]["status"] for r in current}
            status = (
                "disputed"
                if "disputed" in states
                else "supported_manual"
                if "supported" in states
                else "unknown"
            )
            checks.append({"key": key, "label": label, "status": status})
        statuses = {c["status"] for c in checks}
        verdict = (
            "conflicting_evidence"
            if "disputed" in statuses
            else "manual_review_complete"
            if statuses == {"supported_manual"}
            else "incomplete"
        )
        return {
            "address": address,
            "checks": checks,
            "evidence": records,
            "verdict": verdict,
            "automatically_verified": False,
            "fundamentals_verified": False,
            "announcements": self.announcements.summary(address),
            "ai": self.ai.history(address),
            "note": "Confirmările manuale expiră după 30 de zile; disputele rămân până la retragere. Un citat găsit într-un document nu demonstrează adevărul afirmației, afilierea sau profitabilitatea.",
        }

    async def source(self, body):
        document = await self.announcements.document(body.url, force=True)
        found = normalized(body.excerpt).casefold() in document["text"].casefold()
        return {
            "url": body.url,
            "publisher": document["publisher"],
            "observed_at": document["observed_at"],
            "sha256": document["sha256"],
            "text_truncated": document["text_truncated"],
            "excerpt_found": found,
            "claim_verified": False,
            "endorsement_verified": False,
            "note": "Verifică doar prezența textului. Evaluarea afirmației rămâne manuală.",
        }
