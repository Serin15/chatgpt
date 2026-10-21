"""Point-in-time opportunity features and transparent gates. Scores are not probabilities."""

import math
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.analysis import analyze
from app.models import Market, epoch
from app.paper import Rejected, break_even, fill

RULE_VERSION = "memescope-3.2-market-references"


class EngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = True
    interval_seconds: int = Field(default=60, ge=30, le=3600)
    discovery_pages: int = Field(default=2, ge=1, le=10)
    observation_budget: int = Field(default=60, ge=1, le=100)
    active_watch_seconds: int = Field(default=900, ge=300, le=3600)
    background_interval_seconds: int = Field(default=86400, ge=3600, le=604800)
    background_watch_hours: int = Field(default=48, ge=1, le=168)
    security_budget: int = Field(default=8, ge=1, le=30)
    activity_samples: int = Field(default=0, ge=0, le=10)
    cooldown_seconds: int = Field(default=3600, ge=60, le=86400)
    min_transactions_5m: int = Field(default=10, ge=1, le=10000)
    max_pool_age_hours: int = Field(default=24, ge=1, le=168)
    max_change_5m_pct: float = Field(default=30, gt=0, le=200)
    max_extension_pct: float = Field(default=50, gt=0, le=500)
    max_roundtrip_cost_pct: float = Field(default=5, gt=0, le=20)
    max_liquidity_drop_pct: float = Field(default=30, gt=0, le=90)
    position_usd: float = Field(default=50, ge=2, le=500)
    horizons_seconds: list[int] = Field(
        default_factory=lambda: [300, 3600, 86400], min_length=1, max_length=5
    )
    entry_window_seconds: int = Field(default=180, ge=30, le=600)
    exit_window_seconds: int = Field(default=180, ge=30, le=1800)
    alert_verdicts: list[str] = Field(default_factory=lambda: ["INVESTIGATE", "CONSIDER"])
    telegram_enabled: bool = False
    ai_narratives: bool = False
    routed_quotes_enabled: bool = True
    routed_quote_budget: int = Field(default=4, ge=1, le=10)
    routed_slippage_bps: int = Field(default=50, ge=0, le=200)
    test_from: AwareDatetime | None = None

    def validated(self):
        if len(set(self.horizons_seconds)) != len(self.horizons_seconds) or any(
            h not in {300, 900, 3600, 86400, 604800} for h in self.horizons_seconds
        ):
            raise ValueError("Horizons: 300/900/3600/86400/604800 seconds, without duplicates.")
        if not set(self.alert_verdicts) <= {"INVESTIGATE", "CONSIDER"}:
            raise ValueError("Opportunity alerts require INVESTIGATE or CONSIDER.")
        return self


def pct(current, previous):
    return (
        (current / previous - 1) * 100
        if current is not None and previous is not None and previous > 0
        else None
    )


def features(market, history, discovery, at, config, activity=None, distribution=None):
    now = epoch(at)
    previous = [r for r in history if r.get("market") and epoch(r["at"]) < now]
    changes = {}
    for label, seconds in [("5m", 300), ("15m", 900), ("1h", 3600)]:
        eligible = [
            r
            for r in previous
            if seconds <= now - epoch(r["at"]) <= seconds + max(120, seconds * 0.25)
        ]
        old = min(eligible, key=lambda r: now - epoch(r["at"])) if eligible else None
        changes[label] = (
            None
            if old is None
            else {
                "baseline_observation_id": old["id"],
                "baseline_at": old["at"],
                "elapsed_seconds": round(now - epoch(old["at"])),
                "price_change_pct": pct(market["price_usd"], old["market"]["price_usd"]),
                "liquidity_change_pct": pct(
                    market["liquidity_usd"], old["market"]["liquidity_usd"]
                ),
                "reported_buyers_change_pct": pct(
                    market.get("buyers_5m_reported"), old["market"].get("buyers_5m_reported")
                ),
                "volume_5m_ratio": market["volume_5m"] / old["market"]["volume_5m"]
                if market.get("volume_5m") is not None and (old["market"].get("volume_5m") or 0) > 0
                else None,
            }
        )
    recent = max(previous, key=lambda r: epoch(r["at"])) if previous else None
    liquidity_change = (
        pct(market["liquidity_usd"], recent["market"]["liquidity_usd"]) if recent else None
    )
    created = discovery.get("pool_created_at_reported")
    try:
        pool_age = (now - epoch(created)) / 3600 if created and epoch(created) <= now else None
    except (ValueError, TypeError):
        pool_age = None
    extension = pct(market["price_usd"], discovery.get("price_usd"))
    reference = (discovery.get("story_evidence") or {}).get("market_reference") or {}
    prior_move = None
    try:
        reported = reference.get("price_change_24h_reported_pct")
        if (
            0 <= now - epoch(reference["observed_at"]) <= 86400
            and isinstance(reported, (int, float))
            and not isinstance(reported, bool)
            and math.isfinite(reported)
        ):
            prior_move = reported
    except (ValueError, TypeError, KeyError, OverflowError):
        pass
    late = (
        (market.get("change_5m") or 0) > config.max_change_5m_pct
        or (extension is not None and extension > config.max_extension_pct)
        or (prior_move is not None and prior_move > config.max_extension_pct)
    )
    suspicions = []
    if liquidity_change is not None and liquidity_change <= -config.max_liquidity_drop_pct:
        suspicions.append(
            {
                "kind": "liquidity_withdrawal_or_revaluation",
                "severity": "high",
                "origin": "provider_observation",
                "value_pct": liquidity_change,
                "note": "Reported USD liquidity decreased; token price changes can also revalue reserves. Removal is not proven.",
            }
        )
    buys, sells = market.get("buys_5m"), market.get("sells_5m")
    if (
        buys is not None
        and sells is not None
        and buys + sells >= 20
        and max(buys, sells) / (buys + sells) >= 0.95
    ):
        suspicions.append(
            {
                "kind": "one_sided_reported_activity",
                "severity": "medium",
                "origin": "statistical_suspicion",
                "note": "Transaction imbalance does not identify unique buyers or manipulation.",
            }
        )
    if (market.get("volume_5m") or 0) > market["liquidity_usd"] * 3:
        suspicions.append(
            {
                "kind": "high_turnover",
                "severity": "medium",
                "origin": "statistical_suspicion",
                "note": "High turnover can reflect genuine trading, arbitrage or artificial volume; not proof of wash trading.",
            }
        )
    if activity:
        for flag in activity.get("suspicions", []):
            suspicions.append(flag)
    concentration = (distribution or {}).get("top10_token_accounts_pct")
    if concentration is not None and concentration >= 80:
        suspicions.append(
            {
                "kind": "concentrated_token_accounts",
                "severity": "medium",
                "origin": "rpc_observation",
                "value_pct": concentration,
                "note": "Token accounts are not beneficial owners; LP/custody not excluded.",
            }
        )
    return {
        "pool_age_hours": pool_age,
        "token_launch_time_known": False,
        "price_change_since_first_capture_pct": extension,
        "story_reference_prior_24h_move_reported_pct": prior_move,
        "excessive_extension": late,
        "changes": changes,
        "latest_liquidity_change_pct": liquidity_change,
        "reported_transactions_5m": None if buys is None or sells is None else buys + sells,
        "unique_buyers": (activity or {}).get("unique_buy_candidates"),
        "buyers_5m_provider_reported": market.get("buyers_5m_reported"),
        "sellers_5m_provider_reported": market.get("sellers_5m_reported"),
        "activity_sample": activity,
        "holder_growth": None,
        "social_mentions_growth": None,
        "distribution": distribution,
        "suspicions": suspicions,
        "history_observations": len(previous),
        "history_span_seconds": now - min(epoch(r["at"]) for r in previous) if previous else 0,
        "organic_demand_verified": False,
    }


def costs(market, settings, size):
    try:
        entry = fill("buy", str(size), market, settings)
        exit_quote = fill("sell", entry["quantity"], market, settings)
        net = Decimal(exit_quote["cash_change"]) + Decimal(entry["cash_change"])
        return {
            "entry": entry,
            "same_price_exit": exit_quote,
            "roundtrip_net_usd": str(net),
            "roundtrip_cost_pct": float(-net / -Decimal(entry["cash_change"]) * 100),
            **break_even(entry, market, settings),
            "model": "estimated_pool_not_routed",
            "economically_feasible_in_model": True,
            "execution_verified": False,
        }
    except (Rejected, ValueError, KeyError, TypeError, ArithmeticError):
        return {
            "economically_feasible_in_model": False,
            "execution_verified": False,
            "error": "Liquidity/size/impact constraints prevent the estimated round trip.",
        }


def evaluate(market, security, feature, narrative, wallet, settings, config, at):
    base = analyze(Market(**market), security, settings, epoch(at))
    positive = list(base["positive"])
    negative = list(base["critical"])
    unknown = list(base["unknown"])
    severe = [s for s in feature["suspicions"] if s["severity"] == "high"]
    security_critical = [s for s in base["critical"] if s.startswith(("[RPC]", "[GoPlus"))]
    rpc_ok = security.get("rpc") is not None
    security_pass = (
        base["security_checks_complete"] and base["security_fresh"] and not security_critical
    )
    security_risk = 100 if security_critical else 0 if security_pass else None
    c = costs(market, settings, config.position_usd)
    if c["economically_feasible_in_model"]:
        positive.append("Small-position estimated round trip passes liquidity and impact limits.")
    else:
        negative.append("Small-position modeled entry/exit unavailable.")
    if feature["excessive_extension"]:
        negative.append("Price already exceeds the configured extension threshold; avoid chasing.")
    if severe:
        negative.append("Large observed USD liquidity decline; requires recheck.")
    for flag in feature["suspicions"]:
        negative.append(
            f"{flag['kind']} ({flag['origin']}): {flag.get('note', 'Requires investigation; not proof of manipulation.')}"
        )
    if feature["unique_buyers"] is None:
        unknown.append(
            "Unique buyer identities are not independently validated; provider counters and transaction counts do not prove organic participation."
        )
    if feature["holder_growth"] is None:
        unknown.append("Owner-level holder growth unavailable.")
    narrative_supported = narrative.get("ranking_supported", bool(narrative.get("supported")))
    if not narrative_supported:
        unknown.append(
            "No corroborated contract-specific narrative; name matches remain uncertain."
        )
    if narrative.get("contradictory"):
        unknown.append(
            "Contract-specific sources contain negative or contradictory context; issuer claims require independent review."
        )
    if wallet.get("score") is None:
        unknown.append("No reliable monitored-wallet accumulation evidence.")
    unknown.append(
        "Wash trading, developer identity, LP ownership and sellability are not proven by aggregate data."
    )
    unknown.append(
        "Pool API freshness uses receipt time; an upstream trade timestamp is not supplied by these endpoints."
    )
    tx = feature["reported_transactions_5m"]
    activity = feature.get("activity_sample") or {}
    participation = None if tx is None else min(40, round(math.log1p(tx) * 8))
    if feature.get("buyers_5m_provider_reported") is not None:
        participation = min(60, feature["buyers_5m_provider_reported"] * 5)
    if activity.get("unique_buy_candidates") is not None:
        participation = min(80, activity["unique_buy_candidates"] * 10)
        if (activity.get("max_wallet_share") or 0) > 0.5:
            participation = min(participation, 20)
    age = feature["pool_age_hours"]
    early = (
        None
        if market.get("change_5m") is None
        else 0
        if feature["excessive_extension"]
        else min(100, max(0, 50 + market["change_5m"]))
    )
    if early is not None and age is not None and age > config.max_pool_age_hours:
        early = min(early, 20)
    reliability = (
        (25 if rpc_ok else 0)
        + (25 if security.get("goplus") else 0)
        + 20
        + min(15, feature["history_observations"] * 5)
        + (10 if activity.get("sample_size", 0) >= 3 else 0)
        + (5 if narrative_supported else 0)
    )
    liquidity = min(100, round(market["liquidity_usd"] / float(settings.min_liquidity) * 40))
    entry = (
        0
        if feature["excessive_extension"]
        else min(100, round((early or 0) * 0.5 + liquidity * 0.3 + (participation or 0) * 0.2))
    )
    scores = {
        "security_risk": security_risk,
        "exit_liquidity": liquidity,
        "market_participation_quality": participation,
        "early_momentum": early,
        "wallet_intelligence": wallet.get("score"),
        "narrative_social_evidence": narrative.get("score"),
        "entry_attractiveness": entry,
        "data_reliability": reliability,
    }
    verdict = "MONITOR"
    if base["critical"] or severe:
        verdict = "REJECT"
    elif (
        security_pass
        and c["economically_feasible_in_model"]
        and not feature["excessive_extension"]
        and tx is not None
        and tx >= config.min_transactions_5m
        and age is not None
        and age <= config.max_pool_age_hours
        and c["roundtrip_cost_pct"] <= config.max_roundtrip_cost_pct
    ):
        verdict = "INVESTIGATE"
        positive.append(
            "Fresh security screening, reported activity and recent pool age support further research."
        )
        window = feature["changes"]["5m"] or {}
        if (
            feature["history_span_seconds"] >= 600
            and (window.get("volume_5m_ratio") or 0) >= 1.2
            and window.get("liquidity_change_pct") is not None
            and window["liquidity_change_pct"] >= 0
            and participation is not None
            and participation >= 50
            and not feature["suspicions"]
            and reliability >= 80
        ):
            verdict = "CONSIDER"
            positive.append(
                "Observed history and non-overlapping five-minute windows support liquidity retention and reported or sampled participation."
            )
    if tx is None:
        unknown.append("Recent transaction counts unavailable.")
    if age is None:
        unknown.append("Pool creation timestamp unavailable; early status is unconfirmed.")
    rank = (
        round(entry * 0.4 + liquidity * 0.2 + (early or 0) * 0.2 + reliability * 0.2)
        if verdict in {"INVESTIGATE", "CONSIDER"}
        else None
    )
    return {
        "rule_version": RULE_VERSION,
        "verdict": verdict,
        "rank_score": rank,
        "scores": scores,
        "positive": positive,
        "negative": negative,
        "unknown": list(dict.fromkeys(unknown)),
        "costs": c,
        "screening": base,
        "security_filter_passed": security_pass,
        "liquidity_filter_passed": market["liquidity_usd"] >= float(settings.min_liquidity),
        "invalidation": [
            "New privileged authority or transfer restriction",
            "Liquidity decline or unavailable exit quote",
            "Fresh evidence no longer available",
            "Momentum becomes excessively extended",
            "Contradictory contract/source evidence",
        ],
        "score_note": "Heuristic research scores, not probabilities. Security risk: higher is worse; other known scores: higher is stronger evidence. Unknown dimensions stay null.",
    }
