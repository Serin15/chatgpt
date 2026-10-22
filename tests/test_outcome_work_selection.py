"""Future paper horizons must not starve entry/due work or lose new observations."""

import json
import time

from tests.test_observation_sampling import candidate
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, stamp


def test_large_unchanged_future_backlog_does_not_starve_new_entry(client_engine):
    _, engine = client_engine
    c, policy, config = seed(engine)
    now = time.time()
    engine.save_observation(c, payload(engine, c, now - 300), policy, config, stamp(now - 300))
    engine.save_observation(c, payload(engine, c, now - 295), policy, config, stamp(now - 295))
    engine.update_outcomes(now - 294)
    with engine.store.connect() as db:
        template = db.execute("SELECT * FROM opportunity_signals WHERE kind='baseline'").fetchone()
        future = db.execute(
            "SELECT payload FROM opportunity_outcomes WHERE signal_id=? AND horizon_seconds=86400",
            (template["id"],),
        ).fetchone()[0]
        assert json.loads(future)["entry_quote"]
        for _ in range(2001):
            signal = db.execute(
                "INSERT INTO opportunity_signals(candidate_id,observation_id,at,kind,verdict,policy_id,payload) VALUES(?,?,?,'change',?,?,?)",
                (
                    c["id"],
                    template["observation_id"],
                    template["at"],
                    template["verdict"],
                    template["policy_id"],
                    template["payload"],
                ),
            )
            db.execute(
                "INSERT INTO opportunity_outcomes VALUES(?,86400,'pending',?,?)",
                (signal.lastrowid, future, stamp(now - 100)),
            )
        db.execute(
            "UPDATE opportunity_outcomes SET updated_at=? WHERE signal_id=?",
            (stamp(now - 100), template["id"]),
        )
    urgent = candidate(engine, 123451, now - 10)
    _, sid = engine.save_observation(
        urgent, payload(engine, urgent, now - 10), policy, config, stamp(now - 10)
    )
    engine.save_observation(
        urgent, payload(engine, urgent, now - 5), policy, config, stamp(now - 5)
    )
    with engine.store.connect() as db:
        # Reproduce the old budget being filled by unchanged, not-yet-due work.
        old = db.execute(
            "SELECT signal_id FROM opportunity_outcomes WHERE state='pending' ORDER BY updated_at,signal_id,horizon_seconds LIMIT 2000"
        ).fetchall()
        assert sid not in {r[0] for r in old}
        before = db.execute(
            "SELECT count(*) FROM opportunity_outcomes WHERE updated_at=? AND payload=?",
            (stamp(now - 100), future),
        ).fetchone()[0]
    engine.update_outcomes(now)
    with engine.store.connect() as db:
        updated = json.loads(
            db.execute(
                "SELECT payload FROM opportunity_outcomes WHERE signal_id=? AND horizon_seconds=300",
                (sid,),
            ).fetchone()[0]
        )
        assert updated["entry_quote"]
        assert (
            db.execute(
                "SELECT count(*) FROM opportunity_outcomes WHERE updated_at=? AND payload=?",
                (stamp(now - 100), future),
            ).fetchone()[0]
            == before
        )


def test_new_observations_refresh_future_extrema_and_due_horizon_still_settles(client_engine):
    _, engine = client_engine
    c, policy, config = seed(engine)
    now = time.time()
    engine.save_observation(c, payload(engine, c, now), policy, config, stamp(now))
    engine.save_observation(c, payload(engine, c, now + 4), policy, config, stamp(now + 4))
    engine.update_outcomes(now + 5)
    engine.save_observation(
        c, payload(engine, c, now + 10, price=1.2), policy, config, stamp(now + 10)
    )
    engine.update_outcomes(now + 11)
    first = next(o for o in engine.detail(c["id"])["outcomes"] if o["horizon_seconds"] == 300)
    assert first["state"] == "pending" and first["payload"]["mfe_observed_pct"] > 19
    target = first["payload"]["target_at_epoch"]
    engine.save_observation(
        c, payload(engine, c, target + 1, price=0.8), policy, config, stamp(target + 1)
    )
    engine.update_outcomes(target + 2)
    final = next(o for o in engine.detail(c["id"])["outcomes"] if o["horizon_seconds"] == 300)
    assert final["state"] == "evaluated"
    assert float(final["payload"]["pnl_usd"]) < 0
    assert final["payload"]["entry_quote"] == first["payload"]["entry_quote"]
    assert final["payload"]["mfe_observed_pct"] > 19
