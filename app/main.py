import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.models import AddToken, PaperBuy, SignalRequest, solana_address
from app.news import News
from app.paper import Rejected
from app.providers import ProviderError, Providers
from app.service import Service
from app.store import Store

STATIC = Path(__file__).parent / "static"


def create_app(settings=None, providers=None, run_scanner=True, news_factory=None):
    settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(app):
        store = Store(settings)
        sources = providers or Providers(settings)
        app.state.service = Service(settings, store, sources)
        news = (news_factory or News)(store, sources)
        app.state.service.news = news
        task = asyncio.create_task(app.state.service.run()) if run_scanner else None
        news_task = asyncio.create_task(news.run()) if run_scanner else None
        try:
            yield
        finally:
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if news_task:
                news_task.cancel()
                with suppress(asyncio.CancelledError):
                    await news_task
            await news.close()
            await sources.close()

    app = FastAPI(title="Memecoin Research · Paper only", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and urlsplit(origin).netloc != request.headers.get("host")
            ):
                return JSONResponse({"detail": "Cerere cross-origin blocată."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; img-src 'self'; frame-ancestors 'none'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ProviderError)
    async def provider_failure(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(Rejected)
    async def paper_rejected(_, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/status")
    def status(request: Request):
        service = request.app.state.service
        rules = {
            k: str(v)
            for k, v in asdict(settings).items()
            if k not in ("data_dir", "goplus_token", "rpc_url")
        }
        rules["initial_balance"] = str(service.store.initial_balance)
        return {
            "application": "ok",
            "live_execution": False,
            "chain": "solana",
            "providers": service.providers.status,
            "scanner": service.scan_status,
            "rules": rules,
            "discovery": "Latest token profiles: eșantion neexhaustiv și părtinitor",
            "wallet_analytics": "not_implemented",
            "ai_summaries": "not_implemented",
            "news": service.news.status,
            "news_paper_initial_balance": str(service.news_paper.initial_balance),
        }

    @app.get("/api/tokens")
    def tokens(request: Request):
        return request.app.state.service.listing()

    @app.post("/api/tokens", status_code=201)
    async def add_token(body: AddToken, request: Request):
        service = request.app.state.service
        tokens = service.store.tokens()
        if sum(t["watch"] for t in tokens) >= 20 and not any(
            t["address"] == body.address and t["watch"] for t in tokens
        ):
            raise HTTPException(409, "Watchlist limitată la 20 de tokenuri în MVP.")
        service.store.add_token(body.address, "manual", watch=True)
        return await service.refresh(body.address)

    @app.get("/api/tokens/{address}")
    def details(address: str, request: Request):
        service = request.app.state.service
        token = next((t for t in service.listing() if t["address"] == address), None)
        latest = token["snapshot"] if token else None
        if not latest:
            raise HTTPException(404, "Token fără observații; adaugă adresa sau verifică API-urile.")
        return {
            "latest": latest,
            "history": service.store.history(address),
            "watch": token["watch"],
        }

    @app.post("/api/tokens/{address}/unwatch")
    def unwatch(address: str, request: Request):
        request.app.state.service.store.unwatch(address)
        return {"watch": False}

    @app.post("/api/tokens/{address}/refresh")
    async def refresh(address: str, request: Request):
        try:
            solana_address(address)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        service = request.app.state.service
        if not any(t["address"] == address for t in service.store.tokens()):
            raise HTTPException(404, "Adaugă tokenul înainte de refresh.")
        return await service.refresh(address)

    @app.post("/api/tokens/{address}/signal")
    def signal(address: str, request: Request, body: SignalRequest | None = None):
        service = request.app.state.service
        body = body or SignalRequest()
        return service.signal(address, body.account, body.news_id)

    @app.get("/api/news")
    def news_listing(request: Request):
        return request.app.state.service.news.listing()

    @app.post("/api/news/refresh")
    async def news_refresh(request: Request):
        return await request.app.state.service.news.refresh()

    @app.post("/api/scan")
    async def scan(request: Request):
        return await request.app.state.service.scan()

    @app.get("/api/portfolio")
    def portfolio(request: Request, account: Literal["scanner", "news"] = "scanner"):
        return request.app.state.service.portfolio(account)

    @app.post("/api/paper/buy")
    async def paper_buy(body: PaperBuy, request: Request):
        try:
            solana_address(body.address)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        return await request.app.state.service.paper_buy(body)

    @app.post("/api/paper/positions/{position_id}/sell")
    async def paper_sell(
        position_id: int, request: Request, account: Literal["scanner", "news"] = "scanner"
    ):
        return await request.app.state.service.paper_sell(position_id, account)

    return app


app = create_app()
