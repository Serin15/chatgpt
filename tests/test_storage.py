"""Actual SQLite/ZIP/OS locks; no network, no real-money execution."""

import json
import sqlite3
import time
import zipfile
import zlib
from datetime import UTC, datetime, timedelta

import pytest

from app.archive_codec import MAGIC, decode, encode
from app.daily_research import daily_report
from app.maintenance import backup
from app.research_evaluate import ReadOnlyStore
from app.runtime_lock import RuntimeLock
from app.storage import archive_database, capacity, logical_manifest, maintain, restore_backup
from tests.test_opportunities import client_engine as client_engine
from tests.test_opportunities import payload, seed, stamp


def cold_history(engine):
    c, policy, config = seed(engine)
    old = time.time() - 10 * 86400
    for offset in (0, 301, 604):
        at = old + offset
        engine.save_observation(c, payload(engine, c, at), policy, config, stamp(at))
    cutoff = stamp(time.time() - 3 * 86400)
    return c, cutoff


def test_archived_baseline_remains_readable_in_sql_and_readonly_report(client_engine):
    client, engine = client_engine
    c, cutoff = cold_history(engine)
    before = daily_report(engine)
    history = engine.history(c["id"])
    manifest = logical_manifest(engine.store.path)
    run = archive_database(engine.store.path, cutoff)
    assert run["tables"]["opportunity_observations"]["rows_compressed"] == 2
    assert engine.history(c["id"]) == history
    assert logical_manifest(engine.store.path) == manifest
    after = daily_report(engine)
    for key in ("totals", "groups", "reference_prices", "comparisons"):
        if key in before:
            assert after[key] == before[key]
    assert client.get("/api/opportunities").status_code == 200
    assert client.get(f"/api/opportunities/{c['id']}").status_code == 200
    assert client.get("/api/opportunities/performance").status_code == 200
    read_engine = type("ReadOnlyEngine", (), {"store": ReadOnlyStore(engine.store.path)})()
    assert daily_report(read_engine)["totals"] == before["totals"]
    assert (
        archive_database(engine.store.path, cutoff)["tables"]["opportunity_observations"][
            "rows_compressed"
        ]
        == 0
    )


def test_codec_exact_unicode_and_corruption_rejected():
    value = json.dumps(
        {"text": "Știre românească 🐕 " * 1000, "tiny_price": "0.00000000000123"},
        ensure_ascii=False,
    )
    packed = encode(value)
    assert isinstance(packed, bytes) and packed.startswith(MAGIC)
    assert decode(packed) == value
    assert encode(packed) == packed
    assert encode("{}") == "{}"
    for broken in (
        packed[:-3],
        packed + b"trailing",
        packed[: len(MAGIC) + 1],
        packed[: len(MAGIC) + 8] + b"x" * 32 + packed[len(MAGIC) + 40 :],
    ):
        with pytest.raises((ValueError, zlib.error)):
            decode(broken)


def test_offline_maintenance_refuses_running_application(client_engine):
    _, engine = client_engine
    with pytest.raises(ValueError, match="Close MemeScope"):
        maintain(engine.store.path.parent, days=3)


def test_low_disk_health_does_not_block_status_or_candidates(client_engine, monkeypatch):
    client, _ = client_engine
    fake = type("Disk", (), {"free": 1, "total": 100})()
    monkeypatch.setattr("app.storage.shutil.disk_usage", lambda _: fake)
    response = client.get("/api/status")
    assert response.status_code == 200 and response.json()["storage"]["state"] == "error"
    assert client.get("/api/opportunities").status_code == 200


def test_runtime_lock_is_exclusive_and_released(tmp_path):
    with RuntimeLock(tmp_path):
        with pytest.raises(ValueError, match="in use"):
            with RuntimeLock(tmp_path):
                pass
    with RuntimeLock(tmp_path):
        pass


def test_restore_rejects_paths_duplicates_and_existing_directory(tmp_path):
    for i, names in enumerate(
        (
            ["research.sqlite3", "../escape"],
            ["research.sqlite3", "research.sqlite3"],
            ["research.sqlite3", "news_paper/research.sqlite3", ".env"],
        )
    ):
        archive = tmp_path / f"bad-{i}.zip"
        with zipfile.ZipFile(archive, "w") as package:
            for name in names:
                if name in package.namelist():
                    with pytest.warns(UserWarning, match="Duplicate"):
                        package.writestr(name, "not a database")
                else:
                    package.writestr(name, "not a database")
        with pytest.raises(ValueError, match="exactly"):
            restore_backup(archive, tmp_path / f"out-{i}")
    with pytest.raises(ValueError, match="must not exist"):
        restore_backup(tmp_path / "absent.zip", tmp_path)
    assert not (tmp_path.parent / "escape").exists()


def test_archive_retention_preserves_latest_snapshots_and_ids(store):
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    original = json.dumps({"data": "original " * 2000})
    with store.connect() as db:
        for i in range(1, 4):
            db.execute(
                "INSERT INTO snapshots VALUES(?,?,?,?,?,?)",
                (i, "token", old, original, original, original),
            )
    before = logical_manifest(store.path)
    run = archive_database(store.path, stamp(time.time() - 3 * 86400), batch_size=1)
    assert run["tables"]["snapshots"]["rows_compressed"] == 2
    assert logical_manifest(store.path) == before
    assert store.latest("token")["id"] == 3
    with sqlite3.connect(store.path) as db:
        assert db.execute("SELECT typeof(market) FROM snapshots WHERE id=1").fetchone()[0] == "blob"
        assert db.execute("SELECT typeof(market) FROM snapshots WHERE id=3").fetchone()[0] == "text"
    with store.connect() as db:
        row = db.execute(
            "INSERT INTO snapshots(address,at,market,security,analysis) VALUES(?,?,?,?,?)",
            ("token", old, original, original, original),
        )
        assert row.lastrowid == 4


def test_complete_maintenance_backup_compact_restore_and_report(client_engine, tmp_path):
    client, engine = client_engine
    c, _ = cold_history(engine)
    assert client.get("/api/storage").json()["history_deleted"] is False
    directory = engine.store.path.parent
    before = logical_manifest(engine.store.path)
    news_before = logical_manifest(engine.service.news_paper.path)
    config_before = engine.config().model_dump_json()
    history = engine.history(c["id"])
    # Offline operator: release the application lifetime lock without changing data.
    client.__exit__(None, None, None)
    result = maintain(directory, days=3, compact=True)
    assert result["logical_history_identical"] and result["backup_restore_verified"]
    assert result["manifests"]["research.sqlite3"] == before
    assert result["manifests"]["news_paper/research.sqlite3"] == news_before
    assert engine.config().model_dump_json() == config_before
    assert engine.history(c["id"]) == history
    assert capacity(directory)["databases"][0]["last_archive"]
    archived_zip = backup(engine.service)
    restored = tmp_path / "restored with spaces # % ș"
    proof = restore_backup(archived_zip, restored)
    assert proof["research.sqlite3"] == before
    assert proof["news_paper/research.sqlite3"] == news_before
    readonly = type("ReadOnlyEngine", (), {"store": ReadOnlyStore(restored / "research.sqlite3")})()
    assert daily_report(readonly)["totals"] == daily_report(engine)["totals"]
    assert not (restored / ".env").exists()


def test_failed_batch_rolls_back_without_losing_payloads(store, monkeypatch):
    old = stamp(time.time() - 10 * 86400)
    value = json.dumps({"evidence": "unchanged" * 300})
    with store.connect() as db:
        db.executemany(
            "INSERT INTO snapshots VALUES(?,?,?,?,?,?)",
            [(i, "same", old, value, value, value) for i in range(1, 4)],
        )
    before = logical_manifest(store.path)
    original, calls = encode, []

    def interrupted(v):
        calls.append(v)
        if len(calls) == 4:
            raise OSError("Injected disk failure")
        return original(v)

    monkeypatch.setattr("app.storage.encode", interrupted)
    with pytest.raises(OSError, match="Injected"):
        archive_database(store.path, stamp(time.time() - 3 * 86400))
    assert logical_manifest(store.path) == before


def test_low_space_cancels_before_backup_or_payload_changes(client_engine, monkeypatch):
    client, engine = client_engine
    cold_history(engine)
    client.__exit__(None, None, None)
    before = logical_manifest(engine.store.path)
    fake = type("Disk", (), {"free": 1, "total": 100})()
    monkeypatch.setattr("app.storage.shutil.disk_usage", lambda _: fake)
    assert capacity(engine.store.path.parent)["state"] == "critical"
    with pytest.raises(ValueError, match="Insufficient disk space"):
        maintain(engine.store.path.parent, days=3)
    assert logical_manifest(engine.store.path) == before
    assert list((engine.store.path.parent / "backups").glob("*.zip")) == []


def test_corrupt_archive_is_an_error_not_missing_or_zero(store):
    old = stamp(time.time() - 10 * 86400)
    value = json.dumps({"data": "original" * 1000})
    packed = encode(value)
    with store.connect() as db:
        db.execute(
            "INSERT INTO snapshots VALUES(1,'token',?,?,?,?)", (old, packed[:-1], value, value)
        )
    with pytest.raises((ValueError, zlib.error)):
        logical_manifest(store.path)
    with pytest.raises((ValueError, zlib.error)):
        store.latest("token")


def test_unknown_binary_format_and_oversized_archive_are_rejected(store):
    import struct

    from app.archive_codec import MAX_BYTES

    old = stamp(time.time() - 10 * 86400)
    with store.connect() as db:
        db.execute(
            "INSERT INTO snapshots VALUES(1,'token',?,?,?,?)", (old, b"unknown archive", "{}", "{}")
        )
    with pytest.raises(ValueError, match="Unknown or damaged"):
        logical_manifest(store.path)
    with pytest.raises(ValueError, match="limit"):
        decode(MAGIC + struct.pack(">Q", MAX_BYTES + 1) + b"x" * 32)


def test_restore_corrupt_database_never_publishes_destination(tmp_path):
    archive = tmp_path / "invalid.zip"
    target = tmp_path / "must not appear"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("research.sqlite3", b"not SQLite")
        package.writestr("news_paper/research.sqlite3", b"not SQLite")
    with pytest.raises(sqlite3.Error):
        restore_backup(archive, target)
    assert not target.exists()


def test_backup_failure_never_publishes_partial_zip(client_engine, monkeypatch):
    _, engine = client_engine

    def broken(*_):
        raise OSError("Injected ZIP failure")

    monkeypatch.setattr(zipfile.ZipFile, "write", broken)
    with pytest.raises(OSError, match="Injected ZIP"):
        backup(engine.service)
    assert list((engine.store.path.parent / "backups").iterdir()) == []
