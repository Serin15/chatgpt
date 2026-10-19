"""Export one UTC discovery cohort from existing SQLite data, read-only and offline."""

import argparse
import json
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.config import Settings
from app.daily_research import daily_report


class ReadOnlyStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        if not self.path.is_file():
            raise ValueError("Existing research.sqlite3 is required; no database will be created.")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=30)
        try:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA query_only=ON")
            yield db
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Settings.from_environment().data_dir)
    parser.add_argument("--day", type=date.fromisoformat)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".json" or args.output.is_symlink():
        parser.error("Output must be a .json file, not a symbolic link.")
    try:
        result = daily_report(
            SimpleNamespace(store=ReadOnlyStore(args.data_dir / "research.sqlite3")), args.day
        )
    except (sqlite3.Error, ValueError) as exc:
        parser.exit(
            1, f"{type(exc).__name__}: evaluation unavailable; database was not modified.\n"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=args.output.parent, suffix=".json.tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        # Replace a directory entry, never write through an existing hard link.
        temporary.replace(args.output)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "day_utc": result["day_utc"],
                "totals": result["totals"],
                "evaluation_protocol": result["evaluation_protocol"],
                "profitability_demonstrated": False,
            }
        )
    )


if __name__ == "__main__":
    main()
