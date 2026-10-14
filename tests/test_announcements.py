import asyncio
import json
import sqlite3
import time
import zipfile
from datetime import UTC, datetime
from io import BytesIO

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.announcements import ApprovalInput, DocumentReader, VerificationInput, inspect_contract
from app.main import create_app
from app.research import Research
from tests.conftest import ADDRESS, OTHER
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders, article

URL = "https://solana.com/explicit-fixture"
EVM = "0x" + "a" * 40
DIFFERENT = "0x" + "b" * 40


def target(**kwargs):
    return VerificationInput(
        **({"source_url": URL, "chain": "solana", "contract": ADDRESS} | kwargs)
    )


def review(**kwargs):
    return ApprovalInput(
        **(
            target().model_dump()
            | {
                "relation": "issuer",
                "proof_url": "https://example.org/independently-reviewed-identity",
                "reviewer_note": "Manually reviewed the issuer identity and this exact mint.",
                "reviewed": True,
            }
            | kwargs
        )
    )


def html(text):
    return f"<html><head><title>Explicit test document</title></head><body><main><p>{text}</p></main></body></html>"


def document(content):
    reader = DocumentReader(URL)
    reader.feed(content)
    return reader.document()


@pytest.mark.parametrize(
    "content,found",
    [
        (html(f"Solana contract: {ADDRESS}"), True),
        (html(f"Solana contract: {ADDRESS}XYZ"), False),
        (html(f"Solana contract: {OTHER}"), False),
        (html("Solana project with the same token name"), False),
        (html("No contract") + f"<script>Solana {ADDRESS}</script>", False),
        (html(f"Visible text <span hidden>Solana {ADDRESS}</span>"), False),
        (html(f"Visible text <span style='display:none'>Solana {ADDRESS}</span>"), False),
        (html(f"<span aria-hidden style>Solana contract {ADDRESS}</span>"), True),
        (
            f"<html><head><title>{ADDRESS}</title></head><header>{ADDRESS}</header><main><p>No contract</p></main></html>",
            False,
        ),
        (html(f"Solana <a href='https://solscan.io/token/{ADDRESS}'>contract</a>"), True),
        (html(f"<a href='https://solscan.io/token/{ADDRESS}?cluster=devnet'>devnet</a>"), False),
    ],
)
def test_document_match_does_not_use_names_substrings_or_hidden_text(content, found):
    observed = inspect_contract(document(content), "solana", ADDRESS)
    assert observed["exact_contract_found"] is found


def test_evm_network_context_is_scoped_to_table_row():
    content = f"<main><table><tr><td>Ethereum</td><td>{EVM}</td></tr><tr><td>Base</td><td>{DIFFERENT}</td></tr></table></main>"
    observed = inspect_contract(document(content), "base", EVM.upper().replace("0X", "0x"))
    assert observed["exact_contract_found"]
    assert observed["networks_reported"] == ["ethereum"]
    assert not observed["chain_supported"]


def test_match_requires_manual_source_review_and_revocation_is_effective(store):
    async def run():
        research = Research(
            store,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(
                        200,
                        text=html(f"Solana contract: {ADDRESS}"),
                        headers={"content-type": "text/html"},
                    )
                )
            ),
        )
        engine = research.announcements
        try:
            result = await engine.verify(ADDRESS, target())
            assert result["effective_status"] == "address_match_requires_review"
            assert result["official_affiliation"] == "unverified"
            approval_id = engine.approve(ADDRESS, review())
            result = await engine.verify(ADDRESS, target())
            assert result["effective_status"] == "manual_source_match"
            assert result["official_affiliation"] == "supported_manual_source"
            assert (
                not result["payload"]["claim_verified"]
                and not result["payload"]["endorsement_verified"]
            )
            snapshot = json.loads(json.dumps(result))
            assert engine.revoke(ADDRESS, approval_id)
            assert engine.checks(ADDRESS)[0]["effective_status"] == "approval_inactive"
            assert snapshot["effective_status"] == "manual_source_match"
        finally:
            await research.close()

    asyncio.run(run())


def test_new_review_replaces_previous_review_for_the_same_identity_scope(store):
    research = Research(store)
    try:
        engine = research.announcements
        first = engine.approve(ADDRESS, review())
        second = engine.approve(
            ADDRESS, review(reviewer_note="A newer manual review of the same source and mint.")
        )
        approvals = engine.approvals(ADDRESS)
        assert sum(r["active"] for r in approvals) == 1
        assert next(r for r in approvals if r["id"] == first)["revoked_at"]
        assert engine.approval(ADDRESS, target())["id"] == second
    finally:
        asyncio.run(research.close())


@pytest.mark.parametrize(
    "text,chain,contract,profile,expected",
    [
        (
            f"Solana has not issued this fake token: {ADDRESS}",
            "solana",
            ADDRESS,
            None,
            "negative_context",
        ),
        (
            f"Not our token: <a href='https://solscan.io/token/{ADDRESS}'>this fake coin</a>",
            "solana",
            ADDRESS,
            None,
            "negative_context",
        ),
        ("Solana announcement with no address", "solana", ADDRESS, None, "contract_not_found"),
        (f"Contract {ADDRESS}", "solana", ADDRESS, None, "chain_unconfirmed"),
        (f"Ethereum contract {EVM}", "base", EVM, {"contracts": {"base": EVM}}, "chain_mismatch"),
        (f"Base contract {EVM}", "base", EVM, {"contracts": {}}, "identity_unconfirmed"),
        (
            f"Base contract {EVM}",
            "base",
            EVM,
            {"contracts": {"base": DIFFERENT}},
            "identity_mismatch",
        ),
    ],
)
def test_negative_missing_or_mismatched_evidence_never_confirms_affiliation(
    store, text, chain, contract, profile, expected
):
    async def run():
        research = Research(
            store,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(
                        200, text=html(text), headers={"content-type": "text/html"}
                    )
                )
            ),
        )
        address = ADDRESS if chain == "solana" else "asset:fixture"
        try:
            if chain == "solana":
                research.announcements.approve(address, review())
            result = await research.announcements.verify(
                address, target(chain=chain, contract=contract), profile
            )
            assert result["effective_status"] == expected
            assert result["official_affiliation"] == "unverified"
        finally:
            await research.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/private",
        "https://solana.com.evil.example/path",
        "https://evil.solana.com/path",
        "https://example.org/path",
    ],
)
def test_unapproved_hosts_are_not_requested(store, url):
    async def run():
        def handler(request):
            raise AssertionError("An unapproved host must never be fetched")

        research = Research(store, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            result = await research.announcements.verify(ADDRESS, target(source_url=url))
            assert result["effective_status"] == "source_unavailable"
        finally:
            await research.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(302, headers={"location": "https://127.0.0.1/private"}),
        httpx.Response(200, content=b"x" * 2_000_001, headers={"content-type": "text/html"}),
        httpx.Response(200, content=b"binary", headers={"content-type": "application/pdf"}),
        httpx.Response(503),
    ],
)
def test_redirects_oversize_invalid_formats_and_errors_remain_unknown(store, response):
    async def run():
        calls = []

        def handler(request):
            calls.append(str(request.url))
            return response

        research = Research(
            store, httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)
        )
        try:
            research.announcements.approve(ADDRESS, review())
            result = await research.announcements.verify(ADDRESS, target())
            assert result["effective_status"] == "source_unavailable"
            assert result["official_affiliation"] == "unverified" and calls == [URL]
        finally:
            await research.close()

    asyncio.run(run())


def test_manual_recheck_fetches_new_document_and_does_not_reuse_old_success(store):
    async def run():
        calls = []

        def handler(request):
            calls.append(request)
            return (
                httpx.Response(
                    200,
                    text=html(f"Solana contract {ADDRESS}"),
                    headers={"content-type": "text/html"},
                )
                if len(calls) == 1
                else httpx.Response(503)
            )

        research = Research(store, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        try:
            engine = research.announcements
            engine.approve(ADDRESS, review())
            assert (await engine.verify(ADDRESS, target()))[
                "effective_status"
            ] == "manual_source_match"
            assert (await engine.verify(ADDRESS, target()))[
                "effective_status"
            ] == "source_unavailable"
            assert (
                engine.checks(ADDRESS)[0]["official_affiliation"] == "unverified"
                and len(calls) == 2
            )
        finally:
            await research.close()

    asyncio.run(run())


def test_expired_reviews_and_documents_require_recheck(store):
    async def run():
        research = Research(
            store,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(
                        200,
                        text=html(f"Solana contract {ADDRESS}"),
                        headers={"content-type": "text/html"},
                    )
                )
            ),
        )
        try:
            engine = research.announcements
            engine.approve(ADDRESS, review())
            await engine.verify(ADDRESS, target())
            with store.connect() as db:
                db.execute(
                    "UPDATE source_approvals SET at=?",
                    (datetime.fromtimestamp(time.time() - 31 * 86400, UTC).isoformat(),),
                )
            assert engine.checks(ADDRESS)[0]["effective_status"] == "approval_inactive"
            record = engine.checks(ADDRESS)[0]
            record["payload"]["document"]["observed_at"] = datetime.fromtimestamp(
                time.time() - 86401, UTC
            ).isoformat()
            assert engine.effective(record)["effective_status"] == "stale"
        finally:
            await research.close()

    asyncio.run(run())


def test_editorial_cannot_be_approved_as_issuer_and_review_is_explicit(store):
    research = Research(store)
    try:
        from app.providers import ProviderError

        with pytest.raises(ProviderError):
            research.announcements.approve(
                ADDRESS, review(source_url="https://www.coindesk.com/fixture")
            )
        with pytest.raises(ValidationError):
            review(reviewed=False)
    finally:
        asyncio.run(research.close())


def test_api_scopes_results_to_news_and_preserves_signal_evidence(settings):
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    with TestClient(app) as client:
        service = app.state.service
        client.post("/api/tokens", json={"address": ADDRESS})
        first = service.news.save(article())
        second = service.news.save(
            article(title="Another fixture")
            | {"url": "https://example.org/second", "fingerprint": "second"}
        )
        service.news.save_matches(first, [{"address": ADDRESS, "name": "Fixture", "symbol": "F"}])
        service.news.save_matches(second, [{"address": ADDRESS, "name": "Fixture", "symbol": "F"}])
        mock = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    200,
                    text=html(f"Solana contract {ADDRESS}"),
                    headers={"content-type": "text/html"},
                )
            )
        )
        service.research.announcements.client = mock
        try:
            assert client.post(
                f"/api/research/{ADDRESS}/source-approvals", json=review().model_dump()
            ).is_success
            response = client.post(
                f"/api/research/{ADDRESS}/verify-announcement",
                json=target(news_id=first).model_dump(),
            )
            assert response.json()["effective_status"] == "manual_source_match"
            articles = {a["id"]: a for a in client.get("/api/news").json()}
            assert (
                articles[first]["matches"][0]["official_affiliation"] == "supported_manual_source"
            )
            assert articles[second]["matches"][0]["official_affiliation"] == "unverified"
            signal = client.post(
                f"/api/tokens/{ADDRESS}/signal", json={"account": "news", "news_id": first}
            ).json()
            context = json.loads(signal["evidence"])
            assert (
                context["news_context"]["match"]["announcement_check"]["effective_status"]
                == "manual_source_match"
            )
            assert client.post(
                f"/api/research/{ADDRESS}/source-approvals/1/revoke", json={}
            ).is_success
            assert (
                client.get(f"/api/research/{ADDRESS}").json()["announcements"]["checks"][0][
                    "effective_status"
                ]
                == "approval_inactive"
            )
            assert (
                context["research_context"]["announcements"]["checks"][0]["effective_status"]
                == "manual_source_match"
            )
            assert (
                client.post(
                    f"/api/research/{ADDRESS}/verify-announcement",
                    json=target(news_id=9999).model_dump(),
                ).status_code
                == 409
            )
            assert client.get("/api/portfolio?account=news").json()["orders"] == []
            backup = client.post("/api/backup")
            with zipfile.ZipFile(BytesIO(backup.content)) as archive:
                restored = settings.data_dir / "restored"
                archive.extractall(restored)
            with sqlite3.connect(restored / "research.sqlite3") as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert db.execute("SELECT COUNT(*) FROM announcement_checks").fetchone()[0] == 1
                assert db.execute("SELECT revoked_at FROM source_approvals").fetchone()[0]
            with sqlite3.connect(restored / "news_paper/research.sqlite3") as db:
                evidence = json.loads(db.execute("SELECT evidence FROM signals").fetchone()[0])
                assert (
                    evidence["research_context"]["announcements"]["checks"][0]["effective_status"]
                    == "manual_source_match"
                )
        finally:
            asyncio.run(mock.aclose())
    with TestClient(
        create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)
    ) as client:
        assert (
            client.get(f"/api/research/{ADDRESS}").json()["announcements"]["checks"][0][
                "effective_status"
            ]
            == "approval_inactive"
        )


def test_automatic_primary_document_collection_is_bounded_and_never_reads_aggregators(store):
    async def run():
        from app.news import News

        calls = []

        def handler(request):
            calls.append(str(request.url))
            return httpx.Response(
                200, text=html(f"Solana contract {ADDRESS}"), headers={"content-type": "text/html"}
            )

        research = Research(store, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        news = News(store, None)
        news.announcements = research.announcements
        try:
            for i, url in enumerate(
                ["https://example.org/aggregator"]
                + [f"https://solana.com/fixture/{i}" for i in range(5)]
            ):
                news_id = news.save(
                    article(title=f"Explicit source fixture {i}")
                    | {"url": url, "fingerprint": str(i)}
                )
                news.save_matches(
                    news_id, [{"address": ADDRESS, "name": "Fixture", "symbol": "FIXTURE"}]
                )
            await research.announcements.enrich_news(news, None, limit=2)
            assert len(calls) == 2 and all(url.startswith("https://solana.com/") for url in calls)
            read = [n for n in news.listing() if n["document_analysis"]]
            assert len(read) == 2 and all(n["document_analysis"]["state"] == "read" for n in read)
            assert all(
                n["matches"][0]["announcement_check"]["effective_status"]
                == "address_match_requires_review"
                for n in read
            )
            await research.announcements.enrich_news(news, None, limit=2)
            assert len(calls) == 4
        finally:
            await research.close()
            await news.close()

    asyncio.run(run())


def test_primary_document_can_discover_exact_solana_mint_without_a_name_match(store):
    async def run():
        from app.news import News

        research = Research(
            store,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(
                        200,
                        text=html(f"On Solana the contract is {ADDRESS}"),
                        headers={"content-type": "text/html"},
                    )
                )
            ),
        )
        news = News(store, NewsFixtureProviders())
        news.announcements = research.announcements
        try:
            news_id = news.save(
                article(title="Original source launch fixture")
                | {"url": URL, "fingerprint": "original"}
            )
            assert news.listing()[0]["matches"] == []
            await research.announcements.enrich_news(news, None)
            saved = news.listing(news_id=news_id)[0]
            assert saved["matches"][0]["market"]["address"] == ADDRESS
            assert (
                saved["matches"][0]["market"]["news_relation"]
                == "primary_document_contract_mention"
            )
            assert saved["matches"][0]["official_affiliation"] == "unverified"
            assert (
                saved["document_analysis"]["contract_candidates"][0]["token_identity_verified"]
                is False
            )
            assert store.token(ADDRESS)["source"] == "source_document"
            assert store.portfolio()["orders"] == []
        finally:
            await research.close()
            await news.close()

    asyncio.run(run())


def test_primary_articles_remain_available_after_many_newer_aggregator_articles(store):
    from app.news import News

    news = News(store, None)
    try:
        older = datetime.fromtimestamp(time.time() - 86400, UTC).isoformat()
        primary = news.save(
            article(topic="kraken_official", title="Original crypto source announcement")
            | {"url": "https://blog.kraken.com/fixture", "published_at": older}
        )
        for i in range(105):
            news.save(
                article(title=f"Other crypto news {i}")
                | {"url": f"https://example.org/{i}", "fingerprint": str(i)}
            )
        assert primary in {n["id"] for n in news.listing()}
    finally:
        asyncio.run(news.close())
