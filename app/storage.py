"""Offline lossless history archival, capacity checks and verified backup restore.

Run `python -m app.storage --help`. No network or real-money execution.
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from app.archive_codec import configure, decode, encode
from app.config import Settings
from app.models import utcnow
from app.runtime_lock import RuntimeLock

RESERVE = 512 * 1024 * 1024
DATABASES = ("research.sqlite3", "news_paper/research.sqlite3")
COLD_COLUMNS = {
    "snapshots": ("address", ("market", "security", "analysis")),
    "opportunity_observations": ("candidate_id", ("payload",)),
}


class InsufficientSpace(ValueError):
    def __init__(self, needed, free):
        self.required_bytes, self.free_bytes = needed, free
        super().__init__(
            f"Insufficient disk space: need {needed} free bytes including reserve; have {free}."
        )


def file_bytes(path):
    try:
        return Path(path).stat().st_size
    except FileNotFoundError:
        return 0


def backup_estimate(data_dir):
    # Cheap, conservative bound: SQLite copy plus a worst-case ZIP, including
    # pages still in WAL. Do not scan SQLite on the status request's critical path.
    return 2 * sum(
        file_bytes(Path(data_dir) / name) + file_bytes(Path(data_dir) / (name + "-wal"))
        for name in DATABASES
    )


def existing_directory(path):
    path = Path(path)
    while not path.exists():
        if path.parent == path:
            raise ValueError("Backup volume is unavailable")
        path = path.parent
    if not path.is_dir():
        raise ValueError("Backup destination must be a directory")
    return path


def volume_id(path):
    return existing_directory(path).stat().st_dev


def backup_plan(data_dir):
    """Admin-configured paths only; never accept filesystem paths from HTTP input."""
    def configured(name, default):
        value = os.getenv(name)
        if value is None:
            return Path(default).resolve()
        path = Path(value.strip()).expanduser()
        if not value.strip() or not path.is_absolute():
            raise ValueError("Backup paths must be absolute directories")
        try:
            path = path.resolve()
        except RuntimeError:
            raise ValueError("Backup directory cannot be resolved") from None
        existing_directory(path)
        return path

    target = configured("PULSE_BACKUP_DIR", Path(data_dir) / "backups")
    work = configured("PULSE_BACKUP_WORK_DIR", target)
    sizes = [file_bytes(Path(data_dir) / n) + file_bytes(Path(data_dir) / (n + "-wal"))
             for n in DATABASES]
    archive, scratch = sum(sizes), max(sizes, default=0)
    shared = volume_id(target) == volume_id(work)
    target_required = archive + (scratch if shared else 0) + RESERVE
    work_required = target_required if shared else scratch + RESERVE
    target_free = shutil.disk_usage(existing_directory(target)).free
    work_free = target_free if shared else shutil.disk_usage(existing_directory(work)).free
    target_deficit, work_deficit = max(0, target_required - target_free), max(0, work_required - work_free)
    return {
        "backup_destination": str(target), "backup_work_directory": str(work),
        "backup_shared_volume": shared, "backup_configuration_error": None,
        "backup_disk_free_bytes": target_free, "backup_work_free_bytes": work_free,
        "backup_required_free_bytes": target_required,
        "backup_work_required_free_bytes": work_required,
        "backup_work_space_deficit_bytes": work_deficit,
        "backup_space_deficit_bytes": target_deficit + (0 if shared else work_deficit),
        "backup_ready": target_deficit == 0 and work_deficit == 0,
    }


def backup_status(data_dir):
    try:
        return backup_plan(data_dir)
    except (OSError, ValueError):
        return {"backup_ready": False, "backup_configuration_error":
                "Destinația sau spațiul temporar pentru backup nu sunt accesibile/configurate corect."}


def require_backup_space(plan):
    for path, needed in [(plan["backup_destination"], plan["backup_required_free_bytes"]),
                         (plan["backup_work_directory"], plan["backup_work_required_free_bytes"])]:
        free = shutil.disk_usage(existing_directory(path)).free
        if free < needed:
            raise InsufficientSpace(needed, free)


def read_connection(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    configure(db)
    db.execute("PRAGMA query_only=ON")
    return db


def require_space(folder, needed):
    free = shutil.disk_usage(folder).free
    if free < needed + RESERVE:
        raise InsufficientSpace(needed + RESERVE, free)


def disk_health(data_dir):
    try:
        free = shutil.disk_usage(data_dir).free
    except OSError:
        return {
            "state": "error",
            "at": utcnow(),
            "error": "Spațiul de stocare nu poate fi verificat.",
        }
    report = backup_status(data_dir)
    ready = report["backup_ready"]
    state = "error" if free < RESERVE else "partial" if free < RESERVE * 2 or not ready else "ok"
    return {
        "state": state,
        "at": utcnow(),
        "disk_free_bytes": free,
        **report,
        "error": "Spațiu liber redus; verifică panoul Stocare din Jurnal & rezultate."
        if free < 2 * RESERVE else "Spațiu insuficient pentru backupul complet; verifică panoul Stocare."
        if not ready else None,
    }


def tables(db):
    return {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not row[0].startswith(("sqlite_", "storage_archive_", "ui_catalog_"))
    }


def logical_manifest(path):
    """Hash every logical row, not compressed bytes; never return private payloads."""
    result = {}
    with closing(read_connection(path)) as db:
        db.execute("BEGIN")
        checks = [row[0] for row in db.execute("PRAGMA quick_check")]
        if checks != ["ok"]:
            raise ValueError("SQLite integrity check failed")
        for table in sorted(tables(db)):
            quoted = '"' + table.replace('"', '""') + '"'
            info = db.execute(f"PRAGMA table_info({quoted})").fetchall()
            keys = [row[1] for row in sorted(info, key=lambda r: r[5]) if row[5]]
            order = ",".join('"' + key.replace('"', '""') + '"' for key in keys) or "rowid"
            digest, count = hashlib.sha256(), 0
            for row in db.execute(f"SELECT * FROM {quoted} ORDER BY {order}"):
                if table in COLD_COLUMNS and any(
                    not isinstance(row[column], str) for column in COLD_COLUMNS[table][1]
                ):
                    raise ValueError("Unknown or damaged archive format in cold JSON column")
                # Binary values outside cold JSON are preserved with an explicit type.
                values = [
                    {"bytes_hex": value.hex()} if isinstance(value, bytes) else value
                    for value in row
                ]
                digest.update(json.dumps(values, ensure_ascii=False, allow_nan=False).encode())
                digest.update(b"\n")
                count += 1
            result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def capacity(data_dir):
    data_dir = Path(data_dir).resolve()
    disks, databases = shutil.disk_usage(data_dir), []
    for relative in DATABASES:
        path = data_dir / relative
        if not path.is_file():
            continue
        with closing(read_connection(path)) as db:
            pages = db.execute("PRAGMA page_count").fetchone()[0]
            page_size = db.execute("PRAGMA page_size").fetchone()[0]
            free_pages = db.execute("PRAGMA freelist_count").fetchone()[0]
            latest = None
            if db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='storage_archive_runs' AND type='table'"
            ).fetchone():
                row = db.execute(
                    "SELECT payload FROM storage_archive_runs ORDER BY id DESC LIMIT 1"
                ).fetchone()
                latest = json.loads(row[0]) if row else None
        databases.append(
            {
                "database": relative,
                "file_bytes": path.stat().st_size,
                "logical_page_bytes": pages * page_size,
                "reusable_bytes": free_pages * page_size,
                "wal_bytes": file_bytes(str(path) + "-wal"),
                "last_archive": latest,
            }
        )
    report = backup_status(data_dir)
    backup_dir = Path(report.get("backup_destination", data_dir / "backups"))
    backups = list(backup_dir.glob("*.zip")) if backup_dir.is_dir() else []
    return {
        "at": utcnow(),
        "state": "critical"
        if disks.free < RESERVE
        else "warning"
        if disks.free < 2 * RESERVE or not report["backup_ready"]
        else "ok",
        "disk_free_bytes": disks.free,
        "disk_total_bytes": disks.total,
        **report,
        "databases": databases,
        "backup_count": len(backups),
        "backup_bytes": sum(file_bytes(p) for p in backups),
        "automatic_archival": False,
        "history_deleted": False,
        "archive_is_independent_backup": False,
    }


def archive_database(path, cutoff, batch_size=200):
    """Bounded atomic batches. Latest row per subject stays plain for fast UI reads."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("Batch size must be between 1 and 1000")
    cutoff_at = datetime.fromisoformat(cutoff)
    if cutoff_at.tzinfo is None or cutoff_at >= datetime.now(UTC) - timedelta(days=1):
        raise ValueError("Archive cutoff must be timezone-aware and at least one day old")
    result = {"cutoff": cutoff, "tables": {}, "codec": "memescope-zlib-sha256-v1"}
    with closing(sqlite3.connect(path, timeout=10)) as db:
        configure(db)
        db.row_factory = sqlite3.Row
        available = tables(db)
        for table, (subject, columns) in COLD_COLUMNS.items():
            if table not in available:
                continue
            after, changed, raw_bytes, packed_bytes = 0, 0, 0, 0
            plain = " OR ".join(f"typeof({column})='text'" for column in columns)
            while True:
                try:
                    db.execute("BEGIN IMMEDIATE")
                    rows = db.execute(
                        f"SELECT * FROM {table} WHERE id>? AND julianday(at)<julianday(?) "
                        f"AND ({plain}) AND id!=(SELECT max(t.id) FROM {table} t "
                        f"WHERE t.{subject}={table}.{subject}) ORDER BY id LIMIT ?",
                        (after, cutoff, batch_size),
                    ).fetchall()
                    if not rows:
                        db.rollback()
                        break
                    for row in rows:
                        after = row["id"]
                        raw = [row[column] for column in columns]
                        original = [decode(value) for value in raw]
                        if not all(isinstance(value, str) for value in original):
                            raise ValueError("Unknown binary format in cold JSON column")
                        packed = [encode(value) for value in raw]
                        if packed == raw:
                            continue
                        # Decode existing archives on reruns; storing them again is
                        # deterministic. Do not touch timestamps, IDs or other fields.
                        db.execute(
                            f"UPDATE {table} SET "
                            + ",".join(f"{c}=?" for c in columns)
                            + " WHERE id=?",
                            (*packed, row["id"]),
                        )
                        restored = db.execute(
                            "SELECT " + ",".join(columns) + f" FROM {table} WHERE id=?",
                            (row["id"],),
                        ).fetchone()
                        if [decode(value) for value in restored] != original:
                            raise ValueError("Stored archive differs from original payload")
                        changed += 1
                        raw_bytes += sum(len(v.encode("utf-8")) for v in original)
                        packed_bytes += sum(
                            len(v) if isinstance(v, bytes) else len(v.encode("utf-8"))
                            for v in packed
                        )
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
            result["tables"][table] = {
                "rows_compressed": changed,
                "original_payload_bytes": raw_bytes,
                "stored_payload_bytes": packed_bytes,
            }
        db.execute(
            "CREATE TABLE IF NOT EXISTS storage_archive_runs(id INTEGER PRIMARY KEY,at TEXT NOT NULL,payload TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO storage_archive_runs(at,payload) VALUES(?,?)",
            (utcnow(), json.dumps(result)),
        )
        db.commit()
    return result


def compact_database(path):
    # SQLite's own VACUUM preserves the live pathname atomically. Never replace a
    # database under a running process, and never remove its WAL/SHM manually.
    with closing(sqlite3.connect(path, timeout=2, isolation_level=None)) as db:
        configure(db)
        needed = (
            db.execute("PRAGMA page_count").fetchone()[0]
            * db.execute("PRAGMA page_size").fetchone()[0]
        )
        require_space(Path(path).parent, needed * 2)
        # VACUUM may use the system temporary volume as well as the database
        # volume (not necessarily the same drive on Windows).
        require_space(Path(tempfile.gettempdir()), needed)
        db.execute("PRAGMA locking_mode=EXCLUSIVE")
        db.execute("BEGIN EXCLUSIVE")
        db.execute("ROLLBACK")
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("VACUUM")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError("Post-compaction SQLite integrity check failed")


def restore_backup(archive, destination):
    """Restore to a NEW directory only. Exact allowlist; no ZIP path extraction."""
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Restore destination must not exist; existing data is never overwritten")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) != 2 or sorted(i.filename for i in entries) != sorted(DATABASES):
            raise ValueError("Backup must contain exactly the two MemeScope databases")
        if any((i.external_attr >> 16) & 0o170000 == 0o120000 for i in entries):
            raise ValueError("Symbolic links are not accepted in backups")
        require_space(destination.parent, sum(i.file_size for i in entries))
        with tempfile.TemporaryDirectory(
            prefix=".memescope-restore-", dir=destination.parent
        ) as scratch:
            root = Path(scratch) / "restored"
            root.mkdir(mode=0o700)
            manifests = {}
            for info in entries:
                target = root / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, target.open("xb") as output:
                    target.chmod(0o600)
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                manifests[info.filename] = logical_manifest(target)
            if destination.exists() or destination.is_symlink():
                raise ValueError("Restore destination appeared during validation")
            root.rename(destination)
    return manifests


def maintain(data_dir, days=7, compact=False):
    from app.maintenance import backup

    if not 1 <= days <= 3650:
        raise ValueError("Retention must be between 1 and 3650 days")
    data_dir = Path(data_dir).resolve()
    if not all((data_dir / name).is_file() for name in DATABASES):
        raise ValueError("Both existing MemeScope databases are required")
    with RuntimeLock(data_dir):
        print("Verifying existing logical history...", file=sys.stderr, flush=True)
        before = {name: logical_manifest(data_dir / name) for name in DATABASES}
        service = SimpleNamespace(
            settings=SimpleNamespace(data_dir=data_dir),
            store=SimpleNamespace(path=data_dir / DATABASES[0]),
            news_paper=SimpleNamespace(path=data_dir / DATABASES[1]),
        )
        print("Creating consistent backup before archival...", file=sys.stderr, flush=True)
        saved = backup(service)
        # Read every restored row before rewriting any original payload.
        with tempfile.TemporaryDirectory(prefix=".verify-", dir=saved.parent) as scratch:
            restored = restore_backup(saved, Path(scratch) / "data")
            if restored != before:
                raise ValueError("Backup restoration differs from current data; archival cancelled")
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        runs = {}
        for name in DATABASES:
            print(f"Archiving {name}...", file=sys.stderr, flush=True)
            runs[name] = archive_database(data_dir / name, cutoff)
        after = {name: logical_manifest(data_dir / name) for name in DATABASES}
        if before != after:
            raise ValueError("Logical history verification failed; restore the verified backup")
        if compact:
            for name in DATABASES:
                print(f"Compacting {name}...", file=sys.stderr, flush=True)
                compact_database(data_dir / name)
            if {name: logical_manifest(data_dir / name) for name in DATABASES} != before:
                raise ValueError("Compaction history verification failed")
        return {
            "backup": saved.name,
            "backup_restore_verified": True,
            "logical_history_identical": True,
            "runs": runs,
            "manifests": after,
            "capacity": capacity(data_dir),
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["status", "verify", "archive", "restore"])
    parser.add_argument("--data-dir", type=Path, default=Settings.from_environment().data_dir)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--compact", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "status":
            result = capacity(args.data_dir)
        elif args.command == "verify":
            result = {name: logical_manifest(args.data_dir / name) for name in DATABASES}
        elif args.command == "archive":
            result = maintain(args.data_dir, args.days, args.compact)
        else:
            if not args.backup or not args.destination:
                parser.error("restore requires --backup and a NEW --destination")
            result = restore_backup(args.backup, args.destination)
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Maintenance stopped: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
