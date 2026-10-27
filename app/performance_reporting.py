"""Read-only full-history summaries with streamed outcomes and frozen read time."""

import hashlib
import json
import sqlite3
import time
from collections import Counter, defaultdict

from app.cohort_comparisons import partition
from app.models import epoch
from app.opportunity_catalog import available as catalog_available
from app.opportunity_outcomes import summary, wilson
from app.opportunity_rules import RULE_VERSION


class Aggregate:
    """Preserve Decimal summation order and the original summary contract."""

    def __init__(self):
        from decimal import Decimal

        self.states = Counter()
        self.total = Decimal(0)
        self.measured = self.wins = self.losses = 0

    def add(self, state, pnl):
        self.states[state] += 1
        if state == "evaluated":
            self.measured += 1
            self.wins += pnl > 0
            self.losses += pnl < 0
            self.total += pnl

    def result(self):
        result = summary([])
        n = self.measured
        count = sum(self.states.values())
        result.update(
            experiments=count,
            evaluated=n,
            unresolved_or_unavailable=count - n,
            states=dict(self.states),
            profitable_after_costs=self.wins,
            loss_rate_among_evaluated=self.losses / n if n else None,
            unprofitable_rate_among_evaluated=(n - self.wins) / n if n else None,
            net_pnl_independent_experiments_usd=str(self.total) if n else None,
            mean_net_pnl_usd=str(self.total / n) if n else None,
            win_rate_95pct_wilson_approx=wilson(self.wins, n),
        )
        return result


def projection(db, query, parameters=()):
    # These explicit projections contain JSON text/scalars, never cold blobs.
    # archive_text remains mandatory inside SQL for archived observation columns.
    cursor = db.cursor()
    cursor.row_factory = sqlite3.Row
    return cursor.execute(query, parameters)


def report(engine, now=None):
    from decimal import Decimal

    now = time.time() if now is None else now
    aggregates = defaultdict(Aggregate)
    diagnostics = defaultdict(set)
    first_verdicts, current_verdicts = Counter(), Counter()
    first_security = first_liquidity = current_security = current_liquidity = 0
    collapses = appreciated = 0
    horizons, policies = set(), defaultdict(set)
    overlaps = Counter()
    with engine.store.connect() as db:
        # A report cannot mix candidates read before a write with outcomes read
        # after it. WAL readers do not take the collector's writer lock.
        if not db.in_transaction:
            db.execute("BEGIN")
        totals = {
            key: db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for key, table in [
                ("discovered", "opportunity_candidates"),
                ("signals", "opportunity_signals"),
                ("alerts", "opportunity_alerts"),
                ("observations", "opportunity_observations"),
            ]
        }
        totals["eligible"] = db.execute(
            "SELECT count(*) FROM opportunity_candidates WHERE eligible=1"
        ).fetchone()[0]
        totals["eligible_without_first_evaluation"] = db.execute(
            "SELECT count(*) FROM opportunity_candidates c WHERE eligible=1 AND NOT EXISTS(SELECT 1 FROM opportunity_signals s WHERE s.candidate_id=c.id AND s.kind='baseline')"
        ).fetchone()[0]
        for key, condition in [
            ("risk_update_alerts", "severity='critical'"),
            ("delivered_in_app", "delivered_in_app_at IS NOT NULL"),
            ("telegram_acknowledged", "telegram_state='acknowledged_by_api'"),
        ]:
            totals[key] = db.execute(
                "SELECT count(*) FROM opportunity_alerts WHERE " + condition
            ).fetchone()[0]
        has_catalog = catalog_available(db)
        current_query = """
            SELECT c.id,json_extract(c.discovery,'$.price_usd') AS initial_price,
            json_extract(CASE WHEN typeof(o.payload)='blob' THEN archive_text(o.payload) ELSE o.payload END,
              '$.market.price_usd','$.market.observed_at','$.security.observed_at',
              '$.decision.verdict','$.decision.security_filter_passed',
              '$.decision.liquidity_filter_passed') AS fields
            FROM opportunity_candidates c LEFT JOIN opportunity_observations o ON o.id=(
              SELECT id FROM opportunity_observations WHERE candidate_id=c.id ORDER BY id DESC LIMIT 1)
        """
        if has_catalog:
            current_query = """
              SELECT c.id,
                CASE WHEN x.candidate_id IS NULL OR d.candidate_id IS NOT NULL
                  THEN json_extract(c.discovery,'$.price_usd') ELSE x.initial_price END AS initial_price,
                CASE WHEN x.candidate_id IS NULL OR d.candidate_id IS NOT NULL THEN
                  json_extract(CASE WHEN typeof(o.payload)='blob' THEN archive_text(o.payload) ELSE o.payload END,
                    '$.market.price_usd','$.market.observed_at','$.security.observed_at',
                    '$.decision.verdict','$.decision.security_filter_passed','$.decision.liquidity_filter_passed')
                  ELSE x.current_fields END AS fields
              FROM opportunity_candidates c
              LEFT JOIN ui_catalog_candidates x ON x.candidate_id=c.id
              LEFT JOIN ui_catalog_dirty d ON d.candidate_id=c.id
              LEFT JOIN opportunity_observations o ON o.id=CASE
                WHEN x.candidate_id IS NULL OR d.candidate_id IS NOT NULL THEN (
                  SELECT id FROM opportunity_observations WHERE candidate_id=c.id ORDER BY id DESC LIMIT 1) END
            """
        for row in projection(db, current_query):
            price, market_at, security_at, verdict, security, liquidity = (
                json.loads(row["fields"]) if row["fields"] else [None] * 6
            )
            fresh = bool(
                market_at
                and 0 <= now - epoch(market_at) <= engine.service.settings.max_snapshot_age
            )
            security_fresh = bool(
                security_at
                and 0 <= now - epoch(security_at) <= engine.service.settings.max_snapshot_age
            )
            current_security += bool(fresh and security_fresh and security)
            current_liquidity += bool(fresh and liquidity)
            current_verdicts[verdict or "PENDING"] += 1
            if price is not None and (row["initial_price"] or 0) > 0:
                collapses += price / row["initial_price"] <= 0.2
                appreciated += price / row["initial_price"] >= 2
        baseline_query = """
            SELECT s.id,json_extract(CASE WHEN typeof(o.payload)='blob' THEN archive_text(o.payload) ELSE o.payload END,
              '$.features.changes.5m.volume_5m_ratio','$.features.excessive_extension',
              '$.narrative.supported','$.decision.security_filter_passed',
              '$.decision.liquidity_filter_passed','$.decision.verdict') AS fields
            FROM opportunity_signals s JOIN opportunity_observations o ON o.id=s.observation_id
            WHERE s.kind='baseline'
        """
        if has_catalog:
            baseline_query = """
              SELECT x.signal_id AS id,x.fields FROM ui_catalog_baselines x
              WHERE NOT EXISTS(SELECT 1 FROM ui_catalog_dirty d WHERE d.candidate_id=x.candidate_id)
              UNION ALL
              SELECT s.id,json_extract(CASE WHEN typeof(o.payload)='blob' THEN archive_text(o.payload) ELSE o.payload END,
                '$.features.changes.5m.volume_5m_ratio','$.features.excessive_extension',
                '$.narrative.supported','$.decision.security_filter_passed',
                '$.decision.liquidity_filter_passed','$.decision.verdict') AS fields
              FROM opportunity_signals s JOIN opportunity_observations o ON o.id=s.observation_id
              WHERE s.kind='baseline' AND EXISTS(
                SELECT 1 FROM ui_catalog_dirty d WHERE d.candidate_id=s.candidate_id)
            """
        for row in projection(db, baseline_query):
            volume, extended, narrative, security, liquidity, verdict = json.loads(row["fields"])
            first_security += bool(security)
            first_liquidity += bool(liquidity)
            first_verdicts[verdict] += 1
            for name, matches in [
                ("volume_acceleration_ge_2", (volume or 0) >= 2),
                ("excessive_extension", bool(extended)),
                ("contract_narrative", isinstance(narrative, list) and bool(narrative)),
            ]:
                if matches:
                    diagnostics[row["id"]].add(name)
        policy_values = {}
        # Materialize only small scalars once per signal. Embedded policy fields
        # remain authoritative, including legacy records; do not substitute the
        # current configuration or repeatedly parse a large snapshot per horizon.
        rows = projection(
            db,
            """
            WITH subjects AS MATERIALIZED (
              SELECT s.id,s.candidate_id,s.kind,s.at AS signal_at,
                json_extract(s.payload,'$.policy.id','$.policy.at','$.policy.payload.config.test_from',
                  '$.policy.payload.config.entry_window_seconds',
                  '$.policy.payload.config.exit_window_seconds') AS policy_fields
              FROM opportunity_signals s WHERE EXISTS (
                SELECT 1 FROM opportunity_outcomes o WHERE o.signal_id=s.id)
            )
            SELECT o.signal_id,o.horizon_seconds,o.state,json_extract(o.payload,'$.pnl_usd') AS pnl,
              s.kind,s.signal_at,s.policy_fields,a.id AS alert_id,c.contract,
              e.control_member,e.provenance,e.at AS enrolled_at
            FROM subjects s JOIN opportunity_outcomes o ON o.signal_id=s.id
            JOIN opportunity_candidates c ON c.id=s.candidate_id
            LEFT JOIN opportunity_alerts a ON a.signal_id=s.id AND a.severity!='critical'
            LEFT JOIN sampling_enrollment e ON e.candidate_id=c.id
            ORDER BY s.id,o.horizon_seconds
        """,
        )
        previous_id, subject, prospective, control = None, None, False, False
        for row in rows:
            sid, h, state = row["signal_id"], row["horizon_seconds"], row["state"]
            horizons.add(h)
            if sid != previous_id:
                fields = row["policy_fields"]
                if fields not in policy_values:
                    pid, at, cutoff, entry, exit_window = json.loads(fields)
                    policy_values[fields] = {
                        "policy_id": pid,
                        "policy_at": at,
                        "config_parsed": {
                            "test_from": cutoff,
                            "entry_window_seconds": entry,
                            "exit_window_seconds": exit_window,
                        },
                    }
                subject = policy_values[fields] | {"signal_at": row["signal_at"]}
                prospective = (
                    row["kind"] == "baseline"
                    and row["provenance"] == "prospective"
                    and epoch(row["enrolled_at"]) <= epoch(row["signal_at"])
                )
                control = int(hashlib.sha256(row["contract"].encode()).hexdigest()[:8], 16) % 5 == 0
                previous_id = sid
            pnl = Decimal(row["pnl"]) if state == "evaluated" else None
            keys = []
            selected = row["alert_id"] is not None
            if row["kind"] == "baseline":
                pid = subject["policy_id"]
                policies[h].add(pid)
                keys.extend([(h, "all"), (h, "cohort", partition(subject, h)), (h, "policy", pid)])
                if selected:
                    keys.append((h, "selected"))
                if control:
                    keys.append((h, "control"))
                if prospective:
                    if selected:
                        keys.append((h, "prospective_selected"))
                    if row["control_member"]:
                        keys.append((h, "prospective_control"))
                        overlaps[h] += selected
            elif selected:
                keys.append((h, "later"))
            keys.extend((h, "diagnostic", name) for name in diagnostics.get(sid, ()))
            for key in keys:
                aggregates[key].add(state, pnl)
        extended_alerts = sum(
            bool(row[0])
            for row in projection(
                db,
                "SELECT json_extract(payload,'$.features.excessive_extension') FROM opportunity_alerts",
            )
        )

    def result(*key):
        return aggregates[key].result()

    reports = {}
    for h in sorted(horizons):
        reports[str(h)] = {
            "all_eligible_first_evaluations": result(h, "all"),
            "selected_at_first_evaluation": result(h, "selected"),
            "deterministic_20pct_baseline": result(h, "control"),
            "later_alert_experiments": result(h, "later"),
            "cohorts": {
                c: result(h, "cohort", c)
                for c in ["development", "test", "unassigned", "purged_boundary"]
            },
            "policies": {str(p): result(h, "policy", p) for p in sorted(policies[h])},
            "prospective_comparison": {
                "selected_at_first_evaluation": result(h, "prospective_selected"),
                "fixed_control": result(h, "prospective_control"),
                "overlapping_experiments": overlaps[h],
                "note": "Control assigned before screening, including rejected tokens and any overlapping alerts. Legacy history is excluded. Observation coverage and executable paper results are separate.",
            },
        }
    return {
        "rule_version": RULE_VERSION,
        "totals": totals,
        "sampling": engine.sampling.coverage(),
        "first_evaluation_security_pass": first_security,
        "first_evaluation_liquidity_pass": first_liquidity,
        "first_evaluation_verdicts": dict(first_verdicts),
        "current_security_pass": current_security,
        "current_liquidity_pass": current_liquidity,
        "current_verdicts": dict(current_verdicts),
        "known_current_price_collapses_ge_80pct": collapses,
        "known_current_appreciation_ge_100pct": appreciated,
        "alerts_already_extended_at_signal": extended_alerts,
        "confirmed_unsellable": None,
        "missed_opportunities": None,
        "horizons": reports,
        "exploratory_signal_diagnostics": {
            name: {str(h): result(h, "diagnostic", name) for h in sorted(horizons)}
            for name in ["volume_acceleration_ge_2", "excessive_extension", "contract_narrative"]
        },
        "note": "Partial provider discovery universe, not all launches. Follow-up prioritizes alerts, so comparative coverage is unequal and missingness can bias comparisons. No global missed-opportunity rate. Historical or missing prices are never filled with future data. Independent experiments are not a capital-constrained strategy or demonstrated profit.",
        "live_execution": False,
    }
