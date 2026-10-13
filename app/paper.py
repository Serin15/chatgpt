"""Scenario simulation: balanced constant-product reserves inferred from total USD liquidity.

This is NOT a routed quote or proof that a swap can execute. All amounts use Decimal.
"""

import json
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from app.models import epoch, utcnow

D = Decimal


class Rejected(ValueError):
    pass


def amount(value):
    try:
        result = D(str(value))
        if not result.is_finite() or result <= 0:
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError):
        raise Rejected("Suma trebuie să fie finită și pozitivă.") from None


def fill(side, size, market, settings):
    size, price, reserve = (
        amount(size),
        amount(market["price_usd"]),
        amount(market["liquidity_usd"]) / 2,
    )
    if reserve * 2 < settings.min_liquidity:
        raise Rejected("Lichiditate insuficientă pentru simularea ieșirii/intrării.")
    effective = size * (1 - settings.swap_fee)
    if side == "buy":
        quantity = (reserve / price) * effective / (reserve + effective)
        impact = 1 - quantity * price / effective
        result = {
            "quantity": str(quantity),
            "cash_change": str(-(size + settings.network_fee_usd)),
            "swap_fee_usd": str(size * settings.swap_fee),
        }
    elif side == "sell":
        gross = reserve * effective / (reserve / price + effective)
        impact = 1 - gross / (effective * price)
        if gross <= settings.network_fee_usd:
            raise Rejected("Costurile depășesc suma recuperabilă.")
        result = {
            "quantity": str(size),
            "cash_change": str(gross - settings.network_fee_usd),
            "swap_fee_usd": str(size * settings.swap_fee * price),
        }
    else:
        raise Rejected("Sens necunoscut.")
    if impact > settings.max_price_impact:
        raise Rejected("Impactul estimat depășește limita configurată.")
    return result | {
        "price_impact": str(impact),
        "network_fee_usd": str(settings.network_fee_usd),
        "model": "estimated_balanced_constant_product",
        "execution_verified": False,
        "pool_address": market["pair_address"],
    }


def break_even(quote, market, settings):
    reserve = amount(market["liquidity_usd"]) / 2
    net_tokens = amount(quote["quantity"]) * (1 - settings.swap_fee)
    required_gross = -D(quote["cash_change"]) + settings.network_fee_usd
    if required_gross >= reserve:
        return {"break_even_price_estimate": None, "break_even_rise_pct": None}
    target = required_gross * reserve / (net_tokens * (reserve - required_gross))
    return {
        "break_even_price_estimate": str(target),
        "break_even_rise_pct": str((target / amount(market["price_usd"]) - 1) * 100),
    }


def require_fresh(snapshot, settings, now):
    age = now - epoch(snapshot["at"])
    if not 0 <= age <= settings.max_snapshot_age:
        raise Rejected("Snapshot expirat sau timestamp din viitor.")
    age_security = now - epoch(snapshot["security"]["observed_at"])
    if not 0 <= age_security <= settings.max_snapshot_age:
        raise Rejected("Verificările de securitate sunt expirate.")


def buy(store, snapshot, signal_id, usd, settings, now=None):
    now = now if now is not None else datetime.now(UTC).timestamp()
    require_fresh(snapshot, settings, now)
    if not snapshot["analysis"]["paper_allowed"]:
        raise Rejected("Intrare blocată: risc critic sau verificări incomplete.")
    usd = amount(usd)
    if usd < settings.min_position:
        raise Rejected("Poziție sub dimensiunea minimă.")
    quote = fill("buy", usd, snapshot["market"], settings)
    quote |= break_even(quote, snapshot["market"], settings)
    cost = -D(quote["cash_change"])
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        signal = db.execute("SELECT * FROM signals WHERE id=?", (signal_id,)).fetchone()
        if not signal or signal["address"] != snapshot["address"]:
            raise Rejected("Semnal inexistent sau pentru alt token.")
        delay = now - epoch(signal["at"])
        if delay < settings.min_signal_delay or delay > settings.max_snapshot_age:
            raise Rejected("Semnal prea nou sau expirat; creează unul nou și așteaptă 3 secunde.")
        if epoch(snapshot["at"]) < epoch(signal["at"]):
            raise Rejected("Intrarea necesită un snapshot colectat după semnal.")
        if db.execute("SELECT 1 FROM positions WHERE signal_id=?", (signal_id,)).fetchone():
            raise Rejected("Semnal deja utilizat.")
        rows = db.execute("SELECT * FROM positions WHERE closed_at IS NULL").fetchall()
        if any(r["address"] == snapshot["address"] for r in rows):
            raise Rejected("Există deja o poziție deschisă pentru token.")
        cash = D(db.execute("SELECT balance FROM account WHERE id=1").fetchone()[0])
        exposure = sum((D(r["entry_cost"]) for r in rows), D(0))
        capital = min(store.initial_balance, cash + exposure)
        if cost > capital * settings.max_allocation:
            raise Rejected("Alocarea maximă per poziție este depășită (inclusiv costuri).")
        if cost + exposure > capital * settings.max_exposure:
            raise Rejected("Expunerea totală maximă este depășită.")
        if cost > cash:
            raise Rejected("Sold paper insuficient.")
        day = datetime.fromtimestamp(now, UTC).date().isoformat()
        losses = sum(
            (
                max(D(0), -D(r[0]))
                for r in db.execute(
                    "SELECT pnl FROM positions WHERE closed_at LIKE ?", (day + "%",)
                )
            ),
            D(0),
        )
        if losses >= store.initial_balance * settings.daily_loss_limit:
            raise Rejected("Limita zilnică a pierderilor realizate a fost atinsă (UTC).")
        db.execute("UPDATE account SET balance=? WHERE id=1", (str(cash - cost),))
        row = db.execute(
            "INSERT INTO positions(address,quantity,entry_cost,entry_at,entry_snapshot_id,signal_id) VALUES(?,?,?,?,?,?)",
            (
                snapshot["address"],
                quote["quantity"],
                str(cost),
                utcnow(),
                snapshot["id"],
                signal_id,
            ),
        )
        quote |= {
            "snapshot_id": snapshot["id"],
            "signal_id": signal_id,
            "position_id": row.lastrowid,
            "reasons": snapshot["analysis"],
            "signal_delay_seconds": delay,
            "entry_context": json.loads(signal["evidence"]),
        }
        db.execute(
            "INSERT INTO orders(address,side,at,status,details) VALUES(?,?,?,?,?)",
            (snapshot["address"], "buy", utcnow(), "filled", json.dumps(quote)),
        )
    return quote


def sell(store, position_id, snapshot, settings, now=None):
    now = now if now is not None else datetime.now(UTC).timestamp()
    require_fresh(snapshot, settings, now)
    # Fail closed: a price/liquidity snapshot alone cannot establish sellability.
    if not snapshot["analysis"]["paper_allowed"]:
        raise Rejected(
            "Ieșire nesimulată: sellability nevalidată sau risc critic; poziția rămâne deschisă."
        )
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        position = db.execute(
            "SELECT * FROM positions WHERE id=? AND closed_at IS NULL", (position_id,)
        ).fetchone()
        if not position or position["address"] != snapshot["address"]:
            raise Rejected("Poziție închisă, inexistentă sau token diferit.")
        quote = fill("sell", position["quantity"], snapshot["market"], settings)
        proceeds = D(quote["cash_change"])
        pnl = proceeds - D(position["entry_cost"])
        cash = D(db.execute("SELECT balance FROM account WHERE id=1").fetchone()[0])
        db.execute("UPDATE account SET balance=? WHERE id=1", (str(cash + proceeds),))
        db.execute(
            "UPDATE positions SET closed_at=?,exit_proceeds=?,pnl=? WHERE id=?",
            (utcnow(), str(proceeds), str(pnl), position_id),
        )
        quote |= {
            "position_id": position_id,
            "pnl": str(pnl),
            "snapshot_id": snapshot["id"],
            "exit_reason": "manual_paper_exit",
        }
        db.execute(
            "INSERT INTO orders(address,side,at,status,details) VALUES(?,?,?,?,?)",
            (snapshot["address"], "sell", utcnow(), "filled", json.dumps(quote)),
        )
    return quote
