import json
import sqlite3
from contextlib import contextmanager
from decimal import Decimal

from app.models import utcnow


class Store:
    def __init__(self, settings):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = settings.data_dir / "research.sqlite3"
        self.initial_balance = settings.initial_balance
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS tokens (
                    address TEXT PRIMARY KEY, source TEXT NOT NULL, added_at TEXT NOT NULL,
                    watch INTEGER NOT NULL DEFAULT 0, error TEXT);
                CREATE TABLE IF NOT EXISTS snapshots (
                    id INTEGER PRIMARY KEY, address TEXT NOT NULL, at TEXT NOT NULL,
                    market TEXT NOT NULL, security TEXT NOT NULL, analysis TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS snapshots_token ON snapshots(address, id DESC);
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY, address TEXT NOT NULL, at TEXT NOT NULL,
                    snapshot_id INTEGER NOT NULL, evidence TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS account (
                    id INTEGER PRIMARY KEY CHECK(id=1), balance TEXT NOT NULL,
                    initial_balance TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY, address TEXT NOT NULL, quantity TEXT NOT NULL,
                    entry_cost TEXT NOT NULL, entry_at TEXT NOT NULL, entry_snapshot_id INTEGER,
                    signal_id INTEGER, closed_at TEXT, exit_proceeds TEXT, pnl TEXT);
                CREATE UNIQUE INDEX IF NOT EXISTS one_open_position
                    ON positions(address) WHERE closed_at IS NULL;
                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY, address TEXT NOT NULL, side TEXT NOT NULL,
                    at TEXT NOT NULL, status TEXT NOT NULL, details TEXT NOT NULL);
            """)
            columns = {r[1] for r in db.execute("PRAGMA table_info(account)")}
            if "initial_balance" not in columns:
                db.execute("ALTER TABLE account ADD COLUMN initial_balance TEXT")
                db.execute("UPDATE account SET initial_balance=?", (str(self.initial_balance),))
            db.execute(
                "INSERT OR IGNORE INTO account VALUES (1,?,?)",
                (str(self.initial_balance), str(self.initial_balance)),
            )
            self.initial_balance = Decimal(
                db.execute("SELECT initial_balance FROM account WHERE id=1").fetchone()[0]
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def add_token(self, address, source, watch=False):
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO tokens(address,source,added_at,watch) VALUES(?,?,?,?)",
                (address, source, utcnow(), int(watch)),
            )
            if watch:
                db.execute("UPDATE tokens SET watch=1 WHERE address=?", (address,))

    def tokens(self):
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute("SELECT * FROM tokens ORDER BY watch DESC, added_at DESC")
            ]

    def set_error(self, address, error):
        with self.connect() as db:
            db.execute("UPDATE tokens SET error=? WHERE address=?", (error, address))

    def unwatch(self, address):
        with self.connect() as db:
            db.execute("UPDATE tokens SET watch=0 WHERE address=?", (address,))

    def save_snapshot(self, market, security, analysis):
        with self.connect() as db:
            row = db.execute(
                "INSERT INTO snapshots(address,at,market,security,analysis) VALUES(?,?,?,?,?)",
                (
                    market.address,
                    market.observed_at,
                    market.model_dump_json(),
                    json.dumps(security),
                    json.dumps(analysis),
                ),
            )
            db.execute("UPDATE tokens SET error=NULL WHERE address=?", (market.address,))
            return row.lastrowid

    @staticmethod
    def unpack(row):
        if row is None:
            return None
        result = dict(row)
        for key in ("market", "security", "analysis"):
            result[key] = json.loads(result[key])
        return result

    def latest(self, address):
        with self.connect() as db:
            return self.unpack(
                db.execute(
                    "SELECT * FROM snapshots WHERE address=? ORDER BY id DESC LIMIT 1", (address,)
                ).fetchone()
            )

    def history(self, address):
        with self.connect() as db:
            return [
                self.unpack(r)
                for r in db.execute(
                    "SELECT * FROM snapshots WHERE address=? ORDER BY id DESC LIMIT 200", (address,)
                )
            ]

    def signal(self, snapshot, context=None):
        with self.connect() as db:
            row = db.execute(
                "INSERT INTO signals(address,at,snapshot_id,evidence) VALUES(?,?,?,?)",
                (
                    snapshot["address"],
                    utcnow(),
                    snapshot["id"],
                    json.dumps(snapshot["analysis"] | (context or {})),
                ),
            )
            return dict(db.execute("SELECT * FROM signals WHERE id=?", (row.lastrowid,)).fetchone())

    def failed_order(self, address, side, reason):
        with self.connect() as db:
            db.execute(
                "INSERT INTO orders(address,side,at,status,details) VALUES(?,?,?,?,?)",
                (address, side, utcnow(), "failed", json.dumps({"reason": reason})),
            )

    def portfolio(self):
        with self.connect() as db:
            return {
                "mode": "paper",
                "initial_balance": str(self.initial_balance),
                "cash": db.execute("SELECT balance FROM account WHERE id=1").fetchone()[0],
                "positions": [
                    dict(r) for r in db.execute("SELECT * FROM positions ORDER BY id DESC")
                ],
                "orders": [
                    dict(r) | {"details": json.loads(r["details"])}
                    for r in db.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 100")
                ],
            }
