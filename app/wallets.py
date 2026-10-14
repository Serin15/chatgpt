"""Bounded, read-only wallet observations. Transfers are never invented as profitable swaps."""

import asyncio
import json
import re
from decimal import Decimal

from pydantic import Field

from app.ai_research import StrictModel
from app.errors import ProviderError
from app.models import utcnow
from app.onchain import chain_address

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
JUPITER_PROGRAM = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"


class WalletInput(StrictModel):
    chain: str
    address: str
    label: str = Field(default="", max_length=80)


def solana_activity(transaction, address):
    if not isinstance(transaction, dict) or not isinstance(transaction.get("meta"), dict):
        raise ValueError("Transaction is unavailable/unparsed")
    meta = transaction["meta"]
    deltas = {}
    for key, direction in [("preTokenBalances", -1), ("postTokenBalances", 1)]:
        for row in meta.get(key) or []:
            if row.get("owner") != address:
                continue
            value = row["uiTokenAmount"]
            amount = Decimal(value["amount"]) / Decimal(10) ** int(value["decimals"])
            mint = row["mint"]
            deltas[mint] = deltas.get(mint, Decimal(0)) + direction * amount
    deltas = {k: str(v) for k, v in deltas.items() if v}
    message = transaction.get("transaction", {}).get("message", {})
    programs = {i.get("programId") for i in message.get("instructions", []) if isinstance(i, dict)}
    for group in meta.get("innerInstructions") or []:
        programs |= {
            i.get("programId") for i in group.get("instructions", []) if isinstance(i, dict)
        }
    signed = [Decimal(v) for v in deltas.values()]
    candidate = (
        JUPITER_PROGRAM in programs and any(v < 0 for v in signed) and any(v > 0 for v in signed)
    )
    return {
        "kind": "failed_transaction"
        if meta.get("err")
        else "swap_candidate"
        if candidate
        else "token_balance_change"
        if deltas
        else "other_activity",
        "token_deltas": deltas,
        "fee_lamports": meta.get("fee"),
        "block_time": transaction.get("blockTime"),
        "slot": transaction.get("slot"),
        "swap_verified": False,
        "pnl_usd": None,
        "note": "Schimbările de sold pot include transferuri, LP și taxe. Candidatul de swap nu este o achiziție recomandată; cost basis și PnL necesită istoric complet și prețuri istorice.",
    }


class Wallets:
    def __init__(self, store, onchain):
        self.store, self.onchain = store, onchain
        self.lock = asyncio.Lock()
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tracked_wallets(id INTEGER PRIMARY KEY,chain TEXT NOT NULL,address TEXT NOT NULL,label TEXT NOT NULL,at TEXT NOT NULL,status TEXT NOT NULL,UNIQUE(chain,address));
                CREATE TABLE IF NOT EXISTS wallet_activity(wallet_id INTEGER NOT NULL,event_id TEXT NOT NULL,at TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(wallet_id,event_id));
            """)

    def add(self, body):
        address = chain_address(body.chain, body.address)
        with self.store.connect() as db:
            if (
                db.execute("SELECT count(*) FROM tracked_wallets").fetchone()[0] >= 20
                and not db.execute(
                    "SELECT 1 FROM tracked_wallets WHERE chain=? AND address=?",
                    (body.chain, address),
                ).fetchone()
            ):
                raise ValueError("Maximum 20 de walleturi urmărite.")
            db.execute(
                "INSERT INTO tracked_wallets(chain,address,label,at,status) VALUES(?,?,?,?,?) ON CONFLICT(chain,address) DO UPDATE SET label=excluded.label",
                (body.chain, address, body.label, utcnow(), json.dumps({"state": "unverified"})),
            )
        return self.listing()

    def save_event(self, wallet_id, event_id, payload):
        with self.store.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO wallet_activity VALUES(?,?,?,?)",
                (wallet_id, event_id, utcnow(), json.dumps(payload)),
            )

    async def refresh(self, wallet_id, before=None, from_block=None):
        if self.lock.locked():
            raise ProviderError("Un wallet este deja în curs de actualizare.")
        with self.store.connect() as db:
            wallet = db.execute("SELECT * FROM tracked_wallets WHERE id=?", (wallet_id,)).fetchone()
        if not wallet:
            raise ValueError("Wallet necunoscut.")
        async with self.lock:
            try:
                if wallet["chain"] == "solana":
                    options = {"limit": 10, "commitment": "confirmed"}
                    if before:
                        if not isinstance(before, str) or not 60 <= len(before) <= 100:
                            raise ValueError("Cursor de semnătură invalid.")
                        options["before"] = before
                    signatures = await self.onchain.rpc(
                        "solana", "getSignaturesForAddress", [wallet["address"], options]
                    )
                    if not isinstance(signatures, list):
                        raise ProviderError("Lista de semnături este invalidă.")
                    missing = rejected = 0
                    valid_signatures = []
                    for row in signatures[:10]:
                        if (
                            not isinstance(row, dict)
                            or not isinstance(row.get("signature"), str)
                            or not 60 <= len(row["signature"]) <= 100
                        ):
                            rejected += 1
                            continue
                        signature = row["signature"]
                        valid_signatures.append(signature)
                        try:
                            transaction = await self.onchain.rpc(
                                "solana",
                                "getTransaction",
                                [
                                    signature,
                                    {
                                        "encoding": "jsonParsed",
                                        "commitment": "confirmed",
                                        "maxSupportedTransactionVersion": 0,
                                    },
                                ],
                            )
                            activity = solana_activity(transaction, wallet["address"])
                        except (
                            ValueError,
                            TypeError,
                            KeyError,
                            AttributeError,
                            ArithmeticError,
                            ProviderError,
                        ):
                            activity = {
                                "kind": "unavailable_transaction",
                                "pnl_usd": None,
                                "signature": signature,
                            }
                            missing += 1
                        self.save_event(wallet_id, signature, activity)
                    status = {
                        "state": "ok" if not missing and not rejected else "partial",
                        "at": utcnow(),
                        "observed": len(signatures[:10]),
                        "unavailable": missing,
                        "rejected": rejected,
                        "next_cursor": valid_signatures[-1]
                        if len(signatures) >= 10 and valid_signatures
                        else None,
                        "full_history": False,
                    }
                else:
                    latest = int(await self.onchain.rpc("base", "eth_blockNumber", []), 16)
                    start = max(0, latest - 999) if from_block is None else int(from_block)
                    if not 0 <= start <= latest:
                        raise ValueError("Block de început invalid.")
                    end = min(latest, start + 999)
                    owner = "0x" + wallet["address"][2:].rjust(64, "0")
                    unique = {}
                    rejected = 0
                    for topics in [[TRANSFER, owner], [TRANSFER, None, owner]]:
                        logs = await self.onchain.rpc(
                            "base",
                            "eth_getLogs",
                            [{"fromBlock": hex(start), "toBlock": hex(end), "topics": topics}],
                        )
                        if not isinstance(logs, list):
                            raise ProviderError("Lista de logs Base este invalidă.")
                        if len(logs) > 2000:
                            raise ProviderError(
                                "Prea multe logs; restrânge intervalul cu un RPC/indexer configurat."
                            )
                        for log in logs:
                            try:
                                if log.get("removed"):
                                    continue
                                event_topics = log["topics"]
                                if (
                                    len(event_topics) != 3
                                    or event_topics[0] != TRANSFER
                                    or owner not in event_topics[1:]
                                    or any(
                                        not re.fullmatch(r"0x[0-9a-fA-F]{64}", t)
                                        for t in event_topics
                                    )
                                    or not start <= int(log["blockNumber"], 16) <= end
                                    or int(log["data"], 16) < 0
                                    or int(log["logIndex"], 16) < 0
                                    or not re.fullmatch(
                                        r"0x[0-9a-fA-F]{64}", log["transactionHash"]
                                    )
                                ):
                                    raise ValueError("Invalid/unrelated transfer log")
                                chain_address("base", log["address"])
                                event_id = log["transactionHash"] + ":" + log["logIndex"]
                            except (TypeError, ValueError, KeyError, AttributeError):
                                rejected += 1
                                continue
                            unique[event_id] = log
                    for event_id, log in unique.items():
                        self.save_event(
                            wallet_id,
                            event_id,
                            {
                                "kind": "erc20_transfer_log",
                                "token": log["address"],
                                "from": "0x" + log["topics"][1][-40:],
                                "to": "0x" + log["topics"][2][-40:],
                                "raw_amount": str(int(log["data"], 16)),
                                "block": int(log["blockNumber"], 16),
                                "transaction": log["transactionHash"],
                                "swap_verified": False,
                                "pnl_usd": None,
                                "note": "Transfer event ERC-20; swap, preț istoric, native ETH și cost basis nu sunt deduse din acest log.",
                            },
                        )
                    status = {
                        "state": "partial" if rejected else "ok",
                        "at": utcnow(),
                        "from_block": start,
                        "to_block": end,
                        "next_block": end + 1 if end < latest else None,
                        "full_history": False,
                        "observed": len(unique),
                        "rejected": rejected,
                    }
            except ProviderError as exc:
                status = {
                    "state": "error",
                    "at": utcnow(),
                    "error": str(exc),
                    "full_history": False,
                }
            with self.store.connect() as db:
                db.execute(
                    "UPDATE tracked_wallets SET status=? WHERE id=?",
                    (json.dumps(status), wallet_id),
                )
        return self.report(wallet_id)

    def report(self, wallet_id):
        with self.store.connect() as db:
            wallet = db.execute("SELECT * FROM tracked_wallets WHERE id=?", (wallet_id,)).fetchone()
            if not wallet:
                raise ValueError("Wallet necunoscut.")
            rows = db.execute(
                "SELECT * FROM wallet_activity WHERE wallet_id=? ORDER BY at DESC,event_id DESC LIMIT 100",
                (wallet_id,),
            ).fetchall()
            count = db.execute(
                "SELECT count(*) FROM wallet_activity WHERE wallet_id=?", (wallet_id,)
            ).fetchone()[0]
        return dict(wallet) | {
            "status": json.loads(wallet["status"]),
            "activity": [dict(r) | {"payload": json.loads(r["payload"])} for r in rows],
            "events_total": count,
            "pnl_usd": None,
            "win_rate": None,
            "copyability": None,
            "full_history": False,
            "missing_for_pnl": [
                "complete transaction/inventory history",
                "historical execution prices",
                "fees and transfers separated",
            ],
            "live_execution": False,
        }

    def listing(self):
        with self.store.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM tracked_wallets ORDER BY id DESC")]
        return [self.report(i) for i in ids]
