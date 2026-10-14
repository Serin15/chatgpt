import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__, instance_id
from app.ai_research import AIConfig, AIInput
from app.announcements import ApprovalInput, VerificationInput
from app.assets import Assets, research_case
from app.config import Settings
from app.maintenance import backup, export
from app.models import (
    AddToken,
    AssetBuy,
    AssetWatch,
    PaperBuy,
    SignalRequest,
    solana_address,
    utcnow,
)
from app.news import News
from app.paper import Rejected
from app.providers import ProviderError, Providers
from app.research import EvidenceInput, SourceInput
from app.service import Service
from app.store import Store

STATIC = Path(__file__).parent / "static"


def create_app(
    settings=None,
    providers=None,
    run_scanner=True,
    news_factory=None,
    assets_factory=None,
    trusted_hosts=None,
):
    settings = settings or Settings.from_environment()

    @asynccontextmanager
    async def lifespan(app):
        store = Store(settings)
        sources = providers or Providers(settings)
        app.state.service = Service(settings, store, sources)
        assets = (assets_factory or Assets)(store)
        app.state.service.assets = assets
        assets.held_assets = lambda: [
            p["address"][6:]
            for p in app.state.service.news_paper.portfolio()["positions"]
            if p["address"].startswith("asset:") and not p["closed_at"]
        ]
        news = (news_factory or News)(store, sources)
        news.assets = assets
        news.announcements = app.state.service.research.announcements
        news.ai = app.state.service.research.ai
        app.state.service.news = news
        app.state.workers = {}

        async def supervised(name, fn):
            app.state.workers[name] = {
                "state": "running",
                "started_at": utcnow(),
                "restarts": 0,
                "error": None,
            }
            while True:
                try:
                    await fn()
                    raise RuntimeError("Worker returned unexpectedly")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    record = app.state.workers[name]
                    record.update(state="error", error=type(exc).__name__)
                    record["restarts"] += 1
                    await asyncio.sleep(5)
                    record.update(state="running", error=None)

        tasks = (
            [
                asyncio.create_task(supervised(name, fn))
                for name, fn in [
                    ("scanner", app.state.service.run),
                    ("news", news.run),
                    ("assets", assets.run),
                    ("performance", app.state.service.performance.run),
                ]
            ]
            if run_scanner
            else []
        )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await app.state.service.research.close()
            await assets.close()
            await news.close()
            await sources.close()

    app = FastAPI(title="PULSE Crypto Research · Paper only", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=trusted_hosts or ["127.0.0.1", "localhost", "testserver"],
    )
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
            "ai_summaries": service.research.ai.status(),
            "news": service.news.status,
            "news_paper_initial_balance": str(service.news_paper.initial_balance),
            "crypto_market": service.assets.status,
            "version": __version__,
            "instance_id": instance_id(settings.data_dir),
            "workers": request.app.state.workers,
            "market_sources": service.assets.source_status,
            "performance": service.performance.status,
            "announcement_analysis": service.research.announcements.status,
            "app_id": "pulse_crypto_research",
        }

    @app.get("/api/tokens")
    def tokens(request: Request):
        return request.app.state.service.listing()

    @app.get("/api/assets")
    def asset_listing(request: Request):
        return request.app.state.service.assets.listing()

    @app.get("/api/assets/search")
    async def asset_search(request: Request, q: str = Query(min_length=2, max_length=80)):
        return await request.app.state.service.assets.search(q)

    @app.post("/api/assets/watch")
    async def asset_watch(body: AssetWatch, request: Request):
        return await request.app.state.service.assets.watch(body.asset_id)

    @app.post("/api/assets/{asset_id}/unwatch")
    def asset_unwatch(asset_id: str, request: Request):
        request.app.state.service.assets.unwatch(asset_id)
        return {"watch": False}

    @app.post("/api/assets/refresh")
    async def asset_refresh(request: Request):
        return await request.app.state.service.assets.refresh()

    @app.get("/api/assets/{asset_id}")
    def asset_detail(asset_id: str, request: Request):
        assets = request.app.state.service.assets
        asset = assets.get(asset_id)
        if not asset:
            raise HTTPException(404, "Activ fără observații. Actualizează piața.")
        return {
            "asset": asset,
            "history": assets.history(asset_id),
            "research": research_case(asset),
            "case": request.app.state.service.research.case(asset["address"]),
        }

    @app.get("/api/assets/{asset_id}/venues")
    async def venues(asset_id: str, request: Request):
        assets = request.app.state.service.assets
        if not assets.get(asset_id):
            raise HTTPException(404, "Activ necunoscut")
        return {
            "venues": await assets.venues(asset_id),
            "prelisting_access": "not_established",
            "note": "Acestea sunt piețe raportate, nu acces confirmat înaintea unei listări viitoare.",
        }

    @app.get("/api/assets/{asset_id}/profile")
    async def asset_profile(asset_id: str, request: Request):
        assets = request.app.state.service.assets
        if not assets.get(asset_id):
            raise HTTPException(404, "Activ necunoscut")
        return await assets.profile(asset_id)

    @app.post("/api/assets/{asset_id}/signal")
    async def asset_signal(asset_id: str, request: Request, body: SignalRequest):
        return await request.app.state.service.asset_signal(asset_id, body.news_id, body.thesis)

    @app.post("/api/paper/assets/buy")
    async def asset_buy(body: AssetBuy, request: Request):
        return await request.app.state.service.asset_buy(body)

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
        token = service.store.token(address)
        latest = service.store.latest(address) if token else None
        if latest:
            import time

            from app.analysis import analyze
            from app.models import Market

            latest["analysis"] = analyze(
                Market(**latest["market"]), latest["security"], settings, time.time()
            )
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
    async def signal(address: str, request: Request, body: SignalRequest | None = None):
        service = request.app.state.service
        body = body or SignalRequest()
        if not service.store.token(address):
            raise HTTPException(404, "Adaugă tokenul înainte de semnal.")
        await service.refresh(address)
        return service.signal(address, body.account, body.news_id, body.thesis)

    @app.get("/api/news")
    def news_listing(request: Request, archive: bool = False):
        return request.app.state.service.news.listing(archive=archive)

    @app.post("/api/news/refresh")
    async def news_refresh(request: Request):
        return await request.app.state.service.news.refresh()

    @app.post("/api/news/{news_id}/seen")
    def news_seen(news_id: int, request: Request):
        if not request.app.state.service.news.mark_seen(news_id):
            raise HTTPException(404, "Știre necunoscută")
        return {"seen": True}

    @app.post("/api/scan")
    async def scan(request: Request):
        return await request.app.state.service.scan()

    @app.get("/api/portfolio")
    def portfolio(request: Request, account: Literal["scanner", "news"] = "scanner"):
        return request.app.state.service.portfolio(account)

    @app.get("/api/performance")
    def performance(request: Request, account: Literal["scanner", "news"] = "news"):
        return request.app.state.service.performance.report(account)

    @app.get("/api/export")
    def export_data(request: Request, account: Literal["scanner", "news"] = "news"):
        return JSONResponse(
            export(request.app.state.service, account),
            headers={"Content-Disposition": f'attachment; filename="pulse-{account}.json"'},
        )

    @app.post("/api/backup")
    async def backup_data(request: Request):
        path = await run_in_threadpool(backup, request.app.state.service)
        return FileResponse(path, filename=path.name, media_type="application/zip")

    def known_subject(service, address):
        if address.startswith("asset:"):
            known = service.assets.get(address[6:])
        else:
            known = service.store.token(address)
        if not known:
            raise HTTPException(404, "Adaugă activul în piață/watchlist înainte de dosar.")

    @app.post("/api/research/source")
    async def research_source(body: SourceInput, request: Request):
        return await request.app.state.service.research.source(body)

    @app.get("/api/ai/status")
    def ai_status(request: Request):
        return request.app.state.service.research.ai.status()

    @app.post("/api/ai/config")
    def ai_config(body: AIConfig, request: Request):
        return request.app.state.service.research.ai.configure(body)

    @app.post("/api/ai/connection")
    async def ai_connection(request: Request):
        return await request.app.state.service.research.ai.connection()

    @app.get("/api/research/{address}/ai")
    def ai_history(address: str, request: Request, news_id: int | None = None):
        service = request.app.state.service
        known_subject(service, address)
        check_news_context(service, news_id, address)
        canonical_id = service.news.resolve_id(news_id) if news_id else None
        return {
            "status": service.research.ai.status(),
            "history": service.research.ai.history(address, canonical_id),
        }

    @app.post("/api/research/{address}/ai")
    async def ai_analysis(address: str, body: AIInput, request: Request):
        service = request.app.state.service
        known_subject(service, address)
        check_news_context(service, body.news_id, address)
        context = None
        if body.news_id:
            body = body.model_copy(update={"news_id": service.news.resolve_id(body.news_id)})
            context = service.news.context(body.news_id, address)
        return await service.research.ai.analyze(
            address, body, await contract_profile(service, address), context
        )

    @app.get("/api/research/{address}")
    def research(address: str, request: Request):
        service = request.app.state.service
        known_subject(service, address)
        return service.research.case(address)

    async def contract_profile(service, address):
        if not address.startswith("asset:"):
            return None
        try:
            return await service.assets.profile(address[6:])
        except ProviderError:
            return None

    def check_news_context(service, news_id, address):
        if news_id is None:
            return
        try:
            service.news.context(news_id, address)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None

    @app.post("/api/research/{address}/verify-announcement")
    async def verify_announcement(address: str, body: VerificationInput, request: Request):
        service = request.app.state.service
        known_subject(service, address)
        check_news_context(service, body.news_id, address)
        if body.news_id:
            body = body.model_copy(update={"news_id": service.news.resolve_id(body.news_id)})
        return await service.research.announcements.verify(
            address, body, await contract_profile(service, address)
        )

    @app.post("/api/research/{address}/source-approvals")
    async def approve_source(address: str, body: ApprovalInput, request: Request):
        service = request.app.state.service
        known_subject(service, address)
        check_news_context(service, body.news_id, address)
        if body.news_id:
            body = body.model_copy(update={"news_id": service.news.resolve_id(body.news_id)})
        service.research.announcements.approve(
            address, body, await contract_profile(service, address)
        )
        return service.research.case(address)

    @app.post("/api/research/{address}/source-approvals/{approval_id}/revoke")
    def revoke_source(address: str, approval_id: int, request: Request):
        service = request.app.state.service
        if not service.research.announcements.revoke(address, approval_id):
            raise HTTPException(404, "Evaluare a sursei inexistentă sau retrasă.")
        return service.research.case(address)

    @app.post("/api/research/{address}/evidence")
    def research_evidence(address: str, body: EvidenceInput, request: Request):
        service = request.app.state.service
        known_subject(service, address)
        service.research.add(address, body)
        return service.research.case(address)

    @app.post("/api/research/{address}/evidence/{evidence_id}/revoke")
    def revoke_evidence(address: str, evidence_id: int, request: Request):
        service = request.app.state.service
        if not service.research.revoke(address, evidence_id):
            raise HTTPException(404, "Dovadă activă inexistentă")
        return service.research.case(address)

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


app = create_app(trusted_hosts=["127.0.0.1", "localhost"])
