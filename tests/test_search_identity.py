"""Real isolated SQLite and simulated providers; contract identity is case sensitive."""

from app.models import solana_address
from tests.test_observation_sampling import candidate
from tests.test_opportunities import client_engine as client_engine


def test_exact_contract_disambiguates_distinct_case_sensitive_solana_addresses(client_engine):
    client, engine = client_engine
    c = candidate(engine, 16000, 0)
    other = candidate(engine, 16001, 0)
    alias = solana_address(c["contract"].swapcase())
    assert alias != c["contract"]
    with engine.store.connect() as db:
        db.execute("UPDATE opportunity_candidates SET contract=? WHERE id=?", (alias, other["id"]))
    for contract, expected in [(c["contract"], c["id"]), (alias, other["id"])]:
        r = client.get("/api/opportunities", params={"q": contract, "sort": "rank"})
        assert r.status_code == 200
        data = r.json()
        assert [v["id"] for v in data["items"]] == [expected]
        assert data["matching_total"] == 1


def test_untracked_exact_address_never_matches_another_case_variant(client_engine):
    client, engine = client_engine
    c = candidate(engine, 16000, 0)
    response = client.get(
        "/api/opportunities", params={"q": solana_address(c["contract"].swapcase())}
    )
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["matching_total"] == 0


def test_legacy_search_deadline_is_preserved_and_indexed_api_avoids_payload_scan(client_engine, monkeypatch):
    from itertools import chain, repeat

    client, engine = client_engine
    for i in range(100):
        candidate(engine, 17000 + i, 0)
    ticks = chain([0], repeat(100))
    monkeypatch.setattr("app.opportunities.monotonic", lambda: next(ticks))
    import pytest

    from app.providers import ProviderError

    with pytest.raises(ProviderError, match="adresa exactă"):
        engine.listing(query="unmatched text")
    response = client.get("/api/opportunities", params={"q": "unmatched text"})
    assert response.status_code == 200 and response.json()["matching_total"] == 0
    assert client.get("/api/opportunities").status_code == 200
    assert client.get("/healthz").status_code == 200
