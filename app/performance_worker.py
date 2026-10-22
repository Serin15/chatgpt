"""Finite, read-only report subprocess. Never creates services, keys or trades."""

import argparse
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from app.archive_codec import configure
from app.opportunity_rules import EngineConfig
from app.opportunity_sampling import Sampling
from app.performance_reporting import report


class ReadStore:
    def __init__(self, path):
        self.path = Path(path).resolve()

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=5)
        configure(db)
        try:
            yield db
        finally:
            db.close()


class ReadEngine:
    def __init__(self, path, news_path, max_snapshot_age):
        self.store = ReadStore(path)
        self.service = SimpleNamespace(
            settings=SimpleNamespace(max_snapshot_age=max_snapshot_age),
            news_paper=ReadStore(news_path),
        )
        # Sampling.__init__ migrates/enrolls data; a report must never invoke it.
        self.sampling = Sampling.__new__(Sampling)
        self.sampling.engine, self.sampling.store = self, self.store

    def config(self):
        with self.store.connect() as db:
            row = db.execute("SELECT payload FROM opportunity_config WHERE id=1").fetchone()
        return EngineConfig.model_validate_json(row[0]).validated()


def main():
    parser = argparse.ArgumentParser(description="Read a complete MemeScope performance report")
    parser.add_argument("--database", required=True)
    parser.add_argument("--news-database", required=True)
    parser.add_argument("--max-snapshot-age", type=int, default=120)
    args = parser.parse_args()
    try:
        data = report(ReadEngine(args.database, args.news_database, args.max_snapshot_age))
        sys.stdout.buffer.write(
            json.dumps(data, ensure_ascii=False, allow_nan=False).encode("utf-8")
        )
        return 0
    except Exception as error:
        # Exception types are enough for diagnostics; do not serialize paths,
        # environment variables, provider configuration or arbitrary DB content.
        sys.stderr.write(type(error).__name__ + "\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
