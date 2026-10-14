import asyncio
import json
import sqlite3
import zipfile
from io import BytesIO

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.ai_evaluation import load_cases, metrics
from app.ai_research import (
    AIConfig,
    AIInput,
    AIResearch,
    relationship_gate,
    validate_interpretation,
)
from app.main import create_app
from app.providers import ProviderError
from app.research import Research
from tests.conftest import ADDRESS, OTHER
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders, article

URL = "https://solana.com/ai-fixture"
CONTENT = f"Solana contract {ADDRESS}. This is a document for an isolated test, not an actual token announcement."


def test_corpus_provenance_and_evaluation_do_not_hide_failures_or_false_associations():
    cases = load_cases()
    assert len(cases) == 12
    assert sum(c["origin"] == "observed_excerpt" for c in cases) == 2
    report = metrics(cases, [])
    assert report["accuracy"] == 0 and report["invalid_or_failed"] == 12
    assert report["positive_precision"] is None
    negative = next(c for c in cases if c["id"] == "synthetic-denial")
    report = metrics(
        [negative],
        [
            {
                "id": negative["id"],
                "state": "completed",
                "relationship": {"effective": "issuer_announcement"},
            }
        ],
    )
    assert report["false_positive_associations"] == 1 and report["accuracy"] == 0


def answer(quote=CONTENT, relationship="insufficient_evidence"):
    statement = {
        "text_ro": "Documentul descrie un exemplu; nu stabilește emiterea unui token nou.",
        "citations": [{"source_id": "D1", "quote": quote}],
    }
    return {
        "event_summary": statement,
        "relationship": relationship,
        "relationship_reason": statement,
        "facts": [statement],
        "research_questions": ["Există un anunț original de emitere pentru contractul ales?"],
        "risks": ["Potrivirea textului nu confirmă afilierea sau adevărul afirmației."],
    }


def transport_result(request, output=None, status=200):
    if request.method == "GET":
        return httpx.Response(200, json={"models": [{"name": "test-model"}]})
    return httpx.Response(
        status,
        json={
            "done": True,
            "message": {"content": json.dumps(output or answer())},
            "eval_count": 100,
        },
    )


def make_engine(store, handler=None, content=CONTENT):
    research = Research(
        store,
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    text=f"<main><p>{content}</p></main>",
                    headers={"content-type": "text/html"},
                )
            )
        ),
    )
    engine = AIResearch(
        store,
        research.announcements,
        httpx.AsyncClient(transport=httpx.MockTransport(handler or transport_result)),
    )
    engine.configure(AIConfig(provider="ollama", model="test-model", daily_request_limit=2))
    return research, engine


@pytest.fixture(autouse=True)
def clean_ai_environment(monkeypatch):
    for key in ("PULSE_AI_PROVIDER", "PULSE_AI_MODEL", "PULSE_AI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)


@pytest.mark.parametrize(
    "raw",
    [
        {"provider": "openai", "model": "../responses"},
        {"provider": "openai", "model": "gpt-foo", "api_key": "never-store-this"},
        {"provider": "ollama", "model": ""},
        {"provider": "other", "model": "x"},
        {"daily_request_limit": 0},
    ],
)
def test_invalid_or_secret_bearing_config_rejected(raw):
    with pytest.raises(ValidationError):
        AIConfig(**raw)


@pytest.mark.parametrize(
    "change",
    [
        {"chain": "solana"},
        {"contract": ADDRESS},
        {"chain": "base", "contract": ADDRESS},
        {"chain": "invented", "contract": ADDRESS},
    ],
)
def test_partial_or_invalid_identity_rejected(change):
    with pytest.raises(ValidationError):
        AIInput(source_url=URL, **change)


def test_citations_do_not_accept_fake_sources_substrings_or_extra_truth_fields():
    bundle = {"sources": [{"id": "D1", "content": CONTENT}]}
    assert validate_interpretation(answer(), bundle)
    for raw in [
        answer(quote="invented quote that does not exist"),
        answer() | {"claim_verified": True},
    ]:
        with pytest.raises(ValueError):
            validate_interpretation(raw, bundle)
    raw = answer()
    raw["event_summary"]["citations"][0]["source_id"] = "N1"
    with pytest.raises(ValueError):
        validate_interpretation(raw, bundle)


def test_trade_promises_rejected_but_reported_competition_multiplier_allowed():
    bundle = {"sources": [{"id": "D1", "content": CONTENT}]}
    raw = answer()
    raw["risks"] = ["Acest token va face 100x"]
    with pytest.raises(ValueError):
        validate_interpretation(raw, bundle)
    raw["risks"] = ["O pondere 3x a volumului într-un concurs nu reprezintă un randament."]
    assert validate_interpretation(raw, bundle)


@pytest.mark.parametrize(
    "technical,source",
    [
        (
            {
                "identity": "identity_mismatch",
                "observations": {"exact_contract_found": True, "chain_supported": True},
            },
            {"kind": "primary", "allowed_relations": ["issuer"]},
        ),
        (
            {
                "identity": "matched_subject_address",
                "observations": {"exact_contract_found": True, "chain_supported": False},
            },
            {"kind": "primary", "allowed_relations": ["issuer"]},
        ),
        (
            {
                "identity": "matched_subject_address",
                "observations": {
                    "exact_contract_found": True,
                    "chain_supported": True,
                    "negative_context": True,
                },
            },
            {"kind": "primary", "allowed_relations": ["issuer"]},
        ),
        (
            {
                "identity": "matched_subject_address",
                "observations": {"exact_contract_found": True, "chain_supported": True},
            },
            {"kind": "editorial", "allowed_relations": []},
        ),
        (
            {
                "identity": "matched_subject_address",
                "observations": {"exact_contract_found": True, "chain_supported": True},
            },
            {"kind": "primary", "allowed_relations": ["listing"]},
        ),
    ],
)
def test_positive_model_relation_cannot_override_identity_chain_denial_or_source_role(
    technical, source
):
    gate = relationship_gate(
        answer(relationship="issuer_announcement"), {"technical": technical, "sources": [source]}
    )
    assert gate["effective"] == "insufficient_evidence" and gate["limitations"]


def test_analysis_records_evidence_and_usage_without_secret_or_portfolio(store):
    async def run():
        requests = []

        def handler(request):
            requests.append(request)
            return transport_result(request)

        research, engine = make_engine(store, handler)
        try:
            assert (await engine.connection())["generation_tested"] is False
            record = await engine.analyze(ADDRESS, AIInput(source_url=URL, news_id=7))
            assert record["state"] == "completed"
            p = record["payload"]
            assert p["citations_checked"] and p["bundle"]["sources"][0]["sha256"]
            assert p["bundle"]["subject"]["contract"] == ADDRESS
            assert not any(
                p[k] for k in ("claim_verified", "endorsement_verified", "fundamentals_verified")
            )
            sent = json.loads(requests[-1].content)
            assert sent["stream"] is False and sent["format"]["additionalProperties"] is False
            assert "portfolio" not in sent["messages"][1]["content"]
            assert len(engine.history(ADDRESS, 7)) == 1 and engine.history(ADDRESS, 8) == []
            assert engine.news_summary(ADDRESS, 7)["state"] == "completed"
            assert store.portfolio()["orders"] == []
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


def test_failed_generation_invalid_citation_and_quota_survive_restart(store):
    async def run():
        research, engine = make_engine(
            store,
            lambda r: transport_result(
                r, answer(quote="This quote has never appeared in the document")
            ),
        )
        try:
            for _ in range(2):
                result = await engine.analyze(ADDRESS, AIInput(source_url=URL))
                assert result["state"] == "error" and result["payload"]["interpretation"] is None
            restarted = AIResearch(store, research.announcements, engine.client)
            with pytest.raises(ProviderError, match="Limita zilnică"):
                await restarted.analyze(ADDRESS, AIInput(source_url=URL))
            assert restarted.status()["requests_today"] == 2
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


def test_failure_after_success_does_not_replace_unknown_with_old_interpretation(store):
    async def run():
        responses = iter(
            [transport_result(httpx.Request("POST", "http://test")), httpx.Response(503)]
        )
        research, engine = make_engine(store, lambda r: next(responses))
        try:
            assert (await engine.analyze(ADDRESS, AIInput(source_url=URL)))["state"] == "completed"
            assert (await engine.analyze(ADDRESS, AIInput(source_url=URL)))["state"] == "error"
            latest, previous = engine.history(ADDRESS)
            assert latest["payload"]["interpretation"] is None
            assert previous["payload"]["interpretation"] and engine.status()["state"] == "error"
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


def test_invalid_configuration_is_explicit_and_can_be_repaired(store, monkeypatch):
    async def run():
        research, engine = make_engine(store)
        try:
            monkeypatch.setenv("PULSE_AI_PROVIDER", "invalid")
            assert engine.status()["configuration_error"] and not engine.status()["configured"]
            with pytest.raises(ProviderError, match="variabilele de mediu"):
                engine.configure(AIConfig())
            monkeypatch.delenv("PULSE_AI_PROVIDER")
            with store.connect() as db:
                db.execute("UPDATE ai_configuration SET payload='broken'")
            assert engine.status()["configuration_error"]
            assert not engine.configure(AIConfig())["configuration_error"]
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429, text="sensitive provider error must not be forwarded"),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, content=b"x" * 1_000_001),
    ],
)
def test_provider_failure_is_explicit_and_does_not_show_stale_success(store, response):
    async def run():
        research, engine = make_engine(store, lambda r: response)
        try:
            result = await engine.analyze(ADDRESS, AIInput(source_url=URL))
            assert result["state"] == "error" and result["payload"]["interpretation"] is None
            assert "sensitive" not in json.dumps(result)
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


def test_timeout_is_saved_and_concurrent_call_does_not_start_a_second_generation(store):
    async def run():
        async def fail(request):
            raise httpx.ReadTimeout("sensitive key must not leak", request=request)

        research, engine = make_engine(store, fail)
        try:
            async with engine.lock:
                with pytest.raises(ProviderError, match="schimba motorul"):
                    engine.configure(AIConfig())
                with pytest.raises(ProviderError, match="deja în curs"):
                    await engine.analyze(ADDRESS, AIInput(source_url=URL))
            result = await engine.analyze(ADDRESS, AIInput(source_url=URL))
            assert result["state"] == "error" and "sensitive" not in result["payload"]["error"]
            assert engine.status()["requests_today"] == 1
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1", "https://solana.com.attacker.org/fake", "https://example.org/news"]
)
def test_unapproved_documents_never_reach_model(store, url):
    async def run():
        research, engine = make_engine(store, lambda r: pytest.fail("Unexpected model request"))
        try:
            with pytest.raises(ProviderError):
                await engine.analyze(ADDRESS, AIInput(source_url=url))
            assert engine.status()["requests_today"] == 0
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


def test_openai_protocol_secret_handling_and_missing_key(store, monkeypatch):
    async def run():
        captured = []

        def handler(request):
            captured.append(request)
            return httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": json.dumps(answer())}],
                        }
                    ],
                    "usage": {"input_tokens": 20, "output_tokens": 30},
                },
            )

        research, engine = make_engine(store, handler)
        engine.configure(AIConfig(provider="openai", model="test-api-model"))
        try:
            with pytest.raises(ProviderError, match="PULSE_AI_API_KEY"):
                await engine.analyze(ADDRESS, AIInput(source_url=URL))
            monkeypatch.setenv("OPENAI_API_KEY", "secret-fixture-never-real")
            result = await engine.analyze(ADDRESS, AIInput(source_url=URL))
            assert result["state"] == "completed"
            sent = json.loads(captured[0].content)
            assert sent["store"] is False and "tools" not in sent
            assert sent["text"]["format"]["strict"] is True
            assert captured[0].headers["Authorization"] == "Bearer secret-fixture-never-real"
            assert "secret-fixture" not in json.dumps(result) + json.dumps(engine.status())
        finally:
            await engine.close()
            await research.close()

    asyncio.run(run())


def test_api_signal_backup_and_news_keep_scoped_immutable_ai(settings):
    app = create_app(
        settings,
        NewsFixtureProviders(),
        run_scanner=False,
        news_factory=FixtureNews,
        assets_factory=FixtureAssets,
    )
    with TestClient(app) as client:
        service = app.state.service
        research, engine = make_engine(service.store)
        old_ai = service.research.ai
        service.research.ai = engine
        service.news.ai = engine
        engine.announcements = research.announcements
        try:
            assert client.get("/api/ai/status").json()["provider"] == "ollama"
            assert (
                client.post(
                    "/api/ai/config", json={"provider": "openai", "model": "x", "api_key": "no"}
                ).status_code
                == 422
            )
            assert (
                client.post(
                    "/api/ai/config",
                    json={"provider": "disabled"},
                    headers={"Origin": "https://attacker.org"},
                ).status_code
                == 403
            )
            assert client.post("/api/ai/connection", json={}).status_code == 200
            assert (
                client.post(f"/api/research/{OTHER}/ai", json={"source_url": URL}).status_code
                == 404
            )
            client.post("/api/news/refresh")
            assert client.post("/api/tokens", json={"address": ADDRESS}).status_code == 201
            news_id = client.get("/api/news").json()[0]["id"]
            body = {"source_url": URL, "news_id": news_id}
            result = client.post(f"/api/research/{ADDRESS}/ai", json=body).json()
            assert result.get("state") == "completed", result
            assert (
                client.get("/api/news").json()[0]["matches"][0]["ai_analysis"]["id"] == result["id"]
            )
            other_id = service.news.save(
                article("trump", "Trump launched another unrelated fixture")
            )
            assert (
                client.post(
                    f"/api/research/{ADDRESS}/ai", json={"source_url": URL, "news_id": other_id}
                ).status_code
                == 409
            )
            saved = client.post(
                f"/api/tokens/{ADDRESS}/signal",
                json={
                    "account": "news",
                    "news_id": news_id,
                    "thesis": "Test immutability before any paper order",
                },
            )
            assert saved.status_code == 200
            export = client.get("/api/export?account=news").json()
            captured = export["signals"][0]["evidence"]["ai_context"][0]
            assert captured["id"] == result["id"]
            with service.store.connect() as db:
                db.execute("UPDATE ai_attempts SET state='error' WHERE id=?", (result["id"],))
            assert (
                client.get("/api/export?account=news").json()["signals"][0]["evidence"][
                    "ai_context"
                ][0]["state"]
                == "completed"
            )
            archive = client.post("/api/backup", json={})
            with zipfile.ZipFile(BytesIO(archive.content)) as zipped:
                path = settings.data_dir / "restored-ai.sqlite3"
                path.write_bytes(zipped.read("research.sqlite3"))
            with sqlite3.connect(path) as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert db.execute("SELECT count(*) FROM ai_attempts").fetchone()[0] == 1
            assert export["portfolio"]["cash"] == "500" and export["portfolio"]["orders"] == []
        finally:
            asyncio.run(old_ai.close())
            asyncio.run(research.close())


def test_evaluation_rejects_document_overlap_between_partitions(tmp_path):
    from app.ai_evaluation import CORPUS

    corpus = json.loads(CORPUS.read_text())
    development = next(c for c in corpus["cases"] if c["partition"] == "development")
    heldout = next(c for c in corpus["cases"] if c["partition"] == "test")
    heldout["group"] = development["group"]
    path = tmp_path / "overlap.json"
    path.write_text(json.dumps(corpus))
    with pytest.raises(ValueError, match="Data leakage"):
        load_cases(path)
