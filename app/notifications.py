"""Persistent in-app alerts and explicit, deduplicated Telegram delivery."""

import asyncio
import json
import logging
import time

import httpx

from app.credentials import secret
from app.errors import ProviderError
from app.http_client import read_json
from app.models import epoch, utcnow


def telegram_receipt(result, target):
    """An API receipt must identify the requested chat and a positive message ID."""
    if (
        not isinstance(result, dict)
        or type(result.get("message_id")) is not int
        or result["message_id"] <= 0
        or not isinstance(result.get("chat"), dict)
    ):
        raise ProviderError("Telegram nu a confirmat un mesaj și un destinatar valid.")
    chat = result["chat"]
    if not target or (
        str(chat.get("id")) != target
        and (not target.startswith("@") or "@" + str(chat.get("username", "")).lower() != target.lower())
    ):
        raise ProviderError("Confirmarea Telegram aparține altui destinatar.")
    return result["message_id"]


class Notifications:
    def __init__(self, service, client=None):
        self.service, self.store = service, service.store
        self.client = client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        self.lock = asyncio.Lock()
        self.status = {"state": "unverified", "at": None}
        with self.store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY,news_id INTEGER UNIQUE NOT NULL,at TEXT NOT NULL,seen_at TEXT,payload TEXT NOT NULL,delivery_state TEXT NOT NULL DEFAULT 'pending',delivery_at TEXT,delivery_details TEXT)"
            )

    async def close(self):
        await self.client.aclose()

    def config(self):
        return {
            "telegram_bot_configured": bool(secret("TELEGRAM_BOT_TOKEN")),
            "telegram_destination_configured": bool(secret("TELEGRAM_CHAT_ID")),
            "automatic_delivery": False,
            "status": self.status,
            "note": "Alerte în aplicație; Telegram trimite numai la cererea explicită din interfață. Nicio comandă de tranzacționare.",
        }

    def collect(self):
        for item in self.service.news.listing()[:20]:
            payload = {
                "title": item["title"],
                "url": item["url"],
                "publisher": item["publisher"],
                "published_at": item["published_at"],
                "association": "unverified",
                "note": "Știre de cercetat; afilierea unui token și calitatea investiției cer dovezi separate.",
            }
            with self.store.connect() as db:
                db.execute(
                    "INSERT OR IGNORE INTO alerts(news_id,at,payload) VALUES(?,?,?)",
                    (item["id"], utcnow(), json.dumps(payload)),
                )
        return self.listing()

    def listing(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 100").fetchall()
        return [
            dict(r)
            | {
                "payload": json.loads(r["payload"]),
                "delivery_details": json.loads(r["delivery_details"])
                if r["delivery_details"]
                else None,
            }
            for r in rows
        ]

    def seen(self, alert_id):
        with self.store.connect() as db:
            return (
                db.execute("UPDATE alerts SET seen_at=? WHERE id=?", (utcnow(), alert_id)).rowcount
                > 0
            )

    async def telegram(self, method, payload):
        token = secret("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ProviderError("TELEGRAM_BOT_TOKEN lipsește din mediul procesului.")
        # Bot API authenticates in the path; prevent its HTTP client from logging the URL.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        data = await read_json(
            self.client,
            "POST",
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload,
            attempts=1,
        )
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ProviderError(
                "Telegram a refuzat cererea; verifică botul, destinatarul și drepturile de acces."
            )
        return data.get("result")

    async def connection(self):
        try:
            result = await self.telegram("getMe", {})
            if not isinstance(result, dict) or result.get("is_bot") is not True:
                raise ProviderError("Identitate de bot invalidă.")
            self.status = {
                "state": "ok",
                "at": utcnow(),
                "bot_username": result.get("username"),
                "message_sent": False,
            }
            return self.config()
        except ProviderError as exc:
            self.status = {
                "state": "error",
                "at": utcnow(),
                "error": str(exc),
                "message_sent": False,
            }
            raise

    async def deliver(self, alert_id):
        if self.lock.locked():
            raise ProviderError("O trimitere este deja în curs.")
        if not secret("TELEGRAM_BOT_TOKEN") or not secret("TELEGRAM_CHAT_ID"):
            raise ProviderError(
                "Configurează TELEGRAM_BOT_TOKEN și TELEGRAM_CHAT_ID înainte de livrare."
            )
        async with self.lock:
            with self.store.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM alerts WHERE id=?", (alert_id,)).fetchone()
                if not row or row["delivery_state"] != "pending":
                    raise ProviderError(
                        "Alertă inexistentă, deja trimisă sau cu rezultat ambiguu; nu o retrimitem automat."
                    )
                last = db.execute("SELECT MAX(delivery_at) FROM alerts").fetchone()[0]
                if last and time.time() - epoch(last) < 2:
                    raise ProviderError("Așteaptă două secunde între încercările de livrare.")
                db.execute(
                    "UPDATE alerts SET delivery_state='sending',delivery_at=? WHERE id=?",
                    (utcnow(), alert_id),
                )
            payload = json.loads(row["payload"])
            message = f"PULSE · informație de cercetat\n{payload['title']}\n{payload['publisher']}\n{payload['url']}\nAfiliere token neconfirmată; fără predicție de randament."
            state, details = (
                "delivery_unknown",
                {"note": "Trimitere întreruptă; verifică Telegram înainte de orice retrimitere."},
            )
            try:
                result = await self.telegram(
                    "sendMessage",
                    {
                        "chat_id": secret("TELEGRAM_CHAT_ID", required=True),
                        "text": message[:4000],
                        "link_preview_options": {"is_disabled": True},
                    },
                )
                message_id = telegram_receipt(result, secret("TELEGRAM_CHAT_ID", required=True))
                state, details = "sent", {"message_id": message_id, "read_by_user": False}
            except ProviderError as exc:
                details = {
                    "error": str(exc),
                    "note": "Nu se reîncearcă automat; timeout-ul nu dovedește absența livrării.",
                }
            finally:
                with self.store.connect() as db:
                    db.execute(
                        "UPDATE alerts SET delivery_state=?,delivery_details=? WHERE id=?",
                        (state, json.dumps(details), alert_id),
                    )
            return {"id": alert_id, "delivery_state": state, "details": details}
