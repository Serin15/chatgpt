"""Regressions with real SQLite and isolated providers; no live trading."""

import time

import pytest

from app import opportunity_lifecycle as lifecycle
from tests.test_candidate_lifecycle import observed
from tests.test_observation_sampling import scheduled
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, stamp


def watch(engine, c, kind):
    if kind == "watchlist":
        engine.store.add_token(c["contract"], "fixture_watch", watch=True)
    else:
        store = engine.store if kind == "scanner_position" else engine.service.news_paper
        with store.connect() as db:
            db.execute(
                "INSERT INTO positions(address,quantity,entry_cost,entry_at,entry_snapshot_id,signal_id) VALUES(?,'1','1',?,1,1)",
                (c["contract"], stamp(time.time() - 86400)),
            )


@pytest.mark.parametrize("kind", ["watchlist", "scanner_position", "news_position"])
def test_old_watched_token_keeps_active_polling_interval(client_engine, kind):
    _, engine = client_engine
    c = observed(engine, 19001, 5 * 86400)
    watch(engine, c, kind)
    now = time.time()
    cfg = engine.config()
    engine.save_observation(c, payload(engine, c, now), engine.policy(cfg), cfg, stamp(now))
    with engine.store.connect() as db:
        row = db.execute("SELECT * FROM opportunity_candidates WHERE id=?", (c["id"],)).fetchone()
    assert row["next_due"] == pytest.approx(now + cfg.interval_seconds, abs=0.001)


@pytest.mark.parametrize("kind", ["watchlist", "scanner_position", "news_position"])
def test_new_watch_bypasses_existing_daily_schedule_without_rewriting_history(client_engine, kind):
    _, engine = client_engine
    c = observed(engine, 19002, 5 * 86400)
    now = time.time()
    with engine.store.connect() as db:
        db.execute(
            "UPDATE opportunity_candidates SET last_attempt_at=?,next_due=? WHERE id=?",
            (stamp(now - 120), now + 86000, c["id"]),
        )
    watch(engine, c, kind)
    before = engine.detail(c["id"])
    chosen = engine.due(engine.config())
    assert c["id"] in {r["id"] for r in chosen}
    after = engine.detail(c["id"])
    assert before["signals"] == after["signals"]
    assert before["outcomes"] == after["outcomes"]
    assert before["next_due"] == after["next_due"], "Selection must not rewrite stored schedules"
    assert engine.queue_health()["dispatchable_due"] == 1


def test_due_followups_cannot_consume_every_active_watch_slot(client_engine):
    _, engine = client_engine
    now = time.time()
    # Twelve due research subjects used to consume all twelve slots, even though
    # only six were the explicitly protected, balanced follow-up allocation.
    for i in range(12):
        scheduled(engine, 19100 + i, now - 20, selected=i % 2 == 0, control=i % 2 == 1)
    active = observed(engine, 19200, 600)
    cfg = engine.config().model_copy(update={"observation_budget": 12})
    chosen = engine.due(cfg)
    assert active["id"] in {r["id"] for r in chosen}
    assert len(chosen) == len({r["id"] for r in chosen}) == 12
    assert sum(r["collection_lane"] == "protected_followup" for r in chosen) == 6


def test_earliest_actual_deadline_runs_first_after_balanced_allocation(client_engine):
    _, engine = client_engine
    now = time.time()
    later, _ = scheduled(engine, 19300, now - 10, selected=True)
    urgent, _ = scheduled(engine, 19301, now - 160, control=True)
    cfg = engine.config().model_copy(update={"observation_budget": 4})
    chosen = engine.due(cfg)
    assert [r["id"] for r in chosen] == [urgent["id"], later["id"]]
    assert chosen[0]["collection_deadline"] < chosen[1]["collection_deadline"]


def test_queue_freshness_distinguishes_recent_research_from_background(client_engine):
    _, engine = client_engine
    active = observed(engine, 19400, 600)
    observed(engine, 19401, 86400, due_age=3600)
    cfg = engine.config()
    now = time.time()
    summary = lifecycle.summary(engine, cfg, now)
    assert summary["counts_by_state"]["active"]["stale_attempts"] == 1
    assert summary["counts_by_state"]["active"]["oldest_due_delay_seconds"] < 60
    assert summary["counts_by_state"]["background"]["oldest_due_delay_seconds"] >= 3600
    assert summary["priority_due"] == 1
    assert active["id"] in {r["id"] for r in engine.due(cfg)}


def test_new_discovery_and_watch_both_receive_slots_under_followup_pressure(client_engine):
    import json

    from tests.test_observation_sampling import candidate

    _, engine = client_engine
    now = time.time()
    for i in range(12):
        scheduled(engine, 19500 + i, now - 20, selected=i % 2 == 0, control=i % 2 == 1)
    fresh = [candidate(engine, 19600 + i, now) for i in range(4)]
    with engine.store.connect() as db:
        for c in fresh:
            db.execute(
                "UPDATE opportunity_candidates SET next_due=?,discovery=? WHERE id=?",
                (now - 1, json.dumps(c["discovery"] | {"imported_from_cache": False}), c["id"]),
            )
    watched = observed(engine, 19700, 5 * 86400)
    watch(engine, watched, "news_position")
    cfg = engine.config().model_copy(update={"observation_budget": 12})
    chosen = engine.due(cfg)
    assert {c["id"] for c in fresh} <= {r["id"] for r in chosen}
    assert watched["id"] in {r["id"] for r in chosen}
    assert len(chosen) == len({r["id"] for r in chosen}) == 12


def test_watched_provider_failure_preserves_backoff_and_unknown_outcome(client_engine):
    _, engine = client_engine
    c = observed(engine, 19800, 5 * 86400)
    watch(engine, c, "watchlist")
    now, cfg = time.time(), engine.config()
    engine.save_observation(
        c, {"market": None, "error": "fixture outage"}, engine.policy(cfg), cfg, stamp(now)
    )
    with engine.store.connect() as db:
        row = db.execute("SELECT * FROM opportunity_candidates WHERE id=?", (c["id"],)).fetchone()
    assert row["next_due"] == pytest.approx(now + 2 * cfg.interval_seconds, abs=0.001)
    assert row["failures"] == 1
    assert c["id"] not in {r["id"] for r in engine.due(cfg)}
    assert engine.detail(c["id"])["observations"][-1]["market"] is None


@pytest.mark.parametrize(
    "association,active", [("exact_contract_document_mention", True), ("name_similarity", False)]
)
def test_only_documented_recent_story_can_shorten_daily_schedule(
    client_engine, association, active
):
    import json

    _, engine = client_engine
    c = observed(engine, 19900, 5 * 86400)
    now = time.time()
    with engine.store.connect() as db:
        db.execute(
            "UPDATE opportunity_candidates SET last_attempt_at=?,next_due=? WHERE id=?",
            (stamp(now - 120), now + 86000, c["id"]),
        )
        db.execute(
            "INSERT INTO story_pool_lookups VALUES(?,?,?,0,'existing_candidate',?)",
            (
                c["contract"],
                stamp(now),
                now,
                json.dumps(
                    {
                        "last_checked_at": stamp(now),
                        "current_evidence": {"association": association},
                    }
                ),
            ),
        )
    assert (c["id"] in {r["id"] for r in engine.due(engine.config())}) is active


def test_future_attempt_timestamp_is_unknown_not_recent(client_engine):
    _, engine = client_engine
    c = observed(engine, 19910, 600)
    now = time.time()
    with engine.store.connect() as db:
        db.execute(
            "UPDATE opportunity_candidates SET last_attempt_at=? WHERE id=?",
            (stamp(now + 60), c["id"]),
        )
    state = lifecycle.summary(engine, now=now)["counts_by_state"]["active"]
    assert state["recent_attempts"] == 0
    assert state["invalid_attempt_timestamps"] == 1


def test_watch_respects_a_custom_success_interval_longer_than_retry_cap(client_engine, monkeypatch):
    _, engine = client_engine
    c = observed(engine, 19920, 5 * 86400)
    watch(engine, c, "watchlist")
    cfg = engine.config().model_copy(update={"interval_seconds": 1200})
    engine.configure(cfg)
    now = time.time()
    engine.save_observation(c, payload(engine, c, now), engine.policy(cfg), cfg, stamp(now))
    monkeypatch.setattr("app.opportunity_sampling.time.time", lambda: now + 901)
    assert c["id"] not in {r["id"] for r in engine.due(cfg)}
