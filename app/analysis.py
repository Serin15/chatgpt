"""Deterministic screening rules, not probabilities or forecasts."""

import math

from app.models import epoch

LEGACY_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"


def supported_program(rpc):
    if not rpc:
        return False
    if rpc.get("program") == LEGACY_TOKEN_PROGRAM:
        return True
    extensions = rpc.get("extensions")
    return (
        rpc.get("program") == TOKEN_2022_PROGRAM
        and isinstance(extensions, list)
        and all(
            isinstance(e, dict) and e.get("extension") in {"metadataPointer", "tokenMetadata"}
            for e in extensions
        )
    )


def flag(report, key):
    value = report.get(key)
    if isinstance(value, dict):
        value = value.get("status")
    if str(value) in ("0", "1"):
        return int(value)
    return None


def analyze(market, security, settings, now):
    critical, unknown, positive, warnings = [], [], [], []
    rpc = security.get("rpc")
    report = security.get("goplus") or {}
    rpc_complete = False
    if not rpc:
        unknown.append("Autoritățile mint/freeze nu au fost verificate prin RPC.")
    else:
        rpc_complete = True
        for key, label in (
            ("mint_authority", "Mint authority"),
            ("freeze_authority", "Freeze authority"),
        ):
            value = rpc.get(key, "unknown")
            if value == "unknown":
                unknown.append(f"{label}: necunoscut.")
                rpc_complete = False
            elif value is not None:
                critical.append(f"[RPC] {label} activă.")
            else:
                positive.append(f"[RPC] {label} revocată.")
        if not supported_program(rpc):
            unknown.append(
                "Program/extensii nesuportate: doar SPL și Token-2022 cu metadata în MVP."
            )
            rpc_complete = False
    legacy = supported_program(rpc)
    required = (
        ("mintable", "freezable") if legacy else ("mintable", "freezable", "none_transferable")
    )
    gp_complete = bool(report) and all(flag(report, key) is not None for key in required)
    for key, label in (
        ("mintable", "Token mintabil"),
        ("freezable", "Conturi înghețabile"),
        ("none_transferable", "Transferuri interzise"),
        ("closable", "Mint închizabil"),
        ("balance_mutable_authority", "Solduri modificabile"),
        ("transfer_fee_upgradable", "Taxă de transfer modificabilă"),
        ("transfer_hook_upgradable", "Transfer hook modificabil"),
    ):
        status = flag(report, key)
        if status == 1:
            critical.append(f"[GoPlus, raport terț] {label}.")
        elif status is None and key in required:
            unknown.append(f"[GoPlus] {label}: informație lipsă.")
    if str(report.get("default_account_state")) in ("0", "2"):
        critical.append("[GoPlus] Conturi neinițializate sau înghețate implicit.")
    if report.get("transfer_hook"):
        critical.append("[GoPlus] Transfer hook: comportament nesimulat.")
    fees = report.get("transfer_fee")
    if isinstance(fees, dict) and fees:
        current = fees.get("current_fee_rate")
        current = current.get("fee_rate") if isinstance(current, dict) else None
        try:
            fee_value = float(current)
            if not math.isfinite(fee_value) or fee_value < 0:
                raise ValueError
            if fee_value > 0 or fees.get("scheduled_fee_rate"):
                critical.append("[GoPlus] Taxe de transfer curente/planificate nesimulate.")
        except (ValueError, TypeError):
            unknown.append("[GoPlus] Taxa de transfer nu poate fi interpretată.")
            gp_complete = False
    if not report:
        unknown.append("Raportul GoPlus nu este disponibil.")
    # These fields do not establish owner-level concentration or unlocked liquidity.
    warnings.append("Concentrarea pe proprietari, wash trading și retragerea LP sunt nevalidate.")
    warnings.append("Cumpărările/vânzările sunt tranzacții raportate, nu participanți unici.")
    liquid = market.liquidity_usd >= float(settings.min_liquidity)
    if not liquid:
        critical.append(f"Lichiditate sub pragul de ${settings.min_liquidity}.")
    fresh = 0 <= now - epoch(market.observed_at) <= settings.max_snapshot_age
    if not fresh:
        unknown.append("Datele de piață sunt expirate.")
    security_fresh = 0 <= now - epoch(security["observed_at"]) <= settings.max_snapshot_age
    if not security_fresh:
        unknown.append("Verificările de securitate sunt expirate.")
    market_complete = all(
        v is not None
        for v in (
            market.volume_5m,
            market.volume_1h,
            market.change_5m,
            market.buys_5m,
            market.sells_5m,
        )
    )
    if not market_complete:
        unknown.append("Unele ferestre de volum/preț/tranzacții nu sunt raportate.")
    total = (market.buys_5m or 0) + (market.sells_5m or 0)
    # Transparent heuristic: volume relative to reported liquidity + transaction count.
    activity = (
        round(min(60, market.volume_5m / max(market.liquidity_usd, 1) * 300) + min(40, total / 2))
        if market.volume_5m is not None
        and market.buys_5m is not None
        and market.sells_5m is not None
        else None
    )
    momentum = (
        round(max(0, min(100, 50 + market.change_5m * 2))) if market.change_5m is not None else None
    )
    exit_score = round(min(100, market.liquidity_usd / float(settings.min_liquidity) * 50))
    completeness = 30 + 20 * int(market_complete) + 25 * int(rpc_complete) + 25 * int(gp_complete)
    if (market.change_5m or 0) > 30:
        warnings.append("Creștere >30% în 5m; intrarea poate fi întârziată.")
    paper_allowed = not critical and rpc_complete and gp_complete and fresh and security_fresh
    action = (
        "reject"
        if critical
        else ("investigate" if paper_allowed and (activity or 0) >= 50 else "monitor")
    )
    priority = round(0.6 * (activity or 0) + 0.2 * (momentum or 0) + 0.2 * exit_score)
    if not paper_allowed:
        priority = 0
    return {
        "action": action,
        "paper_allowed": paper_allowed,
        "scores": {
            "security_risk": 100 if critical else None,
            "liquidity_exit": exit_score,
            "activity": activity,
            "momentum": momentum,
            "data_completeness": completeness,
            "research_priority": priority,
            "wallet_quality": None,
            "copyability": None,
        },
        "critical": critical,
        "unknown": unknown,
        "positive": positive,
        "warnings": warnings,
        "explanation_type": "deterministic_rules",
        "invalidation": [
            "Autoritate privilegiată/restricție nouă",
            "Scăderea lichidității sub prag",
            "Date expirate sau surse indisponibile",
        ],
    }
