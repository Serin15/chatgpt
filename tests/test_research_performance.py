import asyncio
import json
import sqlite3
import time
import zipfile
from datetime import UTC, datetime
from decimal import Decimal as D
from io import BytesIO
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.research import Research, SourceInput
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders


def fixture(settings):
    return create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)


def evidence():
    return {
        "category": "product",
        "claim": "The documentation describes a running product.",
        "status": "supported",
        "source_url": "https://example.org/public-document",
        "reviewer_note": "Manually compared the claim to the document.",
    }


def test_manual_evidence_survives_restart_and_signal_captures_original(settings):
    app = fixture(settings)
    with TestClient(app) as client:
        client.post("/api/assets/refresh")
        case = client.post("/api/research/asset:bitcoin/evidence", json=evidence()).json()
        record = case["evidence"][0]["id"]
        assert case["checks"][2]["status"] == "supported_manual"
        assert not case["automatically_verified"] and not case["fundamentals_verified"]
        signal = client.post("/api/assets/bitcoin/signal", json={"thesis": "Forward test"}).json()
        assert json.loads(signal["evidence"])["research_context"]["evidence"][0]["id"] == record
        assert client.post(
            f"/api/research/asset:bitcoin/evidence/{record}/revoke", json={}
        ).is_success
        with app.state.service.news_paper.connect() as db:
            saved = json.loads(
                db.execute("SELECT evidence FROM signals WHERE id=?", (signal["id"],)).fetchone()[0]
            )
        assert saved["research_context"]["evidence"][0]["revoked_at"] is None
    with TestClient(fixture(settings)) as client:
        assert client.get("/api/research/asset:bitcoin").json()["evidence"][0]["revoked_at"]


def test_review_requires_citation_and_rejects_invalid_contract(settings):
    with TestClient(fixture(settings)) as client:
        client.post("/api/assets/refresh")
        bad = evidence() | {"source_url": None}
        assert client.post("/api/research/asset:bitcoin/evidence", json=bad).status_code == 422
        bad = evidence() | {"chain": "base", "contract": "0x123"}
        assert client.post("/api/research/asset:bitcoin/evidence", json=bad).status_code == 422
        assert client.get("/api/portfolio?account=news").json()["cash"] == "500"


def test_expired_manual_confirmation_never_clears_an_unresolved_dispute(settings):
    app = fixture(settings)
    with TestClient(app) as client:
        client.post("/api/assets/refresh")
        client.post("/api/research/asset:bitcoin/evidence", json=evidence())
        client.post(
            "/api/research/asset:bitcoin/evidence", json=evidence() | {"status": "disputed"}
        )
        with app.state.service.store.connect() as db:
            db.execute(
                "UPDATE research_evidence SET at=?",
                (datetime.fromtimestamp(time.time() - 31 * 86400, UTC).isoformat(),),
            )
        case = client.get("/api/research/asset:bitcoin").json()
        assert case["verdict"] == "conflicting_evidence"
        record = next(r["id"] for r in case["evidence"] if r["payload"]["status"] == "disputed")
        client.post(f"/api/research/asset:bitcoin/evidence/{record}/revoke", json={})
        assert client.get("/api/research/asset:bitcoin").json()["checks"][2]["status"] == "unknown"


def test_metrics_failure_never_reports_a_committed_trade_as_failed(settings):
    app = fixture(settings)
    with TestClient(app) as client:
        signal = client.post("/api/assets/bitcoin/signal", json={}).json()["id"]
        service = app.state.service
        with service.news_paper.connect() as db:
            db.execute(
                "UPDATE signals SET at=? WHERE id=?",
                (datetime.fromtimestamp(time.time() - 4, UTC).isoformat(), signal),
            )
        with patch.object(
            service.performance, "observe", side_effect=RuntimeError("isolated metric error")
        ):
            result = client.post(
                "/api/paper/assets/buy",
                json={"asset_id": "bitcoin", "amount_usd": "50", "signal_id": signal},
            )
        assert result.is_success
        p = client.get("/api/portfolio?account=news").json()
        assert D(p["cash"]) == 450 and len(p["orders"]) == 1
        service.performance.safe_observe("scanner")
        assert service.performance.status["state"] == "error"


def test_document_match_is_not_claim_verification(store):
    async def run():
        html = "<html><p>A release is described by the original source in this document.</p><script>Fake unsupported claim in a script.</script></html>"
        research = Research(
            store,
            httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda r: httpx.Response(200, text=html, headers={"content-type": "text/html"})
                )
            ),
        )
        try:
            result = await research.source(
                SourceInput(
                    url="https://blog.ethereum.org/example",
                    excerpt="A release is described by the original source in this document.",
                )
            )
            assert (
                result["excerpt_found"]
                and not result["claim_verified"]
                and not result["endorsement_verified"]
            )
            result = await research.source(
                SourceInput(
                    url="https://blog.ethereum.org/example",
                    excerpt="Fake unsupported claim in a script.",
                )
            )
            assert not result["excerpt_found"]
            import pytest

            from app.providers import ProviderError

            with pytest.raises(ProviderError):
                await research.source(
                    SourceInput(
                        url="https://127.0.0.1/private",
                        excerpt="An untrusted document has no permission.",
                    )
                )
        finally:
            await research.close()

    asyncio.run(run())


def test_forward_report_counts_failures_gaps_and_aligned_benchmark(settings, tmp_path):
    app = fixture(settings)
    with TestClient(app) as client:
        client.post("/api/assets/refresh")
        service = app.state.service
        service.performance.observe("news")
        signal = client.post("/api/assets/bitcoin/signal", json={}).json()["id"]
        with service.news_paper.connect() as db:
            db.execute(
                "UPDATE signals SET at=? WHERE id=?",
                (datetime.fromtimestamp(time.time() - 4, UTC).isoformat(), signal),
            )
        order = client.post(
            "/api/paper/assets/buy",
            json={"asset_id": "bitcoin", "amount_usd": "50", "signal_id": signal},
        ).json()
        client.post(
            "/api/paper/assets/buy",
            json={"asset_id": "bitcoin", "amount_usd": "50", "signal_id": signal},
        )
        client.post(f"/api/paper/positions/{order['position_id']}/sell?account=news")
        report = client.get("/api/performance?account=news").json()
        assert report["closed_trades"] == 1 and report["open_trades"] == 0
        assert report["failed_attempts"] == 1 and D(report["realized_pnl_usd"]) < 0
        assert (
            report["comparison"] is not None
            and D(report["comparison"]["btc_scenario_return_pct"]) < 0
        )
        with service.news_paper.connect() as db:
            db.execute(
                "INSERT INTO equity_observations(at,equity,cash,btc_price,context) VALUES(?,?,?,?,?)",
                (datetime.now(UTC).isoformat(), None, "450", None, "{}"),
            )
        report = client.get("/api/performance?account=news").json()
        assert report["missing_valuations"] == 1 and report["comparison"] is None
        exported = client.get("/api/export?account=news").json()
        assert (
            len(exported["orders"]) == 3
            and exported["snapshots"]
            and exported["equity_observations"]
        )
        assert not exported["live_execution"]
        backup = client.post("/api/backup")
        assert backup.is_success
        with zipfile.ZipFile(BytesIO(backup.content)) as archive:
            assert set(archive.namelist()) == {"research.sqlite3", "news_paper/research.sqlite3"}
            assert archive.testzip() is None
            restored = tmp_path / "restored"
            archive.extractall(restored)
        for relative, expected_orders in [
            ("research.sqlite3", 0),
            ("news_paper/research.sqlite3", 3),
        ]:
            with sqlite3.connect(restored / relative) as db:
                assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == expected_orders
        with sqlite3.connect(restored / "news_paper/research.sqlite3") as db:
            assert (
                db.execute("SELECT balance FROM account").fetchone()[0]
                == exported["portfolio"]["cash"]
            )
        assert client.get("/api/portfolio?account=scanner").json()["cash"] == "100"
