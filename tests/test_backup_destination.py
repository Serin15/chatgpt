"""Real fixture databases/files; disk availability and volume IDs are simulated."""

import tempfile
from pathlib import Path

import pytest

from app.maintenance import backup
from app.storage import RESERVE, existing_directory, logical_manifest, restore_backup
from tests.test_opportunities import client_engine as client_engine


def test_backup_and_restore_use_configured_destination_and_work_directory(
    client_engine, tmp_path, monkeypatch
):
    _, engine = client_engine
    destination, work = tmp_path / "Backup știri #1", tmp_path / "Working space"
    monkeypatch.setenv("PULSE_BACKUP_DIR", str(destination))
    monkeypatch.setenv("PULSE_BACKUP_WORK_DIR", str(work))
    original, used = tempfile.TemporaryDirectory, []

    def temporary(*args, **kwargs):
        used.append(Path(kwargs["dir"]))
        return original(*args, **kwargs)

    monkeypatch.setattr("app.maintenance.tempfile.TemporaryDirectory", temporary)
    saved = backup(engine.service)
    assert saved.parent == destination
    assert used == [work] and not list(work.iterdir())
    restored = restore_backup(saved, tmp_path / "restored")
    assert restored["research.sqlite3"] == logical_manifest(engine.store.path)


def test_external_backup_can_succeed_when_data_volume_is_too_small(
    client_engine, tmp_path, monkeypatch
):
    client, engine = client_engine
    target = tmp_path / "external volume"
    target.mkdir()
    monkeypatch.setenv("PULSE_BACKUP_DIR", str(target))
    source = engine.store.path.parent

    def disk(path):
        return type("Disk", (), {"free": 1 if Path(path) != target and Path(path).is_relative_to(source) else 50 * RESERVE,
                                  "total": 100 * RESERVE})()

    monkeypatch.setattr("app.storage.shutil.disk_usage", disk)
    monkeypatch.setattr("app.storage.volume_id", lambda p: str(p), raising=False)
    status = client.get("/api/storage").json()
    assert status["backup_ready"] is True
    assert client.post("/api/backup").status_code == 200
    assert list(target.glob("*.zip"))


def test_insufficient_work_volume_is_reported_even_with_room_for_zip(
    client_engine, tmp_path, monkeypatch
):
    client, _ = client_engine
    target, work = tmp_path / "destination", tmp_path / "small working volume"
    target.mkdir()
    work.mkdir()
    monkeypatch.setenv("PULSE_BACKUP_DIR", str(target))
    monkeypatch.setenv("PULSE_BACKUP_WORK_DIR", str(work))
    monkeypatch.setattr("app.storage.volume_id", lambda p: str(p), raising=False)
    monkeypatch.setattr("app.storage.shutil.disk_usage", lambda p: type("Disk", (), {
        "free": 1 if Path(p) == work else 50 * RESERVE, "total": 100 * RESERVE})())
    status = client.get("/api/storage").json()
    assert status["backup_ready"] is False
    assert status["backup_work_space_deficit_bytes"] > 0
    assert client.post("/api/backup").status_code == 507
    assert not list(target.glob("*.zip*"))


@pytest.mark.parametrize("value", ["relative-folder", " "])
def test_invalid_destination_does_not_block_dashboard_or_expose_path(
    client_engine, monkeypatch, value
):
    client, _ = client_engine
    monkeypatch.setenv("PULSE_BACKUP_DIR", value)
    status = client.get("/api/storage")
    assert status.status_code == 200
    assert status.json()["backup_configuration_error"]
    assert client.post("/api/backup").status_code == 503
    assert client.get("/api/opportunities").status_code == 200


def test_unavailable_volume_stops_at_root_instead_of_looping(tmp_path, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(Path, "exists", lambda _: False)
        with pytest.raises(ValueError, match="volume is unavailable"):
            existing_directory(tmp_path)
