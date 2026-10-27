"""Manual candidate-to-ledger integration with isolated provider fixtures."""

import json
import time
from decimal import Decimal

import pytest

from app.providers import ProviderError
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, stamp


def observed(engine, **kwargs):
    candidate, policy, config = seed(engine)
    at = time.time() - 10
    observation, _ = engine.save_observation(
        candidate, payload(engine, candidate, at, **kwargs), policy, config, stamp(at)
    )
    return candidate, observation


def prepare(client, candidate, observation, account="news", **extra):
    return client.post(
        f"/api/opportunities/{candidate['id']}/paper-signal",
        json={"observation_id": observation, "account": account, **extra},
    )


def age_signal(engine, signal, account="news"):
    # Explicit fixture clock adjustment, never a production fill/backdate.
    with engine.service.paper_store(account).connect() as db:
        db.execute("UPDATE signals SET at=? WHERE id=?", (stamp(time.time() - 4), signal))


def buy(client, candidate, signal, account="news", amount="50"):
    return client.post("/api/paper/buy", json={
        "address": candidate["contract"], "account": account,
        "signal_id": signal, "amount_usd": amount,
    })


def test_candidate_manual_signal_preserves_origin_and_fills_at_new_price(client_engine):
    client, engine = client_engine
    candidate, observation = observed(engine, price=.5)
    response = client.post(
        f"/api/opportunities/{candidate['id']}/paper-signal",
        json={"observation_id": observation, "account": "news", "thesis": "My hypothesis"},
    )
    assert response.status_code == 200, response.text
    saved = response.json()
    context = json.loads(saved["evidence"])["opportunity_context"]
    assert context["candidate_id"] == candidate["id"]
    assert context["observation"]["id"] == observation
    assert context["observation"]["payload"]["market"]["price_usd"] == .5
    assert saved["snapshot"]["market"]["price_usd"] == 1
    assert context["discovery_signal"]["kind"] == "discovery"
    assert context["linked_at"] >= context["observation"]["at"]
    assert engine.store.token(candidate["contract"])["watch"] == 1
    assert client.get("/api/portfolio?account=news").json()["cash"] == "500"
    age_signal(engine, saved["id"])
    order = buy(client, candidate, saved["id"])
    assert order.status_code == 200, order.text
    order = order.json()
    assert order["entry_context"]["opportunity_context"] == context
    assert Decimal(order["quantity"]) < 50  # costs and impact at fresh $1, not old $0.50
    assert buy(client, candidate, saved["id"]).status_code == 409
    portfolio = client.get("/api/portfolio?account=news").json()
    assert len(portfolio["positions"]) == 1
    origin = portfolio["positions"][0]["opportunity"]
    assert origin["candidate_id"] == candidate["id"] and origin["observation_id"] == observation
    response = client.post(
        f"/api/paper/positions/{order['position_id']}/sell?account=news", json={}
    )
    assert response.status_code == 200, response.text
    portfolio = client.get("/api/portfolio?account=news").json()
    assert Decimal(portfolio["positions"][0]["pnl"]) < 0
    assert Decimal(portfolio["cash"]) < 500
    assert portfolio["positions"][0]["opportunity"] == origin
    assert client.get("/api/portfolio?account=scanner").json()["cash"] == "100"


@pytest.mark.parametrize("account,amount,fragment", [
    ("scanner", "50", "Alocarea"), ("news", "NaN", "Suma"),
    ("news", "0", "Suma"), ("news", "1", "minimă"),
])
def test_manual_candidate_keeps_existing_financial_limits(client_engine, account, amount, fragment):
    client, engine = client_engine
    candidate, observation = observed(engine)
    response = prepare(client, candidate, observation, account, amount_usd=amount if amount == "1" else "50")
    assert response.status_code == 200
    signal = response.json()["id"]
    age_signal(engine, signal, account)
    response = buy(client, candidate, signal, account, amount)
    assert response.status_code == 409 and fragment in response.text
    portfolio = client.get("/api/portfolio?account=" + account).json()
    assert not portfolio["positions"]
    assert portfolio["cash"] == ("100" if account == "scanner" else "500")


def test_manual_candidate_does_not_bypass_delay_expiry_or_account(client_engine):
    client, engine = client_engine
    candidate, observation = observed(engine)
    signal = prepare(client, candidate, observation).json()["id"]
    assert buy(client, candidate, signal).status_code == 409
    age_signal(engine, signal)
    assert buy(client, candidate, signal, "scanner", "5").status_code == 409
    with engine.service.news_paper.connect() as db:
        db.execute("UPDATE signals SET at=? WHERE id=?", (stamp(time.time() - 300), signal))
    assert buy(client, candidate, signal).status_code == 409
    assert not engine.service.news_paper.portfolio()["positions"]


@pytest.mark.parametrize("stage", ["prepare", "buy"])
def test_provider_outage_never_fills_using_candidate_cached_price(client_engine, monkeypatch, stage):
    client, engine = client_engine
    candidate, observation = observed(engine)
    if stage == "buy":
        signal = prepare(client, candidate, observation).json()["id"]
        age_signal(engine, signal)

    async def failure(address):
        raise ProviderError("dex: explicit fixture failure")

    monkeypatch.setattr(engine.service.providers, "market", failure)
    response = prepare(client, candidate, observation) if stage == "prepare" else buy(client, candidate, signal)
    assert response.status_code == 503
    assert not engine.service.news_paper.portfolio()["positions"]
    assert engine.service.news_paper.portfolio()["cash"] == "500"


def test_selected_evidence_and_study_rows_are_not_rewritten(client_engine):
    client, engine = client_engine
    candidate, observation = observed(engine)
    tables = ["opportunity_signals", "opportunity_observations", "opportunity_outcomes", "opportunity_policies"]
    with engine.store.connect() as db:
        before = {table: [tuple(row) for row in db.execute("SELECT * FROM " + table)] for table in tables}
    signal = prepare(client, candidate, observation).json()["id"]
    age_signal(engine, signal)
    assert buy(client, candidate, signal).status_code == 200
    with engine.store.connect() as db:
        after = {table: [tuple(row) for row in db.execute("SELECT * FROM " + table)] for table in tables}
    assert before == after


@pytest.mark.parametrize("reason", ["base", "excluded", "rejected", "new_rejection", "future", "wrong_observation", "missing", "invalid_contract"])
def test_invalid_or_rejected_candidate_fails_closed(client_engine, reason):
    client, engine = client_engine
    candidate, observation = observed(engine, unsafe=reason == "rejected")
    with engine.store.connect() as db:
        if reason == "base":
            db.execute("UPDATE opportunity_candidates SET chain='base' WHERE id=?", (candidate["id"],))
        elif reason == "excluded":
            db.execute("UPDATE opportunity_candidates SET eligible=0 WHERE id=?", (candidate["id"],))
        elif reason == "future":
            db.execute("UPDATE opportunity_observations SET at=? WHERE id=?", (stamp(time.time() + 60), observation))
        elif reason == "invalid_contract":
            db.execute("UPDATE opportunity_candidates SET contract='bad' WHERE id=?", (candidate["id"],))
    if reason == "new_rejection":
        at = time.time() - 1
        engine.save_observation(candidate, payload(engine, candidate, at, unsafe=True), engine.policy(engine.config()), engine.config(), stamp(at))
    if reason == "wrong_observation":
        observation += 9999
    if reason == "missing":
        candidate["id"] += 9999
    response = prepare(client, candidate, observation)
    assert response.status_code == (404 if reason in {"wrong_observation", "missing"} else 409)
    for account in ["scanner", "news"]:
        with engine.service.paper_store(account).connect() as db:
            assert db.execute("SELECT count(*) FROM signals").fetchone()[0] == 0


def test_new_rejection_after_preparation_vetoes_manual_buy(client_engine):
    client, engine = client_engine
    candidate, observation = observed(engine)
    signal = prepare(client, candidate, observation).json()["id"]
    age_signal(engine, signal)
    at = time.time() - 1
    engine.save_observation(candidate, payload(engine, candidate, at, unsafe=True), engine.policy(engine.config()), engine.config(), stamp(at))
    response = buy(client, candidate, signal)
    assert response.status_code == 409 and "Verdictul" in response.text
    assert not engine.service.news_paper.portfolio()["positions"]


def test_fresh_security_failure_keeps_signal_but_cannot_fill(client_engine, monkeypatch):
    client, engine = client_engine
    candidate, observation = observed(engine)

    async def incomplete(address):
        return {"observed_at": stamp(time.time()), "rpc": None, "goplus": None, "errors": ["fixture outage"]}

    monkeypatch.setattr(engine.service.providers, "security", incomplete)
    saved = prepare(client, candidate, observation).json()
    assert saved["snapshot"]["analysis"]["paper_allowed"] is False
    age_signal(engine, saved["id"])
    assert buy(client, candidate, saved["id"]).status_code == 409
    assert engine.service.news_paper.portfolio()["cash"] == "500"


def test_manual_amount_change_requires_new_decision(client_engine):
    client, engine = client_engine
    candidate, observation = observed(engine)
    saved = prepare(client, candidate, observation).json()
    age_signal(engine, saved["id"])
    preview = saved["cost_preview"]
    assert preview["available"] and Decimal(preview["roundtrip_pnl_usd"]) < 0
    assert Decimal(preview["entry"]["price_impact"]) > 0
    assert Decimal(preview["break_even_rise_pct"]) > 0
    response = buy(client, candidate, saved["id"], amount="25")
    assert response.status_code == 409 and "Suma diferă" in response.text
    assert not engine.service.news_paper.portfolio()["positions"]


def test_jupiter_mode_never_substitutes_pool_preview_or_fallback(client_engine, monkeypatch):
    client, engine = client_engine
    monkeypatch.setenv("PAPER_SOLANA_EXECUTION", "jupiter")
    candidate, observation = observed(engine)
    saved = prepare(client, candidate, observation).json()
    assert saved["cost_preview"]["available"] is False
    assert "Jupiter" in saved["cost_preview"]["reason"]
    age_signal(engine, saved["id"])

    async def unavailable(*args):
        raise ProviderError("Jupiter: explicit fixture unavailable")

    monkeypatch.setattr(engine.service.jupiter, "fill", unavailable)
    assert buy(client, candidate, saved["id"]).status_code == 503
    assert not engine.service.news_paper.portfolio()["positions"]


def test_pinned_observation_is_not_silently_replaced_by_newer_evidence(client_engine):
    client, engine = client_engine
    candidate, observation = observed(engine, price=.5)
    at = time.time() - 1
    newer, _ = engine.save_observation(candidate, payload(engine, candidate, at, price=.8), engine.policy(engine.config()), engine.config(), stamp(at))
    saved = prepare(client, candidate, observation).json()
    context = json.loads(saved["evidence"])["opportunity_context"]
    assert context["observation"]["id"] == observation != newer
    assert context["observation"]["payload"]["market"]["price_usd"] == .5
    assert saved["snapshot"]["market"]["price_usd"] == 1


def test_paper_bridge_validates_input_and_origin(client_engine):
    client, engine = client_engine
    candidate, observation = observed(engine)
    path = f"/api/opportunities/{candidate['id']}/paper-signal"
    for body in [
        {}, {"observation_id": -1}, {"observation_id": observation, "account": "live"},
        {"observation_id": observation, "thesis": "x" * 1001},
        {"observation_id": observation, "contract": "spoofed"},
    ]:
        assert client.post(path, json=body).status_code == 422
    assert client.post(path, json={"observation_id": observation}, headers={"origin": "https://other.example"}).status_code == 403


@pytest.mark.parametrize("amount", ["1e999999999", "NaN", "Infinity", "0", "-1"])
def test_invalid_preparation_amount_never_reaches_preview_or_changes_cash(client_engine, amount):
    client, engine = client_engine
    candidate, observation = observed(engine)
    response = prepare(client, candidate, observation, amount_usd=amount)
    assert response.status_code == 409
    assert engine.service.news_paper.portfolio()["cash"] == "500"
    with engine.service.news_paper.connect() as db:
        assert db.execute("SELECT count(*) FROM signals").fetchone()[0] == 0
