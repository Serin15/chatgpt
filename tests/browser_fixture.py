"""Explicit fake market server for isolated browser tests. Never used by the product."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from app.ai_research import AIResearch
from app.config import Settings
from app.main import create_app
from app.research import Research
from tests.conftest import ADDRESS
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders

app = create_app(
    Settings(data_dir=Path(os.environ["BROWSER_TEST_DATA"])),
    NewsFixtureProviders(),
    run_scanner=False,
    news_factory=FixtureNews,
    assets_factory=FixtureAssets,
)

if os.environ.get("ANNOUNCEMENT_FIXTURE") == "1" or os.environ.get("AI_FIXTURE") == "1":
    original_lifespan = app.router.lifespan_context

    def document_response(request):
        text = f"Solana contract {ADDRESS}. Explicit isolated source fixture."
        if request.url.path.endswith("negative"):
            text = f"This is not our token on Solana. Beware of this fake token: {ADDRESS}"
        return httpx.Response(
            200,
            text=f"<html><head><title>Isolated announcement fixture</title></head><main><p>{text}</p></main></html>",
            headers={"content-type": "text/html"},
        )

    @asynccontextmanager
    async def fixture_lifespan(app):
        async with original_lifespan(app):
            service = app.state.service
            await service.research.close()
            service.research = Research(
                service.store, httpx.AsyncClient(transport=httpx.MockTransport(document_response))
            )
            service.news.announcements = service.research.announcements
            service.news.ai = service.research.ai
            if os.environ.get("AI_FIXTURE") == "1":
                from tests.test_ai_research import answer, transport_result

                def model_response(request):
                    if request.method == "GET":
                        return transport_result(request)
                    import json

                    body = json.loads(request.content)
                    bundle = json.loads(body["messages"][1]["content"])
                    return transport_result(
                        request, answer(quote=bundle["sources"][0]["content"][:300])
                    )

                await service.research.ai.close()
                service.research.ai = AIResearch(
                    service.store,
                    service.research.announcements,
                    httpx.AsyncClient(transport=httpx.MockTransport(model_response)),
                )
                service.news.ai = service.research.ai
            yield

    app.router.lifespan_context = fixture_lifespan
