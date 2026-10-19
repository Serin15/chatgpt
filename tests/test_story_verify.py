"""The live checker itself must reject mismatched or incomplete fixture evidence."""

import copy
import time

from app.story_verify import assess
from tests.test_opportunities import stamp


def sample():
    at = time.time() - 1000
    source = {
        "news_id": 1,
        "source_sha256": "a" * 64,
        "document_observed_at": stamp(at),
        "evidence_indexed_at": stamp(at + 1),
    }
    detail = {
        "id": 7,
        "discovered_at": stamp(at + 2),
        "discovery": {
            "discovery_basis": "exact_contract_news_mention_not_launch",
            "story_evidence": source,
        },
        "observations": [
            {
                "market": {"price_usd": 1},
                "security": {"rpc": {"slot": 1}},
                "source_kind": "live_provider_observation",
            }
        ],
        "signals": [
            {
                "id": 9,
                "kind": "baseline",
                "verdict": "INVESTIGATE",
                "at": stamp(at + 3),
                "payload": {"narrative": {"supported": [copy.deepcopy(source)]}},
            }
        ],
        "outcomes": [
            {
                "signal_id": 9,
                "state": "evaluated",
                "horizon_seconds": 300,
                "payload": {
                    "exit_at": stamp(at + 400),
                    "actual_hold_seconds": 396,
                    "pnl_usd": "-2",
                },
            }
        ],
    }
    alerts = [
        {"candidate_id": 7, "delivered_in_app_at": stamp(at + 5), "payload": {"signal_id": 9}}
    ]
    return detail, {"state": "resolved_pool"}, alerts


def test_checker_requires_one_linked_signal_and_actual_later_outcome():
    assert all(assess(*sample()).values())


def test_checker_does_not_reuse_an_unrelated_signal_outcome_or_receipt():
    detail, job, alerts = sample()
    detail["signals"][0]["payload"]["narrative"]["supported"][0]["news_id"] = 2
    result = assess(detail, job, alerts)
    assert not result["stored_signal_with_narrative_and_verdict"]
    assert not result["eligible_alert_generated"] and not result["later_outcome_evaluated"]


def test_checker_rejects_future_or_short_or_missing_outcomes():
    for overrides in [
        {"exit_at": stamp(time.time() + 300)},
        {"actual_hold_seconds": 1},
        {"pnl_usd": None},
    ]:
        detail, job, alerts = sample()
        detail["outcomes"][0]["payload"].update(overrides)
        assert not assess(detail, job, alerts)["later_outcome_evaluated"]


def test_document_available_after_discovery_is_not_initial_discovery_evidence():
    detail, job, alerts = sample()
    detail["discovery"]["story_evidence"]["evidence_indexed_at"] = stamp(time.time())
    assert not assess(detail, job, alerts)["candidate_discovered_from_document"]


def test_market_reference_verification_is_explicit_and_requires_same_api_evidence():
    from tests.test_story_markets import reference

    detail, job, alerts = sample()
    at = detail["discovery"]["story_evidence"]["document_observed_at"]
    ref = reference(observed_at=at, pool_created_at_reported=None)
    detail["contract"] = ref["base_contract"]
    detail["discovery"]["discovery_basis"] = "news_market_pair_reference_not_launch"
    detail["discovery"]["story_evidence"]["market_reference"] = ref
    detail["signals"][0]["payload"]["narrative"] = {
        "market_references": [copy.deepcopy(detail["discovery"]["story_evidence"])]
    }
    assert not assess(detail, job, alerts)["candidate_discovered_from_document"]
    assert all(assess(detail, job, alerts, "market_reference").values())
    detail["signals"][0]["payload"]["narrative"]["market_references"][0]["market_reference"][
        "response_sha256"
    ] = "b" * 64
    assert not assess(detail, job, alerts, "market_reference")["eligible_alert_generated"]


def test_risk_alert_is_not_an_eligible_opportunity_alert():
    detail, job, alerts = sample()
    alerts[0]["severity"] = "critical"
    assert not assess(detail, job, alerts)["eligible_alert_generated"]


def test_wrong_reference_kind_is_not_a_direct_document_contract_proof():
    detail, job, alerts = sample()
    detail["discovery"]["discovery_basis"] = "news_market_pair_reference_not_launch"
    assert not assess(detail, job, alerts)["real_document_contract_reference"]


def test_future_receipt_is_not_verified_delivery():
    detail, job, alerts = sample()
    alerts[0]["delivered_in_app_at"] = stamp(time.time() + 3600)
    assert not assess(detail, job, alerts)["in_app_delivery_receipt"]
