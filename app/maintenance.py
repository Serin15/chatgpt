"""Portable, consistent paper-data backups and full experiment exports."""

import json
import os
import sqlite3
import tempfile
import uuid
import zipfile
from contextlib import closing
from pathlib import Path

from app import __version__
from app.models import utcnow
from app.storage import require_space


def backup(service):
    folder = service.settings.data_dir / "backups"
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    name = (
        "pulse-" + utcnow().replace(":", "").replace("+", "-") + "-" + uuid.uuid4().hex[:8] + ".zip"
    )
    target = folder / name
    stores = [
        ("research.sqlite3", service.store),
        ("news_paper/research.sqlite3", service.news_paper),
    ]
    require_space(folder, sum(s.path.stat().st_size for _, s in stores) * 2)
    partial = target.with_suffix(".zip.partial")
    try:
        # Scratch and final ZIP use the same filesystem checked above. Failure
        # never publishes an incomplete ZIP or removes an older backup.
        with tempfile.TemporaryDirectory(prefix=".backup-", dir=folder) as scratch:
            with zipfile.ZipFile(partial, "x", compression=zipfile.ZIP_DEFLATED) as archive:
                partial.chmod(0o600)
                for relative, store in stores:
                    copied = Path(scratch) / relative
                    copied.parent.mkdir(parents=True, exist_ok=True)
                    with (
                        closing(
                            sqlite3.connect(store.path.resolve().as_uri() + "?mode=ro", uri=True)
                        ) as source,
                        closing(sqlite3.connect(copied)) as destination,
                    ):
                        source.backup(destination)
                        if destination.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                            raise ValueError("Backup SQLite integrity check failed")
                    archive.write(copied, relative)
            with zipfile.ZipFile(partial) as archive:
                if archive.testzip() is not None:
                    raise ValueError("Backup ZIP checksum failed")
            with partial.open("r+b") as handle:
                os.fsync(handle.fileno())
            partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def export(service, account):
    store = service.paper_store(account)
    with store.connect() as db:
        orders = [
            dict(r) | {"details": json.loads(r["details"])}
            for r in db.execute("SELECT * FROM orders ORDER BY id")
        ]
        signals = [
            dict(r) | {"evidence": json.loads(r["evidence"])}
            for r in db.execute("SELECT * FROM signals ORDER BY id")
        ]
        referenced = {s["snapshot_id"] for s in signals}
        referenced.update(
            o["details"]["snapshot_id"]
            for o in orders
            if o["details"].get("snapshot_id") is not None
        )
        snapshots = [
            store.unpack(r)
            for r in db.execute("SELECT * FROM snapshots ORDER BY id")
            if r["id"] in referenced
        ]
        observations = [
            dict(r) | {"context": json.loads(r["context"])}
            for r in db.execute("SELECT * FROM equity_observations ORDER BY id")
        ]
    return {
        "exported_at": utcnow(),
        "version": __version__,
        "account": account,
        "portfolio": service.portfolio(account),
        "orders": orders,
        "signals": signals,
        "snapshots": snapshots,
        "equity_observations": observations,
        "performance": service.performance.report(account),
        "research_cases": {
            address: service.research.case(address)
            for address in sorted({s["address"] for s in signals})
        },
        "live_execution": False,
    }
