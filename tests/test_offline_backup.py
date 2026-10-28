"""Real offline SQLite/ZIP restore. Capacity/volume identities are simulated where stated."""

import hashlib
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.maintenance import backup
from app.offline_backup import (
    ArchiveLimitExceeded,
    BudgetFile,
    create_backup,
    plan_backup,
    verify_archive,
)
from app.runtime_lock import RuntimeLock
from app.storage import DATABASES, RESERVE, InsufficientSpace, logical_manifest, restore_backup
from tests.test_opportunities import client_engine as client_engine


def offline(client_engine):
    client, engine = client_engine
    root = engine.store.path.parent
    client.__exit__(None, None, None)
    return root, engine


def test_offline_backup_preserves_all_rows_and_restores_with_existing_command(
    client_engine, tmp_path,
):
    root, _ = offline(client_engine)
    before = {name: logical_manifest(root / name) for name in DATABASES}
    out, work = tmp_path / "Backup știri #1", tmp_path / "Verification work"
    result = create_backup(root, out, work)
    archive = Path(result["archive"])
    assert result["restoration_verified"] and result["live_execution"] is False
    assert result["independent_offsite_backup_verified"] is False
    assert result["sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as z:
        assert set(z.namelist()) == set(DATABASES)
        assert z.testzip() is None
        metadata = json.loads(z.comment)
        assert metadata["format"] == "memescope-offline-backup-v1"
        for name in DATABASES:
            assert hashlib.sha256(z.read(name)).hexdigest() == result["files"][name]["sha256"]
    assert restore_backup(archive, tmp_path / "Restored data") == before
    assert {name: logical_manifest(root / name) for name in DATABASES} == before
    assert not list(work.iterdir()) and not list(out.glob("*.partial"))


def test_running_app_prevents_offline_backup(client_engine, tmp_path):
    _, engine = client_engine
    with pytest.raises(ValueError, match="Close MemeScope"):
        create_backup(engine.store.path.parent, tmp_path / "backups")


def test_checkpoint_includes_recent_committed_wal_and_blocks_other_sqlite_writers(
    client_engine, tmp_path,
):
    root, _ = offline(client_engine)
    source = sqlite3.connect(root / DATABASES[0])
    try:
        source.execute("PRAGMA journal_mode=WAL")
        source.execute("CREATE TABLE offline_proof(value TEXT)")
        source.execute("INSERT INTO offline_proof VALUES('committed in WAL')")
        source.commit()
        assert Path(str(root / DATABASES[0]) + "-wal").stat().st_size > 0
        checked = []

        def progress(phase, name):
            if phase == "compressing":
                with sqlite3.connect(root / name, timeout=.01) as other:
                    with pytest.raises(sqlite3.OperationalError, match="locked"):
                        other.execute("BEGIN IMMEDIATE")
                checked.append(name)

        result = create_backup(root, tmp_path / "backups", progress=progress)
        assert checked == list(DATABASES)
        restored = tmp_path / "restored"
        restore_backup(result["archive"], restored)
        with sqlite3.connect(restored / DATABASES[0]) as db:
            assert db.execute("SELECT value FROM offline_proof").fetchone()[0] == "committed in WAL"
    finally:
        source.close()


def test_bounded_compression_succeeds_where_online_conservative_budget_cannot(
    client_engine, tmp_path, monkeypatch,
):
    root, engine = offline(client_engine)
    with sqlite3.connect(root / DATABASES[0]) as db:
        db.execute("CREATE TABLE compression_proof(payload TEXT)")
        db.execute("INSERT INTO compression_proof VALUES(?)", ("preserved fixture " * 100000,))
    destination, work = tmp_path / "small output volume", tmp_path / "large work volume"
    destination.mkdir()
    work.mkdir()
    monkeypatch.setenv("PULSE_BACKUP_DIR", str(destination))
    monkeypatch.setenv("PULSE_BACKUP_WORK_DIR", str(work))
    monkeypatch.setattr("app.storage.volume_id", lambda p: str(p))
    monkeypatch.setattr("app.offline_backup.volume_id", lambda p: str(p))

    def disk(path):
        return type("Disk", (), {"free": RESERVE + (256 * 1024 if Path(path) == destination
                                                    else 8 * 1024 * 1024)})()

    monkeypatch.setattr("app.storage.shutil.disk_usage", disk)
    with pytest.raises(InsufficientSpace):
        backup(engine.service)
    result = create_backup(root)
    assert result["source_bytes"] > 1024 * 1024
    assert result["archive_bytes"] < 256 * 1024
    assert result["plan"]["max_archive_bytes"] == 256 * 1024


def test_output_limit_removes_partial_and_preserves_existing_backups(client_engine, tmp_path):
    root, _ = offline(client_engine)
    destination = tmp_path / "backups"
    destination.mkdir()
    previous = destination / "existing.zip"
    previous.write_bytes(b"older backup fixture")
    before = {n: logical_manifest(root / n) for n in DATABASES}
    with pytest.raises(ArchiveLimitExceeded):
        create_backup(root, destination, max_archive_bytes=200)
    assert list(destination.iterdir()) == [previous]
    assert previous.read_bytes() == b"older backup fixture"
    assert {n: logical_manifest(root / n) for n in DATABASES} == before
    with RuntimeLock(root):
        pass


def test_failed_restore_verification_never_publishes_archive(client_engine, tmp_path, monkeypatch):
    root, _ = offline(client_engine)
    destination, work = tmp_path / "backup", tmp_path / "work"

    def broken(*args):
        raise ValueError("Explicit failed verification")

    monkeypatch.setattr("app.offline_backup.verify_archive", broken)
    with pytest.raises(ValueError, match="failed verification"):
        create_backup(root, destination, work)
    assert not list(destination.iterdir()) and not list(work.iterdir())


def test_restored_content_must_match_source_hash(client_engine, tmp_path):
    root, _ = offline(client_engine)
    result = create_backup(root, tmp_path / "backup")
    with zipfile.ZipFile(result["archive"]) as z:
        metadata = json.loads(z.comment)
        contents = {n: z.read(n) for n in DATABASES}
    corrupted = tmp_path / "changed.zip"
    with zipfile.ZipFile(corrupted, "w") as z:
        z.comment = json.dumps(metadata, sort_keys=True).encode()
        for name, content in contents.items():
            z.writestr(name, content[:-1] + bytes([content[-1] ^ 1]))
    work = tmp_path / "verify"
    work.mkdir()
    with pytest.raises(ValueError, match="checksum"):
        verify_archive(corrupted, work, metadata)
    assert not list(work.iterdir())


def test_sqlite_integrity_failure_rejects_even_a_matching_source_hash(client_engine, tmp_path):
    root, _ = offline(client_engine)
    (root / DATABASES[0]).write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        create_backup(root, tmp_path / "backup")
    assert not (tmp_path / "backup").exists()


def test_budget_checks_highest_position_and_detects_shrinking_free_space(tmp_path, monkeypatch):
    handle = io.BytesIO()
    fake = type("Disk", (), {"free": RESERVE + 100})()
    monkeypatch.setattr("app.offline_backup.shutil.disk_usage", lambda _: fake)
    output = BudgetFile(handle, 10, tmp_path)
    output.write(b"1234567890")
    output.seek(0)
    output.write(b"ab")
    output.seek(0, 2)
    with pytest.raises(ArchiveLimitExceeded):
        output.write(b"x")
    output.seek(0)
    output.since_check = 1024 * 1024
    fake.free = RESERVE
    with pytest.raises(InsufficientSpace):
        output.write(b"x")


def test_shared_volume_reserves_restore_space_and_missing_source_is_not_created(
    client_engine, tmp_path, monkeypatch,
):
    root, _ = offline(client_engine)
    largest = max((root / n).stat().st_size for n in DATABASES)
    free = RESERVE + largest + 256 * 1024
    monkeypatch.setattr("app.offline_backup.shutil.disk_usage",
                        lambda _: type("Disk", (), {"free": free})())
    plan = plan_backup(root, tmp_path / "backup")
    assert plan["shared_volume"] and plan["max_archive_bytes"] == 256 * 1024
    with pytest.raises(ValueError, match="Both existing"):
        create_backup(tmp_path / "missing")
    assert not (tmp_path / "missing").exists()


@pytest.mark.parametrize("bad", ["relative", " "])
def test_paths_are_admin_absolute_directories(client_engine, bad):
    root, _ = offline(client_engine)
    with pytest.raises(ValueError, match="absolute"):
        plan_backup(root, bad)


def test_work_volume_still_requires_full_restore_capacity(client_engine, tmp_path, monkeypatch):
    root, _ = offline(client_engine)
    target, work = tmp_path / "out", tmp_path / "work"
    monkeypatch.setattr("app.offline_backup.volume_id", lambda p: str(p))
    monkeypatch.setattr("app.offline_backup.shutil.disk_usage", lambda path: type("Disk", (), {
        "free": RESERVE if Path(path) == tmp_path else RESERVE * 100,
    })())
    with pytest.raises(InsufficientSpace):
        plan_backup(root, target, work)
    assert not target.exists() and not work.exists()
