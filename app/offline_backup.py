"""Verified offline ZIP backup with a bounded output size and no source clone.

Close MemeScope first. Example: python -m app.offline_backup --work-dir /mounted/work
The online backup and its conservative capacity checks are unchanged.
"""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
from contextlib import ExitStack, closing
from pathlib import Path

from app import __version__
from app.config import Settings
from app.models import utcnow
from app.runtime_lock import RuntimeLock
from app.storage import (
    DATABASES,
    RESERVE,
    InsufficientSpace,
    existing_directory,
    file_bytes,
    volume_id,
)

CHUNK = 1024 * 1024
MIN_OUTPUT = 64 * 1024


class ArchiveLimitExceeded(ValueError):
    def __init__(self, limit):
        self.limit_bytes = limit
        super().__init__("Compressed backup exceeded its output budget; no archive was published.")


def directory(value, default):
    if value is None:
        return Path(default).resolve()
    path = Path(value).expanduser()
    if not str(value).strip() or not path.is_absolute():
        raise ValueError("Backup paths must be absolute directories")
    path = path.resolve()
    existing_directory(path)
    return path


def plan_backup(data_dir, destination=None, work_dir=None, max_archive_bytes=None):
    root = Path(data_dir).resolve()
    if not all((root / name).is_file() and not (root / name).is_symlink() for name in DATABASES):
        raise ValueError("Both existing MemeScope databases are required; symbolic links are refused")
    target = directory(destination if destination is not None else os.getenv("PULSE_BACKUP_DIR"),
                       root / "backups")
    work = directory(work_dir if work_dir is not None else os.getenv("PULSE_BACKUP_WORK_DIR"),
                     target)
    if target == root or target == root / "news_paper" or work == root or work == root / "news_paper":
        raise ValueError("Use dedicated backup and working directories")
    sizes = [file_bytes(root / name) + file_bytes(root / (name + "-wal")) for name in DATABASES]
    restore_bytes = max(sizes)
    shared = volume_id(target) == volume_id(work)
    target_free = shutil.disk_usage(existing_directory(target)).free
    work_free = target_free if shared else shutil.disk_usage(existing_directory(work)).free
    work_required = restore_bytes + RESERVE
    if work_free < work_required:
        raise InsufficientSpace(work_required, work_free)
    available = target_free - RESERVE - (restore_bytes if shared else 0)
    if available < MIN_OUTPUT:
        raise InsufficientSpace(RESERVE + MIN_OUTPUT + (restore_bytes if shared else 0), target_free)
    if max_archive_bytes is not None:
        if type(max_archive_bytes) is not int or max_archive_bytes < 1:
            raise ValueError("Archive budget must be a positive integer number of bytes")
        available = min(available, max_archive_bytes)
    return {
        "destination": str(target), "work_dir": str(work),
        "max_archive_bytes": available, "restore_required_bytes": work_required,
        "shared_volume": shared, "reserve_bytes": RESERVE,
        "mode": "offline_bounded_compression", "compression_fit_is_unverified": True,
    }


class BudgetFile:
    """ZIP can rewrite headers. Bound the highest written byte, not total writes."""

    def __init__(self, handle, limit, volume, restore_reservation=0):
        self.handle, self.limit, self.volume = handle, limit, volume
        self.restore_reservation = restore_reservation
        self.since_check = CHUNK

    def __getattr__(self, name):
        return getattr(self.handle, name)

    def write(self, data):
        if self.handle.tell() + len(data) > self.limit:
            raise ArchiveLimitExceeded(self.limit)
        self.since_check += len(data)
        if self.since_check >= CHUNK:
            free = shutil.disk_usage(self.volume).free
            required = RESERVE + self.restore_reservation + len(data)
            if free < required:
                raise InsufficientSpace(required, free)
            self.since_check = 0
        return self.handle.write(data)


def verify_archive(archive, work_dir, expected):
    """Restore every byte to real SQLite files, hash them, and check their integrity.

    One database is restored at a time. Only the verification copies are removed.
    Expected hashes come from the locked source stream, not from the ZIP itself.
    """
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if len(entries) != len(DATABASES) or sorted(i.filename for i in entries) != sorted(DATABASES):
            raise ValueError("Backup must contain exactly the two MemeScope databases")
        if json.loads(package.comment) != expected:
            raise ValueError("Backup metadata does not match the locked source snapshot")
        with tempfile.TemporaryDirectory(prefix=".offline-verify-", dir=work_dir) as scratch:
            for info in entries:
                if info.file_size != expected["files"][info.filename]["bytes"]:
                    raise ValueError("Restored database size does not match its source")
                free = shutil.disk_usage(work_dir).free
                if free < info.file_size + RESERVE:
                    raise InsufficientSpace(info.file_size + RESERVE, free)
                copied = Path(scratch) / "database.sqlite3"
                digest = hashlib.sha256()
                with package.open(info) as source, copied.open("xb") as output:
                    copied.chmod(0o600)
                    while block := source.read(CHUNK):
                        output.write(block)
                        digest.update(block)
                if digest.hexdigest() != expected["files"][info.filename]["sha256"]:
                    raise ValueError("Restored database checksum does not match its source")
                with closing(sqlite3.connect(copied.resolve().as_uri() + "?mode=ro&immutable=1",
                                             uri=True)) as db:
                    if db.execute("PRAGMA quick_check(1)").fetchall() != [("ok",)]:
                        raise ValueError("Restored SQLite integrity check failed")
                copied.unlink()


def create_backup(data_dir, destination=None, work_dir=None, max_archive_bytes=None, progress=None):
    root = Path(data_dir).resolve()
    # Validate existence before RuntimeLock, which can create its directory.
    plan = plan_backup(root, destination, work_dir, max_archive_bytes)
    target_dir, work = Path(plan["destination"]), Path(plan["work_dir"])
    with RuntimeLock(root), ExitStack() as stack:
        paths = []
        for name in DATABASES:
            path = root / name
            db = stack.enter_context(closing(sqlite3.connect(
                path.resolve().as_uri() + "?mode=rw", uri=True, timeout=2, isolation_level=None,
            )))
            # An offline checkpoint merges ALL committed WAL pages. Holding an
            # IMMEDIATE transaction then prevents another SQLite writer during ZIP.
            checkpoint = db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint[0]:
                raise ValueError("Database is in use; close other programs before backup")
            db.execute("BEGIN IMMEDIATE")
            if file_bytes(str(path) + "-wal"):
                raise ValueError("Database changed during checkpoint; close other programs and retry")
            paths.append((name, path, path.stat()))
        # Recalculate after checkpoint/locks; never rely on a compression sample.
        plan = plan_backup(root, destination, work_dir, max_archive_bytes)
        target_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        work.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = target_dir / ("pulse-offline-" + uuid.uuid4().hex + ".zip")
        partial = target.with_suffix(".zip.partial")
        metadata = {"format": "memescope-offline-backup-v1", "version": __version__,
                    "at": utcnow(), "files": {}, "live_execution": False}
        try:
            with partial.open("xb") as output:
                partial.chmod(0o600)
                budget = BudgetFile(output, plan["max_archive_bytes"], target_dir,
                                    max(s.st_size for _, _, s in paths) if plan["shared_volume"] else 0)
                with zipfile.ZipFile(budget, "w", compression=zipfile.ZIP_DEFLATED,
                                     compresslevel=6) as package:
                    for name, path, original in paths:
                        if progress:
                            progress("compressing", name)
                        digest, count = hashlib.sha256(), 0
                        with path.open("rb") as source, package.open(name, "w", force_zip64=True) as entry:
                            while block := source.read(CHUNK):
                                entry.write(block)
                                digest.update(block)
                                count += len(block)
                        after = path.stat()
                        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                            original.st_dev, original.st_ino, original.st_size, original.st_mtime_ns,
                        ) or count != original.st_size:
                            raise ValueError("Source database changed during backup")
                        metadata["files"][name] = {"bytes": count, "sha256": digest.hexdigest()}
                    package.comment = json.dumps(metadata, sort_keys=True).encode()
                output.flush()
                os.fsync(output.fileno())
            if progress:
                progress("restoring_and_verifying", "both databases")
            verify_archive(partial, work, metadata)
            digest = hashlib.sha256()
            with partial.open("rb") as source:
                while block := source.read(CHUNK):
                    digest.update(block)
            size = partial.stat().st_size
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        return {
            "archive": str(target), "archive_bytes": size, "sha256": digest.hexdigest(),
            "restoration_verified": True, "source_bytes": sum(v["bytes"] for v in metadata["files"].values()),
            "files": metadata["files"], "plan": plan, "live_execution": False,
            "backup_volume_differs_from_data": volume_id(target_dir) != volume_id(root),
            "independent_offsite_backup_verified": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Settings.from_environment().data_dir)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--max-archive-mib", type=int)
    parser.add_argument("--plan", action="store_true", help="Only report capacity; do not stop or copy anything")
    args = parser.parse_args()
    budget = args.max_archive_mib * 1024 * 1024 if args.max_archive_mib is not None else None
    try:
        if args.plan:
            result = plan_backup(args.data_dir, args.destination, args.work_dir, budget)
        else:
            result = create_backup(args.data_dir, args.destination, args.work_dir, budget,
                                   lambda phase, name: print(f"{phase}: {name}", file=sys.stderr, flush=True))
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as exc:
        # Console diagnostics never echo HTTP headers, credentials or SQLite rows.
        parser.exit(1, f"Offline backup stopped: {type(exc).__name__}: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
