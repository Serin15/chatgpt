"""Disk/IO faults and concurrent requests on real API/SQLite; no external services."""

import errno
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from app.storage import RESERVE
from tests.test_opportunities import client_engine as client_engine


def test_insufficient_backup_space_is_explained_instead_of_http_500(client_engine, monkeypatch):
    client, engine = client_engine
    fake = type("Disk", (), {"free": 1, "total": 100})()
    monkeypatch.setattr("app.storage.shutil.disk_usage", lambda _: fake)
    result = client.post("/api/backup")
    assert result.status_code == 507
    assert "spațiu" in result.json()["detail"].lower()
    assert result.json()["free_bytes"] == 1
    assert not list((engine.store.path.parent / "backups").glob("*.zip*"))
    assert client.get("/api/opportunities").status_code == 200


def test_storage_warns_when_database_backup_will_not_fit(client_engine, monkeypatch):
    client, engine = client_engine
    real_stat = Path.stat

    def large_database(path, *args, **kwargs):
        value = real_stat(path, *args, **kwargs)
        if path == engine.store.path:
            values = list(value)
            values[6] = 2 * RESERVE  # Simulated size; do not allocate a huge fixture.
            return os.stat_result(values)
        return value

    monkeypatch.setattr(Path, "stat", large_database)
    fake = type("Disk", (), {"free": 3 * RESERVE, "total": 10 * RESERVE})()
    monkeypatch.setattr("app.storage.shutil.disk_usage", lambda _: fake)
    status = client.get("/api/status").json()["storage"]
    capacity = client.get("/api/storage").json()
    assert status["state"] == "partial"
    assert status["backup_ready"] is False and capacity["backup_ready"] is False
    assert capacity["backup_required_free_bytes"] > fake.free
    assert capacity["state"] == "warning"
    assert client.get("/api/opportunities").status_code == 200


@pytest.mark.parametrize("full", [True, False])
def test_backup_io_errors_are_sanitized_and_existing_archives_preserved(
    client_engine, monkeypatch, full
):
    client, engine = client_engine
    folder = engine.store.path.parent / "backups"
    folder.mkdir(exist_ok=True)
    previous = folder / "existing.zip"
    previous.write_bytes(b"existing fixture archive")

    def fail(_):
        raise OSError(errno.ENOSPC if full else errno.EACCES, "/private/fixture/path")

    monkeypatch.setattr("app.main.backup", fail)
    response = client.post("/api/backup")
    assert response.status_code == (507 if full else 503)
    assert "/private/fixture/path" not in response.text
    assert previous.read_bytes() == b"existing fixture archive"


def test_two_simultaneous_backup_requests_do_not_duplicate_disk_work(client_engine, monkeypatch):
    client, engine = client_engine
    entered, release = Event(), Event()
    calls = []
    archive = engine.store.path.parent / "fixture.zip"
    archive.write_bytes(b"explicit fixture result")

    def slow(_):
        calls.append(True)
        entered.set()
        release.wait(2)
        return archive

    monkeypatch.setattr("app.main.backup", slow)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(client.post, "/api/backup")
        assert entered.wait(3)
        try:
            second = client.post("/api/backup")
            assert second.status_code == 409
            assert calls == [True]
            assert client.get("/api/opportunities").status_code == 200
        finally:
            release.set()
        assert first.result(3).status_code == 200
