"""Bounded polling with durable history and promises; simulated providers, real SQLite."""

import json
import time

import pytest

from tests.test_observation_sampling import candidate
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, stamp


def observed(engine, number, age, due_age=10):
    now = time.time()
    c = candidate(engine, number, now - age)
    cfg = engine.config()
    p = engine.policy(cfg)
    engine.save_observation(c, payload(engine, c, now - age, unsafe=True), p, cfg, stamp(now - age))
    with engine.store.connect() as db:
        db.execute(
            "UPDATE opportunity_candidates SET next_due=? WHERE id=?", (now - due_age, c["id"])
        )
        db.execute(
            "UPDATE opportunity_outcomes SET state='entry_unavailable',payload=? WHERE signal_id IN (SELECT id FROM opportunity_signals WHERE candidate_id=?)",
            (json.dumps({"pnl_usd": None, "fixture": True}), c["id"]),
        )
        db.execute(
            "UPDATE observation_jobs SET status='missed',reason='fixture_prior_worker_gap' WHERE candidate_id=?",
            (c["id"],),
        )
    return c


def test_completed_old_candidate_stops_periodic_polling_without_losing_history(client_engine):
    client, engine = client_engine
    c = observed(engine, 15001, 5 * 86400)
    history = engine.history(c["id"])
    before = engine.detail(c["id"])
    assert c["id"] not in {r["id"] for r in engine.due(engine.config())}
    after = client.get(f"/api/opportunities/{c['id']}").json()
    assert after["signals"] == before["signals"]
    assert after["outcomes"] == before["outcomes"]
    assert engine.history(c["id"]) == history
    assert after["monitoring"]["state"] == "paused"


def test_active_candidate_precedes_warm_background_candidate(client_engine):
    _, engine = client_engine
    warm = observed(engine, 15002, 86400, due_age=3600)
    active = observed(engine, 15003, 600)
    due = engine.due(engine.config().model_copy(update={"observation_budget": 1}))
    assert due[0]["id"] == active["id"]
    assert due[0]["collection_lane"] == "active_watch"
    due = engine.due(engine.config().model_copy(update={"observation_budget": 2}))
    assert {r["id"] for r in due} == {warm["id"], active["id"]}


def test_queue_separates_paused_background_from_dispatchable_work(client_engine):
    _, engine = client_engine
    observed(engine, 15004, 5 * 86400)
    observed(engine, 15005, 600)
    q = engine.queue_health()
    assert q["due"] == 2, "Raw overdue work must remain visible"
    assert q["dispatchable_due"] == 1
    assert q["paused_due"] == 1
    assert q["not_enriched"] == 0


@pytest.mark.parametrize("phase", ["entry", "exit", "checkpoint", "routed_exit"])
def test_promised_job_overrides_age_and_periodic_schedule(client_engine, phase):
    _, engine = client_engine
    c = observed(engine, 15010, 5 * 86400)
    now = time.time()
    with engine.store.connect() as db:
        sid = db.execute(
            "SELECT id FROM opportunity_signals WHERE candidate_id=? AND kind='baseline'",
            (c["id"],),
        ).fetchone()[0]
        engine.sampling.job(
            db,
            c["id"],
            sid,
            phase,
            604800 if phase != "entry" else 1,
            now - 1,
            now + 120,
            True,
            True,
        )
        db.execute(
            "UPDATE opportunity_candidates SET next_due=? WHERE id=?", (now + 86400, c["id"])
        )
    due = engine.due(engine.config().model_copy(update={"observation_budget": 1}))
    assert due[0]["id"] == c["id"]
    assert due[0]["collection_lane"] == "protected_followup"
    monitoring = engine.detail(c["id"])["monitoring"]
    assert monitoring["state"] == "followup" and monitoring["has_open_promises"]
    queue = engine.queue_health()
    assert queue["due"] == 0
    assert queue["promised_due_candidates"] == queue["promised_due_outside_periodic_queue"] == 1


def test_future_week_checkpoint_is_preserved_until_its_original_deadline(
    client_engine, monkeypatch
):
    _, engine = client_engine
    c = observed(engine, 15011, 5 * 86400)
    now = time.time()
    with engine.store.connect() as db:
        sid = db.execute(
            "SELECT min(id) FROM opportunity_signals WHERE candidate_id=?", (c["id"],)
        ).fetchone()[0]
        engine.sampling.job(
            db,
            c["id"],
            sid,
            "checkpoint",
            604800,
            now + 2 * 86400,
            now + 2 * 86400 + 180,
            False,
            True,
        )
        db.execute(
            "UPDATE opportunity_candidates SET next_due=? WHERE id=?", (now + 3 * 86400, c["id"])
        )
        before = [
            tuple(r) for r in db.execute("SELECT * FROM observation_jobs WHERE status='pending'")
        ]
    assert engine.due(engine.config()) == []
    with engine.store.connect() as db:
        assert before == [
            tuple(r) for r in db.execute("SELECT * FROM observation_jobs WHERE status='pending'")
        ]
    monkeypatch.setattr("app.opportunity_sampling.time.time", lambda: now + 2 * 86400 + 1)
    assert engine.due(engine.config())[0]["id"] == c["id"]


@pytest.mark.parametrize("model", ["estimated", "routed", "collecting_route"])
def test_unresolved_result_is_never_paused_even_without_a_pending_job(client_engine, model):
    _, engine = client_engine
    c = observed(engine, 15012, 5 * 86400)
    with engine.store.connect() as db:
        sid = db.execute(
            "SELECT id FROM opportunity_signals WHERE candidate_id=? AND kind='baseline'",
            (c["id"],),
        ).fetchone()[0]
        if model == "estimated":
            db.execute("UPDATE opportunity_outcomes SET state='pending' WHERE signal_id=?", (sid,))
        elif model == "routed":
            db.execute("UPDATE routed_outcomes SET state='pending' WHERE signal_id=?", (sid,))
        else:
            db.execute(
                "UPDATE routed_experiments SET entry_state='collecting' WHERE signal_id=?", (sid,)
            )
    assert engine.due(engine.config())[0]["id"] == c["id"]
    assert engine.detail(c["id"])["monitoring"]["has_open_promises"]


@pytest.mark.parametrize("manual", ["watchlist", "scanner_position", "news_position"])
def test_manual_holdings_and_watchlist_are_protected(client_engine, manual):
    _, engine = client_engine
    c = observed(engine, 15013, 5 * 86400)
    if manual == "watchlist":
        engine.store.add_token(c["contract"], "fixture_manual", watch=True)
    else:
        store = engine.store if manual == "scanner_position" else engine.service.news_paper
        with store.connect() as db:
            db.execute(
                "INSERT INTO positions(address,quantity,entry_cost,entry_at,entry_snapshot_id,signal_id) VALUES(?,'1','1',?,1,1)",
                (c["contract"], stamp(time.time() - 86400)),
            )
    assert engine.due(engine.config())[0]["id"] == c["id"]
    assert engine.detail(c["id"])["monitoring"]["state"] == "manual_watch"


def test_first_observation_is_required_even_after_long_provider_failure(client_engine):
    _, engine = client_engine
    c = candidate(engine, 15014, time.time() - 5 * 86400)
    with engine.store.connect() as db:
        db.execute("UPDATE opportunity_candidates SET next_due=0 WHERE id=?", (c["id"],))
    assert engine.due(engine.config())[0]["id"] == c["id"]
    assert engine.detail(c["id"])["monitoring"]["state"] == "awaiting_first_observation"


def test_configurable_background_window_does_not_change_old_policy_or_control(client_engine):
    _, engine = client_engine
    c = observed(engine, 15015, 3 * 86400)
    before = engine.detail(c["id"])
    assert engine.due(engine.config()) == []
    config = engine.config().model_copy(update={"background_watch_hours": 96})
    assert engine.due(config)[0]["id"] == c["id"]
    assert engine.detail(c["id"])["signals"] == before["signals"]
    assert engine.detail(c["id"])["sampling_enrollment"] == before["sampling_enrollment"]


def test_new_document_can_resume_an_old_token_without_rediscovery(client_engine):
    import asyncio

    from tests.test_story_evidence import save_document

    _, engine = client_engine
    c = observed(engine, 15016, 5 * 86400)
    # Synthetic document whose explicit contract is this previously observed token.
    save_document(
        engine,
        candidates=[
            {"contract": c["contract"], "networks_reported": ["solana"], "negative_context": False}
        ],
    )
    engine.narratives.stories.index_documents()
    asyncio.run(engine.story_discovery.cycle())
    assert engine.story_discovery.summary()["states"] == {"existing_candidate": 1}
    assert engine.detail(c["id"])["monitoring"]["state"] == "reactivated"
    assert engine.due(engine.config())[0]["id"] == c["id"]
    assert engine.detail(c["id"])["discovered_at"] == c["discovered_at"]


def test_expired_promise_does_not_reactivate_finished_background_work(client_engine):
    _, engine = client_engine
    c = observed(engine, 15017, 5 * 86400)
    now = time.time()
    with engine.store.connect() as db:
        db.execute(
            "UPDATE observation_jobs SET status='pending',due_at=?,deadline_at=? WHERE candidate_id=?",
            (now - 300, now - 120, c["id"]),
        )
    # Reading status neither renews the expired deadline nor erases the missed job.
    assert engine.detail(c["id"])["monitoring"]["state"] == "paused"
    with engine.store.connect() as db:
        assert db.execute(
            "SELECT count(*) FROM observation_jobs WHERE status='pending'"
        ).fetchone()[0]
    assert engine.due(engine.config()) == []
    with engine.store.connect() as db:
        assert not db.execute("SELECT 1 FROM observation_jobs WHERE status='pending'").fetchone()
        assert db.execute("SELECT 1 FROM observation_jobs WHERE status='missed'").fetchone()


@pytest.mark.parametrize("age,state", [(48 * 3600, "background"), (48 * 3600 + 1, "paused")])
def test_background_boundary_uses_ingestion_time_not_last_quote(client_engine, age, state):
    from app import opportunity_lifecycle as lifecycle

    _, engine = client_engine
    c = observed(engine, 15018, age)
    with engine.store.connect() as db:
        at = db.execute(
            "SELECT ingested_at FROM opportunity_candidates WHERE id=?", (c["id"],)
        ).fetchone()[0]
        from app.models import epoch

        value = lifecycle.candidates(engine, db, engine.config(), [c["id"]], epoch(at) + age)
    assert value[c["id"]]["state"] == state


@pytest.mark.parametrize(
    "evidence,offset",
    [
        ({"association": "name_similarity"}, 0),
        (
            {
                "association": "resolved_market_pair_reference",
                "market_reference": {"qualifies_for_discovery": False},
            },
            0,
        ),
        ({"association": "exact_contract_document_mention"}, 60),
        ({"association": "exact_contract_document_mention"}, -901),
    ],
)
def test_unsupported_future_or_expired_story_cannot_reactivate(client_engine, evidence, offset):
    _, engine = client_engine
    c = observed(engine, 15019, 5 * 86400)
    with engine.store.connect() as db:
        db.execute(
            "INSERT INTO story_pool_lookups(contract,first_seen_at,next_due,state,payload) VALUES(?,?,0,'existing_candidate',?)",
            (
                c["contract"],
                stamp(time.time()),
                json.dumps(
                    {"last_checked_at": stamp(time.time() + offset), "current_evidence": evidence}
                ),
            ),
        )
    assert engine.detail(c["id"])["monitoring"]["state"] == "paused"
    assert engine.due(engine.config()) == []
