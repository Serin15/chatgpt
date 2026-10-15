"""Isolated fixtures for the Level 3 workflow. No external calls or real trades."""

import asyncio
import copy
import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import utcnow
from app.opportunity_rules import EngineConfig, evaluate, features
from app.opportunity_sources import sampled_activity
from tests.conftest import OTHER, market, security
from tests.test_assets import FixtureAssets
from tests.test_news import FixtureNews, NewsFixtureProviders

TOKEN = OTHER
POOL = "So11111111111111111111111111111111111111112"


def stamp(at):
    return datetime.fromtimestamp(at, UTC).isoformat()


def source_item(at=None):
    at = time.time() if at is None else at
    return {
        "chain": "solana",
        "pool": POOL,
        "contract": TOKEN,
        "name": "Explicit fixture / SOL",
        "price_usd": 1,
        "liquidity_usd": 50000,
        "source": "isolated fixture",
        "pool_created_at_reported": stamp(at - 1800),
        "observed_at": stamp(at),
        "token_launched_at": None,
    }


@pytest.fixture
def client_engine(settings, monkeypatch):
    app = create_app(settings, NewsFixtureProviders(), False, FixtureNews, FixtureAssets)

    async def quotes(providers, candidates):
        return {
            (c["pool"], c["contract"]): market(c["contract"]).model_dump()
            | {"pair_address": c["pool"]}
            for c in candidates
        }

    async def gecko(discovery, candidates):
        return {}

    monkeypatch.setattr("app.opportunities.pool_markets", quotes)
    monkeypatch.setattr("app.opportunities.gecko_markets", gecko)
    with TestClient(app) as client:
        yield client, app.state.service.opportunities


def seed(engine):
    engine.service.discovery.save(source_item())
    config = engine.config()
    policy = engine.policy(config)
    engine.ingest(policy)
    return engine.due(config)[0], policy, config


def payload(engine, candidate, at, price=1, liquidity=50000, history=None, unsafe=False):
    m = market(candidate["contract"], price_usd=price, liquidity_usd=liquidity).model_dump() | {
        "pair_address": candidate["pool"],
        "observed_at": stamp(at),
    }
    s = security()
    s["observed_at"] = stamp(at)
    if unsafe:
        s["rpc"]["freeze_authority"] = "explicit privileged fixture"
    f = features(m, history or [], candidate["discovery"], stamp(at), engine.config())
    n = {"supported": [], "uncertain": [], "score": None}
    w = {"score": None, "events": []}
    d = evaluate(m, s, f, n, w, engine.service.settings, engine.config(), stamp(at))
    return {
        "market": m,
        "security": s,
        "features": f,
        "decision": d,
        "narrative": n,
        "wallet": w,
        "source_kind": "isolated_fixture",
    }


def test_automatic_cycle_connects_discovery_to_alert_without_paper_orders(client_engine):
    client, engine = client_engine
    engine.service.discovery.save(source_item())
    result = asyncio.run(engine.cycle(refresh_discovery=False))
    assert result["observed"] == 1
    row = client.get("/api/opportunities").json()["items"][0]
    assert row["latest"]["decision"]["verdict"] == "INVESTIGATE"
    alerts = client.get("/api/opportunities/alerts").json()["items"]
    assert len(alerts) == 1 and alerts[0]["payload"]["contract"] == TOKEN
    assert alerts[0]["delivered_in_app_at"] is None
    receipt = client.post(f"/api/opportunities/alerts/{alerts[0]['id']}/receipt").json()
    assert receipt["delivered_in_app_at"]
    assert client.get("/api/portfolio?account=news").json()["orders"] == []
    assert client.get("/api/opportunities/performance").json()["totals"]["delivered_in_app"] == 1


def test_discovery_initial_capture_is_immutable_and_duplicate_pools_do_not_duplicate_candidate(
    client_engine,
):
    _, engine = client_engine
    item = source_item()
    engine.service.discovery.save(item)
    engine.service.discovery.save(item | {"price_usd": 100})
    engine.ingest(engine.policy(engine.config()))
    detail = engine.detail(engine.listing()["items"][0]["id"])
    assert detail["discovery"]["price_usd"] == 1
    engine.service.discovery.save(item | {"pool": TOKEN})
    engine.ingest(engine.policy(engine.config()))
    assert engine.report()["totals"]["discovered"] == 1


def test_rejected_and_disappeared_candidates_are_retained(client_engine, monkeypatch):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    at = time.time()
    original = payload(engine, c, at, unsafe=True)
    engine.save_observation(c, original, p, cfg, stamp(at))
    engine.save_observation(
        c, {"market": None, "error": "fixture provider failure"}, p, cfg, stamp(at + 4)
    )
    assert engine.detail(c["id"])["signals"][1]["verdict"] == "REJECT"
    engine.update_outcomes(at + 500)
    outcome = engine.detail(c["id"])["outcomes"][0]
    assert outcome["state"] == "entry_unavailable" and outcome["payload"]["pnl_usd"] is None
    assert engine.report()["totals"]["eligible"] == 1
    assert engine.report()["confirmed_unsellable"] is None


def test_cooldown_and_restart_preserve_signal_and_alert_identity(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    at = time.time()
    one = payload(engine, c, at)
    engine.save_observation(c, one, p, cfg, stamp(at))
    engine.save_observation(c, payload(engine, c, at + 1), p, cfg, stamp(at + 1))
    assert len(engine.alerts()) == 1
    from app.opportunities import Opportunities

    restarted = Opportunities(engine.service)
    assert len(restarted.alerts()) == 1
    assert restarted.detail(c["id"])["discovery"] == c["discovery"]
    assert not restarted.detail(c["id"])["outcomes"][0]["payload"].get("pnl_usd")


def test_missing_outcomes_never_become_zero_profit(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    at = time.time()
    engine.save_observation(c, payload(engine, c, at), p, cfg, stamp(at))
    engine.update_outcomes(at + 10000)
    rows = engine.detail(c["id"])["outcomes"]
    assert all(
        r["state"] == "missing_forward_entry" and r["payload"]["pnl_usd"] is None for r in rows
    )
    report = engine.report()["horizons"]["300"]["all_eligible_first_evaluations"]
    assert report["evaluated"] == 0 and report["mean_net_pnl_usd"] is None


def test_forward_uses_first_receipts_frozen_costs_and_no_favorable_selection(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    at = time.time()
    engine.save_observation(c, payload(engine, c, at), p, cfg, stamp(at))
    first = engine.save_observation(c, payload(engine, c, at + 4), p, cfg, stamp(at + 4))[0]
    engine.save_observation(c, payload(engine, c, at + 5, price=0.1), p, cfg, stamp(at + 5))
    exit_id = engine.save_observation(c, payload(engine, c, at + 304), p, cfg, stamp(at + 304))[0]
    engine.save_observation(c, payload(engine, c, at + 305, price=100), p, cfg, stamp(at + 305))
    engine.update_outcomes(at + 400)
    row = next(
        r
        for r in engine.detail(c["id"])["outcomes"]
        if r["signal_id"] == 2 and r["horizon_seconds"] == 300
    )
    assert row["state"] == "evaluated" and Decimal(row["payload"]["pnl_usd"]) < 0
    assert (
        row["payload"]["entry_observation_id"] == first
        and row["payload"]["exit_observation_id"] == exit_id
    )
    before = copy.deepcopy(row)
    config = engine.config().model_copy(update={"position_usd": 100})
    engine.configure(config)
    engine.update_outcomes(at + 500)
    after = next(
        r
        for r in engine.detail(c["id"])["outcomes"]
        if r["signal_id"] == 2 and r["horizon_seconds"] == 300
    )
    assert after == before


def test_feature_windows_do_not_use_future_or_overlapping_volume_samples(settings):
    at = time.time()
    m = market(TOKEN).model_dump()
    cfg = EngineConfig()
    history = [
        {"id": 1, "at": stamp(at - 100), "market": m | {"price_usd": 0.1}},
        {"id": 2, "at": stamp(at - 301), "market": m | {"volume_5m": 1000}},
        {"id": 3, "at": stamp(at + 1), "market": m | {"volume_5m": 1, "price_usd": 100}},
    ]
    f = features(m, history, source_item(at), stamp(at), cfg)
    assert f["changes"]["5m"]["baseline_observation_id"] == 2
    assert f["changes"]["5m"]["volume_5m_ratio"] == 20
    assert f["history_observations"] == 2
    assert f["unique_buyers"] is None and f["social_mentions_growth"] is None


def test_security_and_extension_gates_override_high_volume(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    at = time.time()
    assert payload(engine, c, at, unsafe=True)["decision"]["verdict"] == "REJECT"
    extended = payload(engine, c, at, price=2)
    assert extended["features"]["excessive_extension"]
    assert extended["decision"]["verdict"] == "MONITOR"
    assert extended["decision"]["scores"]["wallet_intelligence"] is None


def test_unknown_security_cannot_be_ranked(client_engine):
    _, engine = client_engine
    c, _, cfg = seed(engine)
    at = time.time()
    p = payload(engine, c, at)
    d = evaluate(
        p["market"],
        {"rpc": None, "goplus": None, "observed_at": stamp(at)},
        p["features"],
        p["narrative"],
        p["wallet"],
        engine.service.settings,
        cfg,
        stamp(at),
    )
    assert d["verdict"] == "MONITOR" and d["rank_score"] is None
    assert d["scores"]["security_risk"] is None


def test_narrative_name_similarity_does_not_supply_contract_evidence(client_engine):
    _, engine = client_engine
    asyncio.run(engine.service.news.refresh())
    result = engine.narratives.evidence("So11111111111111111111111111111111111111112", utcnow())
    assert result["uncertain"] and not result["supported"] and result["score"] is None


def test_configuration_and_lease_guards(client_engine):
    client, engine = client_engine
    assert (
        client.post(
            "/api/opportunities/config",
            json=EngineConfig(test_from=stamp(time.time() - 10)).model_dump(mode="json"),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/opportunities/config",
            json=EngineConfig(alert_verdicts=["REJECT"]).model_dump(mode="json"),
        ).status_code
        == 422
    )
    from app.opportunities import Opportunities

    other = Opportunities(engine.service)
    assert engine.acquire() and not other.acquire()
    engine.release()
    assert other.acquire()
    other.release()


def test_suspicion_is_not_a_manipulation_verdict():
    result = sampled_activity([None], TOKEN, POOL)
    assert result["unique_buy_candidates"] is None
    assert not result["organic_demand_verified"]


def test_followup_reserves_capacity_without_dropping_other_candidates(client_engine):
    _, engine = client_engine
    c, policy, cfg = seed(engine)
    # Follow-up is urgent only once the frozen minimum observation delay elapsed.
    now = time.time() - 5
    engine.save_observation(c, payload(engine, c, now), policy, cfg, stamp(now))
    with engine.store.connect() as db:
        db.execute("UPDATE opportunity_candidates SET next_due=?", (now - 1,))
        db.execute(
            "INSERT INTO opportunity_candidates(chain,contract,pool,discovered_at,ingested_at,discovery,eligible,next_due) VALUES('solana',?,?,?,?,?,1,?)",
            (
                "fixture-other-candidate",
                POOL,
                stamp(now - 1000),
                stamp(now - 1000),
                "{}",
                now - 1000,
            ),
        )
    cfg = cfg.model_copy(update={"observation_budget": 2})
    due = engine.due(cfg)
    assert len(due) == 2 and due[0]["id"] == c["id"]
    assert due[1]["contract"] == "fixture-other-candidate"


def test_old_rank_does_not_displace_a_fresh_candidate(client_engine):
    client, engine = client_engine
    c, policy, cfg = seed(engine)
    now = time.time()
    engine.save_observation(c, payload(engine, c, now - 300), policy, cfg, stamp(now - 300))
    with engine.store.connect() as db:
        result = db.execute(
            "INSERT INTO opportunity_candidates(chain,contract,pool,discovered_at,ingested_at,discovery,eligible,next_due) VALUES('solana',?,?,?,?,?,1,?)",
            ("fixture-current", POOL, stamp(now), stamp(now), "{}", now),
        )
        new_id = result.lastrowid
    other = c | {"id": new_id, "contract": "fixture-current"}
    p = payload(engine, other, now)
    p["decision"]["rank_score"] = 1
    engine.save_observation(other, p, policy, cfg, stamp(now))
    ranked = client.get("/api/opportunities?sort=rank&limit=1").json()
    assert ranked["items"][0]["id"] == new_id
    assert ranked["next_cursor"] is None


def test_cost_formula_change_cannot_rewrite_old_experiment(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    p = copy.deepcopy(p)
    p["payload"]["paper_source_sha256"] = "different-cost-implementation"
    now = time.time()
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    engine.save_observation(c, payload(engine, c, now + 4), p, cfg, stamp(now + 4))
    engine.update_outcomes(now + 400)
    o = engine.detail(c["id"])["outcomes"][0]
    assert o["state"] == "cost_model_unavailable" and o["payload"]["pnl_usd"] is None


def test_later_alert_is_counted_without_changing_baseline_selection(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    engine.save_observation(c, payload(engine, c, now, unsafe=True), p, cfg, stamp(now))
    engine.save_observation(c, payload(engine, c, now + 4), p, cfg, stamp(now + 4))
    report = engine.report()["horizons"]["300"]
    assert report["selected_at_first_evaluation"]["experiments"] == 0
    assert report["later_alert_experiments"]["experiments"] == 1


def test_liquidity_collapse_sends_one_critical_update_during_cooldown(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    engine.save_observation(c, payload(engine, c, now + 4, liquidity=1000), p, cfg, stamp(now + 4))
    engine.save_observation(c, payload(engine, c, now + 8, liquidity=500), p, cfg, stamp(now + 8))
    assert len(engine.alerts()) == 2
    assert engine.alerts()[0]["severity"] == "critical"
    assert engine.alerts()[0]["payload"]["alert_kind"] == "risk_update"
    assert engine.report()["horizons"]["300"]["later_alert_experiments"]["experiments"] == 0


def test_provider_failure_retains_candidate_and_recovers(client_engine, monkeypatch):
    from app.errors import ProviderError

    _, engine = client_engine
    c, p, cfg = seed(engine)

    async def fail(*args):
        raise ProviderError("explicit isolated provider outage")

    with monkeypatch.context() as m:
        m.setattr("app.opportunities.pool_markets", fail)
        m.setattr("app.opportunities.fallback_pool", fail)
        first = asyncio.run(engine.cycle(False))
    assert first["state"] == "partial"
    assert engine.detail(c["id"])["observations"][-1]["market"] is None
    with engine.store.connect() as db:
        db.execute("UPDATE opportunity_candidates SET next_due=0")
    second = asyncio.run(engine.cycle(False))
    assert second["observed"] == 1
    assert engine.detail(c["id"])["observations"][-1]["decision"]["verdict"] == "INVESTIGATE"


def test_promotion_on_another_feed_is_a_warning_not_proof_of_manipulation(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    engine.service.discovery.save(
        source_item() | {"promotion": {"source": "isolated paid-exposure fixture"}}
    )
    asyncio.run(engine.cycle(False))
    last = engine.detail(c["id"])["observations"][-1]
    flag = next(f for f in last["features"]["suspicions"] if f["kind"] == "paid_boost_reported")
    assert flag["origin"] == "provider_reported_promotion"
    assert last["decision"]["verdict"] == "INVESTIGATE"
    assert any("paid_boost_reported" in n for n in last["decision"]["negative"])


@pytest.mark.parametrize("acknowledge", [True, False])
def test_telegram_outbox_checks_actual_chat_and_never_retries_unknown(
    client_engine, monkeypatch, acknowledge
):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "isolated-fixture-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    calls = []

    async def send(method, body):
        calls.append((method, body))
        return {"message_id": 12, "chat": {"id": 12345 if acknowledge else 999}}

    monkeypatch.setattr(engine.service.notifications, "telegram", send)
    cfg = cfg.model_copy(update={"telegram_enabled": True})
    asyncio.run(engine.deliver_telegram(cfg))
    asyncio.run(engine.deliver_telegram(cfg))
    assert len(calls) == 1
    assert engine.alerts()[0]["telegram_state"] == (
        "acknowledged_by_api" if acknowledge else "delivery_unknown"
    )
    assert not engine.alerts()[0]["telegram_details"].get("read_by_user")


def test_empty_parsed_activity_keeps_participation_unknown_without_error(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    v = payload(engine, c, now)
    f = features(
        v["market"],
        [],
        c["discovery"],
        stamp(now),
        cfg,
        activity=sampled_activity([None], TOKEN, POOL),
    )
    result = evaluate(
        v["market"],
        v["security"],
        f,
        v["narrative"],
        v["wallet"],
        engine.service.settings,
        cfg,
        stamp(now),
    )
    assert f["unique_buyers"] is None
    assert result["verdict"] == "INVESTIGATE"


def test_future_narrative_split_is_purged_for_overlapping_trade_windows(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    cfg = cfg.model_copy(update={"test_from": datetime.fromtimestamp(now + 60, UTC)})
    engine.configure(cfg)
    p = engine.policy(cfg)
    engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    assert engine.report()["horizons"]["300"]["cohorts"]["purged_boundary"]["experiments"] == 1
    assert engine.report()["horizons"]["300"]["cohorts"]["test"]["experiments"] == 0


def test_consider_requires_nonoverlapping_history_and_retained_liquidity(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    v = payload(engine, c, now)
    m = v["market"] | {"buyers_5m_reported": 20, "volume_5m": 200}
    history = [
        {"id": 1, "at": stamp(now - 610), "market": m | {"volume_5m": 100}},
        {"id": 2, "at": stamp(now - 310), "market": m | {"volume_5m": 100}},
    ]
    f = features(m, history, c["discovery"], stamp(now), cfg)
    assert (
        evaluate(
            m,
            v["security"],
            f,
            v["narrative"],
            v["wallet"],
            engine.service.settings,
            cfg,
            stamp(now),
        )["verdict"]
        == "CONSIDER"
    )
    f["changes"]["5m"]["liquidity_change_pct"] = None
    assert (
        evaluate(
            m,
            v["security"],
            f,
            v["narrative"],
            v["wallet"],
            engine.service.settings,
            cfg,
            stamp(now),
        )["verdict"]
        == "INVESTIGATE"
    )


def test_narrative_ai_requires_category_and_literal_evidence():
    from app.ai_research import validate_interpretation
    from tests.test_ai_research import CONTENT, answer

    bundle = {"task": "narrative", "sources": [{"id": "D1", "content": CONTENT}]}
    with pytest.raises(ValueError):
        validate_interpretation(answer(), bundle)
    result = validate_interpretation(answer() | {"narrative_category": "ai"}, bundle)
    assert result["narrative_category"] == "ai"
    with pytest.raises(ValueError):
        validate_interpretation(
            answer(quote="invented unsupported quotation") | {"narrative_category": "ai"}, bundle
        )


def test_empty_token_narrative_does_not_starve_global_story_classification(
    client_engine, monkeypatch
):
    _, engine = client_engine
    seed(engine)
    engine.configure(engine.config().model_copy(update={"ai_narratives": True}))
    classified = []

    async def classify(config):
        classified.append(config.ai_narratives)

    monkeypatch.setattr(engine, "refresh_narratives", classify)

    async def run():
        await engine.cycle(False)
        await asyncio.sleep(0)

    asyncio.run(run())
    assert classified == [True]


def test_security_and_liquidity_filters_are_separate(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    r = payload(engine, c, time.time(), liquidity=1000)["decision"]
    assert r["security_filter_passed"]
    assert not r["liquidity_filter_passed"] and r["verdict"] == "REJECT"


def test_migrated_archive_does_not_starve_new_discovery(client_engine):
    _, engine = client_engine
    c, p, cfg = seed(engine)
    with engine.store.connect() as db:
        for i in range(10):
            db.execute(
                "INSERT INTO opportunity_candidates(chain,contract,pool,discovered_at,ingested_at,discovery,eligible,next_due) VALUES('solana',?,?,?,?,?,1,0)",
                (
                    f"legacy-{i}",
                    POOL,
                    stamp(time.time() - 10000),
                    stamp(time.time() - 10000),
                    '{"imported_from_cache":true}',
                ),
            )
    due = engine.due(cfg.model_copy(update={"observation_budget": 3}))
    assert due[0]["id"] == c["id"]
    assert any(r["discovery"].get("imported_from_cache") for r in due[1:])


def test_market_quotes_reject_a_different_contract_or_anchor():
    from app.errors import ProviderError
    from app.opportunity_sources import gecko_market

    c = {"contract": TOKEN, "pool": POOL}
    row = {
        "attributes": {
            "address": POOL,
            "name": "fixture / SOL",
            "base_token_price_usd": "1",
            "reserve_in_usd": "50000",
            "transactions": {"m5": {"buys": 10, "sells": 5, "buyers": 99, "sellers": 4}},
        },
        "relationships": {"base_token": {"data": {"id": "solana_" + TOKEN}}},
    }
    m = gecko_market(row, c)
    assert m["buyers_5m_reported"] is None and m["sellers_5m_reported"] == 4
    with pytest.raises(ProviderError):
        gecko_market(row, c | {"pool": TOKEN})
    with pytest.raises(ProviderError):
        gecko_market(row, c | {"contract": POOL})


def test_alert_cursor_preserves_old_history_when_a_new_alert_arrives(client_engine):
    from app.opportunities import encode

    client, engine = client_engine
    c, p, cfg = seed(engine)
    now = time.time()
    v = payload(engine, c, now)
    with engine.store.connect() as db:
        for i in range(15):
            at = stamp(now + i)
            signal = engine._signal(db, c["id"], None, at, "alert", v["decision"], p, cfg)
            a = engine.alert_payload(c, v, at, signal)
            db.execute(
                "INSERT INTO opportunity_alerts(candidate_id,signal_id,at,severity,fingerprint,payload) VALUES(?,?,?,'research',?,?)",
                (c["id"], signal, at, "isolated-history-" + str(i), encode(a)),
            )
    first = client.get("/api/opportunities/alerts?limit=7").json()
    ids = [a["id"] for a in first["items"]]
    with engine.store.connect() as db:
        signal = engine._signal(db, c["id"], None, stamp(now + 20), "alert", v["decision"], p, cfg)
        db.execute(
            "INSERT INTO opportunity_alerts(candidate_id,signal_id,at,severity,fingerprint,payload) VALUES(?,?,?,'research','isolated-new-alert',?)",
            (
                c["id"],
                signal,
                stamp(now + 20),
                encode(engine.alert_payload(c, v, stamp(now + 20), signal)),
            ),
        )
    cursor = first["next_cursor"]
    while cursor:
        page = client.get("/api/opportunities/alerts", params={"limit": 7, "before": cursor}).json()
        ids.extend(a["id"] for a in page["items"])
        cursor = page["next_cursor"]
    assert len(ids) == 15 and len(set(ids)) == 15 and ids == sorted(ids, reverse=True)
