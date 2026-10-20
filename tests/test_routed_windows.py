"""Frozen Jupiter window policies; synthetic providers and actual SQLite orchestration."""

import json
from decimal import Decimal

import pytest

from app.models import epoch
from app.opportunity_routes import Routes
from tests.test_observation_sampling import legacy_policy
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, stamp
from tests.test_opportunity_routes import execute
from tests.test_opportunity_routes import routed as routed


@pytest.fixture(params=[None, 2], ids=["legacy", "v2"])
def window_route(request, client_engine, monkeypatch):
    # Declare each synthetic policy before its first signal is recorded.
    version = request.param
    original = Routes.policy

    def policy(self, config):
        p = original(self, config)
        if version is None:
            p.pop("forward_quote_window_version", None)
        else:
            p["forward_quote_window_version"] = version
        return p

    monkeypatch.setattr(Routes, "policy", policy)
    r = request.getfixturevalue("routed")
    return r, version


def snapshot(r):
    with r.engine.store.connect() as db:
        return [
            tuple(row)
            for row in db.execute(
                "SELECT policy FROM routed_experiments WHERE signal_id=?", (r.signal_id,)
            )
        ]


def save(r, *, quote_at=None, missing=False, unsafe=False):
    value = (
        {"market": None} if missing else payload(r.engine, r.candidate, r.clock[0], unsafe=unsafe)
    )
    if quote_at is not None:
        value["market"]["observed_at"] = stamp(quote_at)
    return r.engine.save_observation(r.candidate, value, r.policy, r.config, stamp(r.clock[0]))[0]


def detail(r):
    return r.engine.routes.detail(r.candidate["id"])


def outcome(r):
    return next(
        o
        for o in detail(r)["outcomes"]
        if o["signal_id"] == r.signal_id and o["horizon_seconds"] == 300
    )


def job(r, phase):
    with r.engine.store.connect() as db:
        return dict(
            db.execute(
                "SELECT * FROM observation_jobs WHERE signal_id=? AND phase=?",
                (r.signal_id, phase),
            ).fetchone()
        )


def test_entry_prefetch_waits_only_under_new_frozen_policy(window_route):
    r, version = window_route
    before = snapshot(r)
    # The second fixture row was stored after entry due, but uses a prefetched price.
    with r.engine.store.connect() as db:
        db.execute(
            "UPDATE opportunity_observations SET payload=json_set(payload,'$.market.observed_at',?) "
            "WHERE candidate_id=? AND id=(SELECT max(id) FROM opportunity_observations WHERE candidate_id=?)",
            (stamp(r.clock[0] - 4), r.candidate["id"], r.candidate["id"]),
        )
    execute(r)
    if version is None:
        assert detail(r)["entries"][0]["entry_state"] == "entry_unavailable"
        assert "before the observation window" in detail(r)["entries"][0]["reason"]
        assert not r.calls
    else:
        assert detail(r)["entries"][0]["entry_state"] == "entry_pending"
        assert not detail(r)["attempts"] and not r.calls
    r.clock[0] += 1
    observed_id = save(r)
    execute(r)
    if version == 2:
        assert detail(r)["entries"][0]["entry_state"] == "filled"
        assert detail(r)["attempts"][0]["observation_id"] == observed_id
    else:
        assert detail(r)["entries"][0]["entry_state"] == "entry_unavailable"
    assert snapshot(r) == before


def test_exit_prefetch_and_sampler_use_the_same_frozen_rule(window_route):
    r, version = window_route
    before = snapshot(r)
    execute(r)
    r.clock[0] += 301
    prefetched_id = save(r, quote_at=r.clock[0] - 2)
    execute(r)
    if version is None:
        assert outcome(r)["state"] == "exit_unavailable"
        assert "before the observation window" in outcome(r)["payload"]["reason"]
        assert job(r, "routed_exit")["status"] == "attempted"
        assert job(r, "routed_exit")["observation_id"] == prefetched_id
        assert job(r, "routed_exit")["reason"] == "quote_before_window"
    else:
        assert outcome(r)["state"] == "pending"
        assert job(r, "routed_exit")["status"] == "pending"
        assert job(r, "routed_exit")["observation_id"] is None
        assert len(detail(r)["attempts"]) == 1
    r.clock[0] += 1
    observed_id = save(r)
    execute(r)
    if version == 2:
        assert outcome(r)["state"] == "evaluated"
        assert job(r, "routed_exit")["observation_id"] == observed_id
        assert detail(r)["attempts"][-1]["observation_id"] == observed_id
        assert Decimal(outcome(r)["payload"]["pnl_usd"]) < 0
        assert outcome(r)["payload"]["actual_hold_seconds"] == 302
    else:
        assert outcome(r)["state"] == "exit_unavailable"
    assert snapshot(r) == before


@pytest.mark.parametrize("failure", ["missing", "unsafe", "http"])
def test_first_post_window_failure_is_terminal_even_if_later_data_improves(window_route, failure):
    r, _ = window_route
    execute(r)
    r.clock[0] += 301
    first_id = save(r, missing=failure == "missing", unsafe=failure == "unsafe")
    if failure == "http":
        r.failure[0] = 400
    execute(r)
    assert outcome(r)["state"] == "exit_unavailable"
    assert outcome(r)["payload"]["pnl_usd"] is None
    assert detail(r)["attempts"][-1]["observation_id"] == first_id
    original = json.dumps(outcome(r), sort_keys=True)
    calls = len(r.calls)
    r.failure[0] = None
    r.clock[0] += 1
    save(r)
    execute(r)
    assert json.dumps(outcome(r), sort_keys=True) == original
    assert len(r.calls) == calls


def test_prefetch_never_extends_exit_deadline(window_route):
    r, version = window_route
    execute(r)
    due = outcome(r)["target_at"]
    r.clock[0] = due + r.config.exit_window_seconds
    save(r, quote_at=due - 1)
    execute(r)
    r.clock[0] += 0.001
    execute(r)
    assert outcome(r)["state"] == "exit_unavailable"
    assert outcome(r)["payload"]["pnl_usd"] is None
    expected = "quote_deadline_missed" if version == 2 else "before the observation window"
    assert expected in outcome(r)["payload"]["reason"]
    assert len(detail(r)["attempts"]) == (1 if version == 2 else 2)
    assert epoch(detail(r)["entries"][0]["entry_at"]) + 300 == due


def test_new_routed_policy_declares_its_window_rule(routed):
    p = detail(routed)["entries"][0]["policy"]
    assert p["version"] == "jupiter-forward-v2"
    assert p["forward_quote_window_version"] == 2


def test_sampler_does_not_inherit_pool_version_for_routed_jobs(client_engine):
    import time

    from tests.test_opportunities import seed

    _, engine = client_engine
    c, p, cfg = seed(engine)
    p = legacy_policy(engine, p)  # pool v1, routed v2, both frozen before the signal
    now = time.time()
    _, sid = engine.save_observation(c, payload(engine, c, now), p, cfg, stamp(now))
    with engine.store.connect() as db:
        for phase in ["checkpoint", "routed_exit"]:
            engine.sampling.job(db, c["id"], sid, phase, 300, now + 300, now + 480)
    early = payload(engine, c, now + 301)
    early["market"]["observed_at"] = stamp(now + 299)
    engine.save_observation(c, early, p, cfg, stamp(now + 301))
    with engine.store.connect() as db:
        states = dict(
            db.execute(
                "SELECT phase,status FROM observation_jobs WHERE signal_id=? AND horizon_seconds=300",
                (sid,),
            )
        )
    assert states == {"checkpoint": "attempted", "routed_exit": "pending"}


def test_quote_exactly_at_due_is_eligible(window_route):
    r, _ = window_route
    execute(r)
    due = outcome(r)["target_at"]
    r.clock[0] = due
    observed_id = save(r, quote_at=due)
    execute(r)
    assert outcome(r)["state"] == "evaluated"
    assert detail(r)["attempts"][-1]["observation_id"] == observed_id
    assert outcome(r)["payload"]["actual_hold_seconds"] == 300


def test_window_selection_keeps_first_actual_failure_when_later_data_already_exists(window_route):
    r, _ = window_route
    execute(r)
    r.clock[0] += 301
    first_id = save(r, missing=True)
    r.clock[0] += 1
    save(r)
    execute(r)
    assert outcome(r)["state"] == "exit_unavailable"
    assert outcome(r)["payload"]["pnl_usd"] is None
    assert detail(r)["attempts"][-1]["observation_id"] == first_id
