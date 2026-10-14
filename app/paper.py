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
    if market.get("kind") == "market_asset":
        return reference_fill(side, size, market, settings)
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


def reference_fill(side, size, market, settings):
    if side not in ("buy", "sell"):
        raise Rejected("Sens necunoscut.")
    size, price = amount(size), amount(market["price_usd"])
    book = market.get("book")
    if book:
        bid, ask = amount(book["bid"]), amount(book["ask"])
        if bid > ask:
            raise Rejected("Order book inversat/invalid.")
        spread = 1 - bid / ask
        if spread > settings.max_price_impact:
            raise Rejected("Spread de piață prea mare pentru simulare.")
        if side == "buy":
            quantity = size * (1 - settings.reference_fee) / ask
            if quantity > amount(book["ask_size"]):
                raise Rejected(
                    "Ordinul depășește cantitatea ask observată; nivelele următoare sunt necunoscute."
                )
            cash = -size
            fee = size * settings.reference_fee
        elif side == "sell":
            if size > amount(book["bid_size"]):
                raise Rejected("Ieșirea depășește cantitatea bid observată.")
            quantity = size
            cash = size * bid * (1 - settings.reference_fee)
            fee = size * bid * settings.reference_fee
        else:
            raise Rejected("Sens necunoscut.")
        model = "observed_level1_book_assumed_fee"
        impact = None
    else:
        slip = settings.reference_slippage
        if slip > settings.max_price_impact:
            raise Rejected("Slippage de scenariu peste limita configurată.")
        quantity = (
            size * (1 - settings.reference_fee) / (price * (1 + slip)) if side == "buy" else size
        )
        cash = -size if side == "buy" else size * price * (1 - slip) * (1 - settings.reference_fee)
        fee = (
            size * settings.reference_fee
            if side == "buy"
            else size * price * (1 - slip) * settings.reference_fee
        )
        model = "market_reference_assumed_slippage_and_fee"
        impact = slip
    return {
        "quantity": str(quantity),
        "cash_change": str(cash),
        "swap_fee_usd": str(fee),
        "network_fee_usd": "0",
        "price_impact": str(impact) if impact is not None else None,
        "spread_fraction": str(spread) if book else None,
        "slippage_assumption_fraction": str(settings.reference_slippage) if not book else None,
        "model": model,
        "execution_verified": False,
        "source": market["source"],
        "book": book,
    }


def break_even(quote, market, settings):
    if market.get("kind") == "market_asset":
        sell_factor = (1 - settings.reference_fee) * (
            1 - settings.reference_slippage if not market.get("book") else 1
        )
        target = -D(quote["cash_change"]) / (amount(quote["quantity"]) * sell_factor)
        book = market.get("book")
        midpoint_target = (
            target * amount(market["price_usd"]) / amount(book["bid"]) if book else target
        )
        return {
            "break_even_price_estimate": str(midpoint_target),
            "break_even_bid_required": str(target) if book else None,
            "break_even_assumption": "constant_relative_spread"
            if book
            else "unchanged_reference_costs",
            "break_even_rise_pct": str((midpoint_target / amount(market["price_usd"]) - 1) * 100),
        }
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
    if snapshot["market"].get("kind") == "market_asset":
        updated = snapshot["market"].get("source_updated_at")
        try:
            source_fresh = bool(updated) and 0 <= now - epoch(updated) <= settings.max_snapshot_age
        except (ValueError, TypeError, OverflowError):
            source_fresh = False
        if not source_fresh:
            raise Rejected("Timestamp-ul sursei de preț este lipsă sau expirat.")


def buy(store, snapshot, signal_id, usd, settings, now=None, execution=None):
    now = now if now is not None else datetime.now(UTC).timestamp()
    require_fresh(snapshot, settings, now)
    if not snapshot["analysis"]["paper_allowed"]:
        raise Rejected("Intrare blocată: risc critic sau verificări incomplete.")
    usd = amount(usd)
    if usd > store.initial_balance:
        raise Rejected("Suma depășește capitalul de referință al contului.")
    if usd < settings.min_position:
        raise Rejected("Poziție sub dimensiunea minimă.")
    quote = (
        validate_execution(execution, "buy", usd, snapshot, now)
        if execution
        else fill("buy", usd, snapshot["market"], settings)
    )
    quote |= (
        {
            "break_even_price_estimate": None,
            "break_even_rise_pct": None,
            "break_even_assumption": "requires_new_routed_exit_quote",
        }
        if execution
        else break_even(quote, snapshot["market"], settings)
    )
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


def sell(store, position_id, snapshot, settings, now=None, execution=None):
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
        if snapshot["market"].get("kind") == "market_asset":
            entry = db.execute(
                "SELECT market FROM snapshots WHERE id=?", (position["entry_snapshot_id"],)
            ).fetchone()
            if entry and json.loads(entry[0]).get("book") and not snapshot["market"].get("book"):
                raise Rejected(
                    "Ieșirea dintr-o poziție simulată cu order book necesită un bid/ask nou."
                )
        entry_order = db.execute(
            "SELECT details FROM orders WHERE side='buy' AND json_extract(details,'$.position_id')=?",
            (position_id,),
        ).fetchone()
        if (
            entry_order
            and json.loads(entry_order[0]).get("model") == "jupiter_quote_conservative_min_out"
            and execution is None
        ):
            raise Rejected("Această poziție necesită un quote Jupiter nou pentru ieșire.")
        quote = (
            validate_execution(execution, "sell", position["quantity"], snapshot, now)
            if execution
            else fill("sell", position["quantity"], snapshot["market"], settings)
        )
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


def validate_execution(execution, side, size, snapshot, now):
    if (
        execution.get("model") != "jupiter_quote_conservative_min_out"
        or execution.get("address") != snapshot["address"]
        or execution.get("side") != side
        or amount(execution.get("requested_size")) != amount(size)
    ):
        raise Rejected("Quote-ul nu corespunde ordinului paper.")
    if not 0 <= now - epoch(execution["quote_observed_at"]) <= 15:
        raise Rejected("Quote-ul Jupiter este expirat sau din viitor.")
    amount(execution.get("quantity"))
    cash = D(execution["cash_change"])
    if not cash.is_finite() or (side == "buy" and cash >= 0) or (side == "sell" and cash <= 0):
        raise Rejected("Cash flow invalid în quote.")
    return dict(execution)
