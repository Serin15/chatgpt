"""Explicit fixtures for frozen cohorts, missing outcomes and read-only exports."""

import hashlib
import os
import sqlite3
from types import SimpleNamespace

import pytest

from app.cohort_comparisons import comparisons, partition, protocol
from app.daily_research import daily_report, summarize
from app.research_evaluate import ReadOnlyStore
from app.research_evaluate import main as export_main
from tests.test_opportunities import client_engine as client_engine


def subject(**changes):
    return {
        "config_parsed": {
            "test_from": "2026-10-18T00:00:00Z",
            "entry_window_seconds": 180,
            "exit_window_seconds": 180,
            "horizons_seconds": [300],
            "routed_quotes_enabled": False,
        },
        "signal_at": "2026-10-18T00:01:00Z",
        "policy_at": "2026-10-16T00:00:00Z",
        "policy_id": 1,
        "provenance": "prospective",
        "enrolled_at": "2026-10-18T00:00:00Z",
        "selected": False,
        "control_member": True,
    } | changes


def test_disjoint_comparison_keeps_missing_and_overlap_in_denominators():
    firsts = {
        1: subject(selected=True),
        2: subject(selected=True, control_member=False),
        3: subject(),
        4: subject(),
        5: subject(provenance="legacy"),
    }
    rows = [
        {"signal_id": 1, "horizon_seconds": 300, "state": "evaluated", "pnl": "10"},
        {"signal_id": 3, "horizon_seconds": 300, "state": "evaluated", "pnl": "-5"},
    ]
    p = comparisons(firsts, rows, 300, "estimated_pool", summarize)["1"]["test"]
    assert p["all_first_evaluations"]["experiments"] == 5
    assert p["selected_at_first_evaluation"]["win_fraction_sensitivity_bounds_all_planned"] == [
        0.5,
        1,
    ]
    assert p["selected_at_first_evaluation"]["unresolved_or_unavailable"] == 1
    assert p["control_excluding_selected"]["experiments"] == 2
    assert p["control_excluding_selected"]["nonprofitable_rate_among_evaluated"] == 1
    assert p["overlap"] == 1 and p["conditional_mean_difference_usd"] == "15"
    routed = comparisons(firsts, [], 300, "jupiter_quotes", summarize)["1"]["test"]
    assert routed["all_first_evaluations"]["states"] == {"disabled_at_signal": 5}
    assert routed["conditional_mean_difference_usd"] is None
    assert comparisons(firsts, [], 3600, "estimated_pool", summarize) == {}


@pytest.mark.parametrize(
    "when,expected",
    [
        ("2026-10-16T01:00:00Z", "development"),
        ("2026-10-17T23:55:00Z", "purged_boundary"),
        ("2026-10-18T00:00:00Z", "test"),
    ],
)
def test_frozen_partitions(when, expected):
    assert partition(subject(signal_at=when), 300) == expected


def test_late_policy_and_impossible_declaration_do_not_create_holdout():
    s = subject(policy_at="2026-10-19T00:00:00Z")
    assert partition(s, 300) == "unassigned"
    assert protocol({1: s}, "2026-10-20T00:00:00Z")["policies"]["1"]["state"] == "unassigned"
    s = subject(policy_at="2026-10-17T00:00:00Z", signal_at="2026-10-16T00:00:00Z")
    assert protocol({1: s}, "2026-10-20T00:00:00Z")["policies"]["1"]["state"] == "unassigned"


def test_offline_store_is_read_only_and_handles_uri_characters(client_engine, tmp_path):
    _, engine = client_engine
    path = tmp_path / "spaces # percent % & Ș.sqlite3"
    with engine.store.connect() as source, sqlite3.connect(path) as target:
        source.backup(target)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    store = ReadOnlyStore(path)
    daily_report(SimpleNamespace(store=store))
    with store.connect() as db:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM opportunity_candidates")
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before
    missing = tmp_path / "missing.sqlite3"
    with pytest.raises(ValueError):
        ReadOnlyStore(missing)
    assert not missing.exists()


def test_export_cannot_overwrite_database_through_hard_link(client_engine, tmp_path, monkeypatch):
    _, engine = client_engine
    folder = tmp_path / "export data"
    folder.mkdir()
    database = folder / "research.sqlite3"
    with engine.store.connect() as source, sqlite3.connect(database) as target:
        source.backup(target)
    target.close()
    output = folder / "report.json"
    try:
        os.link(database, output)
    except OSError:
        pytest.skip("Filesystem does not support hard links")
    before = database.read_bytes()
    monkeypatch.setattr(
        "sys.argv", ["research_evaluate", "--data-dir", str(folder), "--output", str(output)]
    )
    export_main()
    assert database.read_bytes() == before
    assert output.read_text().startswith("{")
