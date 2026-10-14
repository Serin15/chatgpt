"""Portable, consistent paper-data backups and full experiment exports."""

import json
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path

from app import __version__
from app.models import utcnow


def backup(service):
    folder = service.settings.data_dir / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    name = "pulse-" + utcnow().replace(":", "").replace("+", "-") + ".zip"
    target = folder / name
    with tempfile.TemporaryDirectory() as scratch:
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for relative, store in [
                ("research.sqlite3", service.store),
                ("news_paper/research.sqlite3", service.news_paper),
            ]:
                copied = Path(scratch) / Path(relative).name
                with (
                    closing(
                        sqlite3.connect(f"file:{store.path.resolve()}?mode=ro", uri=True)
                    ) as source,
                    closing(sqlite3.connect(copied)) as destination,
                ):
                    source.backup(destination)
                archive.write(copied, relative)
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
        "live_execution": False,
    }
