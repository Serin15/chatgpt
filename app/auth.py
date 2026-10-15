"""Single-owner sessions for hosted deployments. Keys/passwords remain in the process env."""

import hashlib
import hmac
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi.responses import JSONResponse
from pydantic import Field

from app.ai_research import StrictModel
from app.credentials import secret

COOKIE = "pulse_session"


class LoginInput(StrictModel):
    password: str = Field(min_length=1, max_length=1024)


class Auth:
    def __init__(self, store):
        self.store = store
        self.password = (
            secret("PULSE_AUTH_PASSWORD", required=bool(os.getenv("PULSE_AUTH_PASSWORD_FILE")))
            or ""
        )
        self.origin = os.getenv("PULSE_PUBLIC_ORIGIN", "").rstrip("/")
        self.hosted = os.getenv("PULSE_HOSTED") == "1"
        if self.password and len(self.password) < 16:
            raise RuntimeError("PULSE_AUTH_PASSWORD trebuie să conțină cel puțin 16 caractere.")
        if self.hosted and (not self.password or not self.origin.startswith("https://")):
            raise RuntimeError(
                "Găzduirea necesită PULSE_AUTH_PASSWORD și PULSE_PUBLIC_ORIGIN HTTPS."
            )
        if self.origin and (
            urlsplit(self.origin).username
            or urlsplit(self.origin).path
            or not urlsplit(self.origin).hostname
        ):
            raise RuntimeError(
                "PULSE_PUBLIC_ORIGIN trebuie să fie o origine fără path/autentificare."
            )
        self.attempts = {}
        self.login_lock = threading.Lock()
        with store.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS auth_sessions(token_hash TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires_at REAL NOT NULL)"
            )
            if "credential_tag" not in {r[1] for r in db.execute("PRAGMA table_info(auth_sessions)")}:
                db.execute("ALTER TABLE auth_sessions ADD COLUMN credential_tag TEXT")

    def credential_tag(self, token_hash):
        return hmac.new(
            self.password.encode(), ("memescope-session-v1:" + token_hash).encode(), hashlib.sha256
        ).hexdigest()

    @property
    def enabled(self):
        return bool(self.password)

    def session(self, request):
        if not self.enabled:
            return {"authenticated": True, "required": False, "csrf": None}
        token = request.cookies.get(COOKIE, "")
        if not token or len(token) > 200:
            return {"authenticated": False, "required": True, "csrf": None}
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.store.connect() as db:
            row = db.execute(
                "SELECT csrf,credential_tag FROM auth_sessions WHERE token_hash=? AND expires_at>?",
                (token_hash, time.time()),
            ).fetchone()
        if row and not hmac.compare_digest(row[1] or "", self.credential_tag(token_hash)):
            row = None
        return {"authenticated": bool(row), "required": True, "csrf": row[0] if row else None}

    def login(self, request, body):
        # FastAPI dispatches synchronous handlers in multiple threads.
        with self.login_lock:
            return self._login(request, body)

    def _login(self, request, body):
        if not self.enabled:
            return JSONResponse({"authenticated": True, "required": False, "csrf": None})
        peer = request.client.host if request.client else "unknown"
        now = time.time()
        self.attempts = {
            k: [t for t in v if now - t < 300]
            for k, v in self.attempts.items()
            if any(now - t < 300 for t in v)
        }
        attempts = self.attempts.setdefault(peer, [])
        if len(attempts) >= 5:
            return JSONResponse(
                {"detail": "Prea multe autentificări eșuate; așteaptă cinci minute."},
                status_code=429,
            )
        if not hmac.compare_digest(
            hashlib.sha256(body.password.encode()).digest(),
            hashlib.sha256(self.password.encode()).digest(),
        ):
            attempts.append(now)
            return JSONResponse({"detail": "Autentificare invalidă."}, status_code=401)
        self.attempts.pop(peer, None)
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.store.connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE expires_at<=?", (now,))
            db.execute(
                "INSERT INTO auth_sessions(token_hash,csrf,expires_at,credential_tag) VALUES(?,?,?,?)",
                (token_hash, csrf, now + 86400, self.credential_tag(token_hash)),
            )
        response = JSONResponse({"authenticated": True, "required": True, "csrf": csrf})
        response.set_cookie(
            COOKIE,
            token,
            httponly=True,
            secure=self.hosted or self.origin.startswith("https://"),
            samesite="strict",
            max_age=86400,
            path="/",
        )
        return response

    def logout(self, request):
        token = request.cookies.get(COOKIE, "")
        with self.store.connect() as db:
            db.execute(
                "DELETE FROM auth_sessions WHERE token_hash=?",
                (hashlib.sha256(token.encode()).hexdigest(),),
            )
        response = JSONResponse({"authenticated": False})
        response.delete_cookie(
            COOKIE,
            path="/",
            secure=self.hosted or self.origin.startswith("https://"),
            httponly=True,
            samesite="strict",
        )
        return response

    def guard(self, request):
        if (
            not self.enabled
            or request.url.path in {"/", "/healthz", "/api/auth/session", "/api/auth/login"}
            or request.url.path.startswith("/static/")
        ):
            return None
        session = self.session(request)
        if not session["authenticated"]:
            return JSONResponse(
                {"detail": "Autentificare necesară.", "authentication_required": True},
                status_code=401,
            )
        if request.method not in {"GET", "HEAD", "OPTIONS"} and not hmac.compare_digest(
            request.headers.get("x-pulse-csrf", ""), session["csrf"] or ""
        ):
            return JSONResponse({"detail": "Token CSRF invalid."}, status_code=403)
        return None
