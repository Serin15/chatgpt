"""Bridge immutable engine evidence to a separately timed manual paper decision.

No study rows or financial execution rules are changed here. All fills still go
through the existing manual ledger, its fresh quotes, delay and risk limits.
"""

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app import paper
from app.models import epoch, solana_address, utcnow
from app.paper import Rejected


class OpportunityPaperInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: int = Field(gt=0)
    account: Literal["scanner", "news"] = "news"
    thesis: str = Field(default="", max_length=1000)
    amount_usd: str = Field(default="50", max_length=32)


def source_context(store, candidate_id, observation_id):
    """Pin the observation actually displayed, before any awaited provider calls."""
    linked_at = utcnow()
    with store.connect() as db:
        db.execute("BEGIN")
        candidate = db.execute(
            "SELECT * FROM opportunity_candidates WHERE id=?", (candidate_id,)
        ).fetchone()
        if not candidate:
            raise LookupError("Candidat inexistent.")
        if candidate["chain"] != "solana" or not candidate["eligible"]:
            raise Rejected("Simularea manuală este disponibilă doar pentru candidați Solana eligibili.")
        try:
            solana_address(candidate["contract"])
        except ValueError:
            raise Rejected("Contract Solana invalid; intrare blocată.") from None
        observation = db.execute(
            "SELECT * FROM opportunity_observations WHERE id=? AND candidate_id=?",
            (observation_id, candidate_id),
        ).fetchone()
        if not observation:
            raise LookupError("Observația nu aparține acestui candidat.")
        latest = db.execute(
            "SELECT at,payload FROM opportunity_observations WHERE candidate_id=? ORDER BY id DESC LIMIT 1",
            (candidate_id,),
        ).fetchone()
        selected = dict(observation) | {"payload": json.loads(observation["payload"])}
        if epoch(selected["at"]) > epoch(linked_at) or epoch(latest["at"]) > epoch(linked_at):
            raise Rejected("Observație cu dată viitoare; verifică ceasul și sursa.")
        # Do not let a stale open dossier bypass a more recent engine rejection.
        for item in (selected["payload"], json.loads(latest["payload"])):
            verdict = item.get("decision", {}).get("verdict")
            if verdict not in {"MONITOR", "INVESTIGATE", "CONSIDER"}:
                raise Rejected("Verdictul motorului blochează intrarea. Actualizează dosarul și dovezile.")

        def signal(where, args):
            row = db.execute(
                "SELECT * FROM opportunity_signals WHERE candidate_id=? AND "
                + where + " ORDER BY id LIMIT 1", (candidate_id, *args),
            ).fetchone()
            return dict(row) | {"payload": json.loads(row["payload"])} if row else None

        return {
            "candidate_id": candidate_id,
            "chain": candidate["chain"],
            "contract": candidate["contract"],
            "pool": candidate["pool"],
            "discovered_at": candidate["discovered_at"],
            "discovery": json.loads(candidate["discovery"]),
            "observation": selected,
            "discovery_signal": signal("kind='discovery'", ()),
            "observation_signal": signal("observation_id=?", (observation_id,)),
            "linked_at": linked_at,
            "scope": "manual_decision_not_automatic_study_entry",
        }


async def prepare(service, candidate_id, body):
    size = paper.amount(body.amount_usd)
    if size > service.paper_store(body.account).initial_balance:
        raise Rejected("Suma depășește capitalul de referință al contului.")
    context = source_context(service.store, candidate_id, body.observation_id)
    context["intended_amount_usd"] = str(size)
    address = context["contract"]
    await service.refresh(address)
    service.store.add_token(address, "manual_opportunity", watch=True)
    saved = service.signal(
        address, body.account, thesis=body.thesis, opportunity_context=context
    )
    preview = {"available": False, "reason": "Verificări incomplete sau risc critic."}
    if service.jupiter.enabled:
        preview["reason"] = "Mod Jupiter: costurile necesită o cotație nouă la ordin; nu substituim o estimare de pool."
    elif saved["snapshot"]["analysis"]["paper_allowed"]:
        try:
            entry = paper.fill("buy", size, saved["snapshot"]["market"], service.settings)
            exit_ = paper.fill("sell", entry["quantity"], saved["snapshot"]["market"], service.settings)
            preview = {
                "available": True,
                "entry": entry,
                "exit_at_unchanged_price": exit_,
                "roundtrip_pnl_usd": str(paper.D(entry["cash_change"]) + paper.D(exit_["cash_change"])),
                **paper.break_even(entry, saved["snapshot"]["market"], service.settings),
                "scope": "indicative_pool_estimate_not_guaranteed_execution",
            }
        except Rejected as exc:
            preview["reason"] = str(exc)
    return saved | {
        "cost_preview": preview,
        "min_delay_seconds": service.settings.min_signal_delay,
        "valid_for_seconds": service.settings.max_snapshot_age,
        "live_execution": False,
    }


def validate_origin(service, paper_store, signal_id, amount_usd):
    """A later engine rejection must also veto an already prepared manual buy."""
    with paper_store.connect() as db:
        row = db.execute("SELECT evidence FROM signals WHERE id=?", (signal_id,)).fetchone()
    origin = json.loads(row["evidence"]).get("opportunity_context") if row else None
    if origin:
        intended = origin.get("intended_amount_usd")
        if intended is not None and paper.amount(amount_usd) != paper.amount(intended):
            raise Rejected("Suma diferă de decizia salvată; salvează o decizie nouă.")
        try:
            source_context(service.store, origin["candidate_id"], origin["observation"]["id"])
        except LookupError:
            raise Rejected("Dovada oportunității nu mai este disponibilă; intrare blocată.") from None
