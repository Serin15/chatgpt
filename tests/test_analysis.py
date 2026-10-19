from datetime import UTC, datetime

import pytest

from app.analysis import TOKEN_2022_PROGRAM, analyze
from app.models import epoch, utcnow
from tests.conftest import market, security


def test_momentum_cannot_override_critical_authority(settings):
    evidence = security()
    evidence["rpc"]["mint_authority"] = "someone"
    result = analyze(market(change_5m=100, volume_5m=1000000), evidence, settings, epoch(utcnow()))
    assert result["scores"]["momentum"] == 100
    assert result["action"] == "reject"
    assert result["scores"]["research_priority"] == 0
    assert not result["paper_allowed"]


@pytest.mark.parametrize(
    "key",
    [
        "mintable",
        "freezable",
        "none_transferable",
        "closable",
        "balance_mutable_authority",
        "transfer_fee_upgradable",
    ],
)
def test_third_party_critical_flags_are_vetoes(settings, key):
    evidence = security()
    evidence["goplus"][key] = {"status": "1"} if key != "none_transferable" else "1"
    result = analyze(market(), evidence, settings, epoch(utcnow()))
    assert result["action"] == "reject"
    assert any("GoPlus" in risk for risk in result["critical"])


def test_missing_security_is_unknown_not_safe(settings):
    evidence = security()
    evidence["rpc"], evidence["goplus"] = None, None
    result = analyze(market(), evidence, settings, epoch(utcnow()))
    assert result["scores"]["security_risk"] is None
    assert not result["paper_allowed"]
    assert result["action"] == "monitor"
    assert result["scores"]["data_completeness"] == 50


def test_low_liquidity_rejected(settings):
    result = analyze(market(liquidity_usd=1000), security(), settings, epoch(utcnow()))
    assert result["action"] == "reject"


def test_unknown_token_extensions_not_simulated(settings):
    evidence = security()
    evidence["rpc"]["program"] = "Token2022"
    result = analyze(market(), evidence, settings, epoch(utcnow()))
    assert not result["paper_allowed"]
    assert any("nesuportate" in text for text in result["unknown"])


def test_legacy_mint_does_not_require_nontransferable_extension_field(settings):
    evidence = security()
    evidence["goplus"].pop("none_transferable")
    result = analyze(market(), evidence, settings, epoch(utcnow()))
    assert result["paper_allowed"]
    assert result["scores"]["security_risk"] is None  # clean basic checks != low total risk


def test_stale_security_blocks_entry(settings):
    evidence = security()
    evidence["observed_at"] = datetime.fromtimestamp(epoch(utcnow()) - 121, UTC).isoformat()
    assert not analyze(market(), evidence, settings, epoch(utcnow()))["paper_allowed"]


def test_missing_market_fields_not_invented(settings):
    result = analyze(market(volume_5m=None, change_5m=None), security(), settings, epoch(utcnow()))
    assert result["scores"]["activity"] is None
    assert result["scores"]["momentum"] is None
    assert result["scores"]["data_completeness"] < 100


def test_transfer_fee_is_rejected(settings):
    evidence = security()
    evidence["goplus"]["transfer_fee"] = {"current_fee_rate": {"fee_rate": "0.01"}}
    assert analyze(market(), evidence, settings, epoch(utcnow()))["action"] == "reject"


def test_token2022_metadata_only_can_be_simulated(settings):
    evidence = security()
    evidence["rpc"]["program"] = TOKEN_2022_PROGRAM
    evidence["rpc"]["extensions"] = [
        {"extension": "metadataPointer"},
        {"extension": "tokenMetadata"},
    ]
    evidence["goplus"].pop("none_transferable")
    assert analyze(market(), evidence, settings, epoch(utcnow()))["paper_allowed"]


@pytest.mark.parametrize(
    "extensions",
    [None, [{"extension": "transferFeeConfig"}], [{"extension": "unknownFutureExtension"}]],
)
def test_token2022_transfer_extensions_or_missing_list_blocked(settings, extensions):
    evidence = security()
    evidence["rpc"]["program"] = TOKEN_2022_PROGRAM
    evidence["rpc"]["extensions"] = extensions
    assert not analyze(market(), evidence, settings, epoch(utcnow()))["paper_allowed"]
