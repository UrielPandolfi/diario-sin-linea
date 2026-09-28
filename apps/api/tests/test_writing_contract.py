"""Writing recibe el contrato pareado sin inventar permisos ni tocar Audit."""

from types import SimpleNamespace

from app.core.prompts import load_prompt
from app.domain.enums import ClaimImportance, ClaimStatus, PipelineStatus
from app.schemas.editorial_evidence import EvaluationState, ReasonCode
from app.schemas.writing import ArticleContext
from app.services.article_context import (
    build_article_context,
    claim_contract_fields,
    project_snapshot_contracts,
)
from app.services.audit_service import AuditService
from app.services.evidence_snapshot import article_context_from_snapshot
from app.services.surface_validation import surface_validation_findings
from app.services.writing_service import WritingService

_RESTRICTED = {
    "attribution_required": True,
    "categorical_allowed": False,
    "headline_unattributed_allowed": False,
    "independent_confirmation_language_allowed": False,
}
_OPEN = {
    "attribution_required": False,
    "categorical_allowed": True,
    "headline_unattributed_allowed": True,
    "independent_confirmation_language_allowed": True,
}


def _claim(**kwargs):
    row = SimpleNamespace(
        evidence=[],
        occurred_at=None,
        subject=None,
        predicate=None,
        object_text=None,
        normalized_value=None,
        unit=None,
        claim_type="hecho",
    )
    for key, value in kwargs.items():
        setattr(row, key, value)
    return row


def _event(claims):
    return SimpleNamespace(
        id="event-1",
        event_type="otro",
        title_internal="Viaje",
        locality=None,
        province=None,
        neighborhood=None,
        started_at=None,
        short_summary=None,
        claims=claims,
        event_sources=[],
        event_entities=[],
        updates=[],
    )


def _runs(decisions: dict):
    ids = list(decisions)
    evaluated = [{"claim_id": cid} for cid in ids]
    claim_run = SimpleNamespace(
        id="claim-run",
        stage="claim_resolution",
        status=PipelineStatus.SUCCESS,
        metadata_json={
            "claims_fingerprint": "fp-contract",
            "evaluated_claims": evaluated,
            "coverage": {"coverage_gap": False, "expected_central": []},
        },
    )
    verify_run = SimpleNamespace(
        id="verify-run",
        stage="verification",
        status=PipelineStatus.SUCCESS,
        metadata_json={
            "claims_fingerprint": "fp-contract",
            "based_on_claim_run_id": "claim-run",
            "evaluated_claims": evaluated,
            "decision_by_claim_id": decisions,
        },
    )
    return [claim_run, verify_run]


def _by_id(context: ArticleContext) -> dict:
    found = {}
    for bucket in (
        context.confirmed_claims,
        context.single_source_claims,
        context.conflicting_claims,
        context.uncertain_claims,
        context.disproven_claims,
        context.outdated_claims,
    ):
        for claim in bucket:
            found[claim.id] = claim
    return found


def _reasons(issues) -> set[str]:
    out = set()
    for issue in issues:
        reason = issue.reason
        out.add(reason.value if hasattr(reason, "value") else str(reason))
    return out


def _surface_snapshot(claims: list[dict], decisions: dict) -> dict:
    buckets = {
        "confirmed_claims": [],
        "single_source_claims": [],
        "uncertain_claims": [],
        "outdated_claims": [],
    }
    evaluated = []
    for claim in claims:
        row = dict(claim)
        evaluated.append(row)
        status = row["status"]
        if status == "SUPPORTED":
            buckets["confirmed_claims"].append(row)
        elif status == "SINGLE_SOURCE":
            buckets["single_source_claims"].append(row)
        elif status == "OUTDATED":
            buckets["outdated_claims"].append(row)
        else:
            buckets["uncertain_claims"].append(row)
    return {
        "evaluated_claims": evaluated,
        "decision_by_claim_id": decisions,
        "article_context": {
            "event": {"event_id": "e", "event_type": "otro", "working_title": "Viaje"},
            **buckets,
        },
        "claims_fingerprint": "fp-c5",
        "verification_run_id": "v1",
        "based_on_claim_run_id": "c1",
        "coverage_run_id": "c1",
        "coverage": {"coverage_gap": False, "expected_central": []},
    }


def test_claim_contract_fields_copy_readers_and_drop_llm_reason() -> None:
    fields = claim_contract_fields(
        {
            "evaluation_state": "complete",
            "reason_code": "SINGLE_KNOWN_ORIGIN",
            "verified_scope": "  la denuncia  ",
            "unsupported_scope": "",
            "public_rendering": _RESTRICTED,
            "llm_reason": "no copiar",
            "status": "SINGLE_SOURCE",
        }
    )
    assert fields["evaluation_state"] is EvaluationState.COMPLETE
    assert fields["reason_code"] is ReasonCode.SINGLE_KNOWN_ORIGIN
    assert fields["verified_scope"] == "la denuncia"
    assert fields["unsupported_scope"] is None
    assert fields["public_rendering"].categorical_allowed is False
    assert "llm_reason" not in fields
    assert "no copiar" not in str(fields)


def test_absent_or_incomplete_contract_does_not_grant_permissions() -> None:
    empty = claim_contract_fields(None)
    assert all(value is None for value in empty.values())
    legacy = claim_contract_fields({"status": "SUPPORTED", "claim_id": "c"})
    assert legacy["evaluation_state"] is None
    assert legacy["public_rendering"] is None
    skipped = claim_contract_fields(
        {
            "status": "SUPPORTED",
            "evaluation_state": "skipped",
            "llm_reason": "veto",
            "public_rendering": _OPEN,
            "verified_scope": "no debería usarse",
        }
    )
    assert skipped["evaluation_state"] is EvaluationState.SKIPPED
    assert skipped["public_rendering"] is None
    pending = claim_contract_fields(
        {"evaluation_state": "pending", "public_rendering": _OPEN, "status": "SUPPORTED"}
    )
    failed = claim_contract_fields(
        {"evaluation_state": "failed", "public_rendering": _OPEN, "status": "SINGLE_SOURCE"}
    )
    assert pending["public_rendering"] is None
    assert failed["evaluation_state"] is EvaluationState.FAILED
    assert failed["public_rendering"] is None
    complete_without_rendering = claim_contract_fields(
        {
            "status": "SUPPORTED",
            "evaluation_state": "complete",
            "reason_code": "INDEPENDENT_CORROBORATION",
            "verified_scope": "El colectivo chocó en Pellegrini.",
        }
    )
    assert complete_without_rendering["public_rendering"] is None
    assert complete_without_rendering["verified_scope"] == "El colectivo chocó en Pellegrini."


def test_build_article_context_keeps_paired_contract_on_included_claims() -> None:
    open_id = "supported-open"
    restricted_supported = "supported-restricted"
    single_id = "single"
    uncertain_id = "uncertain"
    skipped_supported = "skipped-supported"
    skipped_outdated = "skipped-outdated"
    claims = [
        _claim(
            id=open_id,
            canonical_text="Milei llegará al aeropuerto JFK el martes a las 9:30.",
            importance=ClaimImportance.HIGH,
            status=ClaimStatus.SUPPORTED,
        ),
        _claim(
            id=restricted_supported,
            canonical_text="El dato sigue atribuido pese al status.",
            importance=ClaimImportance.HIGH,
            status=ClaimStatus.SUPPORTED,
        ),
        _claim(
            id=single_id,
            canonical_text="Villaggi denunció irregularidades en la escuela.",
            importance=ClaimImportance.HIGH,
            status=ClaimStatus.SINGLE_SOURCE,
        ),
        _claim(
            id=uncertain_id,
            canonical_text="Anunciaron acciones legales contra la delegada.",
            importance=ClaimImportance.MEDIUM,
            status=ClaimStatus.UNCERTAIN,
        ),
        _claim(
            id=skipped_supported,
            canonical_text="Este hecho no entra al balde confirmado.",
            importance=ClaimImportance.HIGH,
            status=ClaimStatus.SUPPORTED,
        ),
        _claim(
            id=skipped_outdated,
            canonical_text="La agenda anterior mencionaba otra escala.",
            importance=ClaimImportance.LOW,
            status=ClaimStatus.OUTDATED,
        ),
    ]
    decisions = {
        open_id: {
            "claim_id": open_id,
            "status": "SUPPORTED",
            "evaluation_state": "complete",
            "reason_code": "INDEPENDENT_CORROBORATION",
            "verified_scope": "Milei llegará al aeropuerto JFK el martes a las 9:30.",
            "unsupported_scope": None,
            "public_rendering": _OPEN,
            "llm_reason": "no-copiar-razon",
            "support_basis": {"kind": "independent_reporting", "known_independent_count": 2},
        },
        restricted_supported: {
            "claim_id": restricted_supported,
            "status": "SUPPORTED",
            "evaluation_state": "complete",
            "public_rendering": _RESTRICTED,
            "verified_scope": "El dato sigue atribuido pese al status.",
        },
        single_id: {
            "claim_id": single_id,
            "status": "SINGLE_SOURCE",
            "evaluation_state": "complete",
            "reason_code": "SINGLE_KNOWN_ORIGIN",
            "verified_scope": "Villaggi denunció irregularidades en la escuela.",
            "public_rendering": _RESTRICTED,
        },
        uncertain_id: {
            "claim_id": uncertain_id,
            "status": "UNCERTAIN",
            "evaluation_state": "complete",
            "reason_code": "INSUFFICIENT_EVIDENCE",
            "verified_scope": None,
            "unsupported_scope": "Anunciaron acciones legales contra la delegada.",
            "public_rendering": _RESTRICTED,
            "support_basis": {
                "documents_supporting": 0,
                "evaluated_canonical_text": "Anunciaron acciones legales contra la delegada.",
            },
        },
        skipped_supported: {
            "claim_id": skipped_supported,
            "status": "SUPPORTED",
            "evaluation_state": "skipped",
            "llm_reason": "policy_skip",
            "public_rendering": _OPEN,
        },
        skipped_outdated: {
            "claim_id": skipped_outdated,
            "status": "OUTDATED",
            "evaluation_state": "skipped",
            "llm_reason": "veto",
            "public_rendering": _OPEN,
            "verified_scope": "no conceder",
        },
    }
    context = build_article_context(_event(claims), pipeline_runs=_runs(decisions))
    found = _by_id(context)
    assert skipped_supported not in found
    assert skipped_supported not in context.verification.decision_by_claim_id
    outdated = found[skipped_outdated]
    assert outdated.evaluation_state is EvaluationState.SKIPPED
    assert outdated.public_rendering is None
    assert outdated.verified_scope is None
    open_claim = found[open_id]
    assert open_claim.public_rendering.categorical_allowed is True
    assert open_claim.public_rendering.attribution_required is False
    assert open_claim.reason_code is ReasonCode.INDEPENDENT_CORROBORATION
    restricted = found[restricted_supported]
    assert restricted.status is ClaimStatus.SUPPORTED
    assert restricted.public_rendering.categorical_allowed is False
    single = found[single_id]
    assert single.public_rendering.attribution_required is True
    assert single.evaluation_state is EvaluationState.COMPLETE
    uncertain = found[uncertain_id]
    assert uncertain.verified_scope is None
    assert uncertain.unsupported_scope == "Anunciaron acciones legales contra la delegada."
    assert uncertain.support_basis.evaluated_canonical_text.startswith("Anunciaron")
    dumped = context.model_dump_json()
    assert "no-copiar-razon" not in dumped
    assert "policy_skip" not in dumped

    trimmed = build_article_context(
        _event(claims),
        pipeline_runs=_runs(decisions),
        claim_ids={single_id},
        include_source_contexts=False,
    )
    trimmed_found = _by_id(trimmed)
    assert set(trimmed_found) == {single_id}
    assert trimmed_found[single_id].public_rendering.headline_unattributed_allowed is False
    prompt = WritingService._user_prompt(None, trimmed)
    assert "categorical_allowed" in prompt
    assert "unsupported_scope" in prompt
    assert "Villaggi denunció irregularidades" in prompt
    assert "event.working_title no obliga" in prompt


def test_historical_snapshot_projects_in_memory_without_persisting_or_granting() -> None:
    stored_claim = {
        "id": "c1",
        "ref": "C1",
        "canonical_text": "Llegó el martes a las 9:30.",
        "importance": "HIGH",
        "status": "SUPPORTED",
    }
    snapshot = {
        "article_context": {
            "event": {"event_id": "e", "event_type": "otro", "working_title": "Viaje"},
            "confirmed_claims": [stored_claim],
        },
        "decision_by_claim_id": {
            "c1": {
                "claim_id": "c1",
                "status": "SUPPORTED",
                "evaluation_state": "complete",
                "reason_code": "INDEPENDENT_CORROBORATION",
                "verified_scope": "Llegó el martes a las 9:30.",
                "unsupported_scope": None,
                "public_rendering": _OPEN,
                "llm_reason": "secreto-historico",
            },
            "legacy": {
                "claim_id": "legacy",
                "status": "SUPPORTED",
            },
        },
    }
    context = article_context_from_snapshot(snapshot)
    claim = context.confirmed_claims[0]
    assert claim.evaluation_state is EvaluationState.COMPLETE
    assert claim.public_rendering.categorical_allowed is True
    assert claim.verified_scope == "Llegó el martes a las 9:30."
    assert "evaluation_state" not in snapshot["article_context"]["confirmed_claims"][0]
    assert "public_rendering" not in snapshot["article_context"]["confirmed_claims"][0]
    assert "secreto-historico" not in claim.model_dump_json()

    legacy_context = ArticleContext.model_validate(
        {
            "event": {"event_id": "e", "event_type": "otro", "working_title": "Viaje"},
            "single_source_claims": [
                {
                    "id": "old",
                    "ref": "C1",
                    "canonical_text": "Un dato viejo.",
                    "importance": "MEDIUM",
                    "status": "SINGLE_SOURCE",
                }
            ],
        }
    )
    assert legacy_context.single_source_claims[0].public_rendering is None
    assert legacy_context.single_source_claims[0].evaluation_state is None
    project_snapshot_contracts(
        legacy_context,
        {"old": {"status": "SINGLE_SOURCE", "claim_id": "old"}},
    )
    assert legacy_context.single_source_claims[0].public_rendering is None
    assert legacy_context.single_source_claims[0].evaluation_state is None

    already = ArticleContext.model_validate(
        {
            "event": {"event_id": "e", "event_type": "otro", "working_title": "Viaje"},
            "confirmed_claims": [
                {
                    "id": "kept",
                    "ref": "C1",
                    "canonical_text": "Dato restringido.",
                    "importance": "HIGH",
                    "status": "SUPPORTED",
                    "evaluation_state": "complete",
                    "public_rendering": _RESTRICTED,
                }
            ],
        }
    )
    project_snapshot_contracts(
        already,
        {"kept": {"evaluation_state": "complete", "status": "SUPPORTED", "public_rendering": _OPEN}},
    )
    assert already.confirmed_claims[0].public_rendering.categorical_allowed is False

    article = SimpleNamespace(headline="h", summary="s", body="b", body_blocks=[])
    rewrite = AuditService._rewrite_user_prompt(None, context, article, [])
    assert "verified_scope" in rewrite
    assert "categorical_allowed" in rewrite
    assert "secreto-historico" not in rewrite
    assert "unsupported_scope" in rewrite


def test_prompt_states_contract_without_dropping_prior_rules() -> None:
    writing = load_prompt("article_writing.md")
    assert "Contrato editorial de cada claim" in writing
    assert "evaluation_state=complete" in writing
    assert "unsupported_scope" in writing
    assert "attribution_required" in writing
    assert "working_title" in writing
    assert "Denunció" in writing and "presunto" in writing
    assert "NUNCA se convierte en hecho afirmado por Sin Línea" in writing
    assert "síntesis categórica" in writing
    assert "titular, bajada y primer párrafo" in writing.casefold()
    assert "Según [fuente], en 2009 fue nombrada subsecretaria" in writing
    assert "sin “según varias fuentes” delante de cada oración" in writing
    assert "Párrafos o segmentos enteros con `claim_refs: []` son correctos" in writing
    assert "no borres el dato" in writing.casefold()
    assert "estimación, proyección o expectativa privada" in writing


def test_attributed_single_source_and_open_supported_keep_existing_surface_rules() -> None:
    single = "Villaggi denunció irregularidades en la escuela de Gran Guardia."
    supported = "Milei llegará al aeropuerto JFK el martes a las 9:30."
    snapshot = _surface_snapshot(
        [
            {
                "id": "s1",
                "canonical_text": single,
                "status": "SINGLE_SOURCE",
                "importance": "HIGH",
            },
            {
                "id": "s2",
                "canonical_text": supported,
                "status": "SUPPORTED",
                "importance": "HIGH",
            },
        ],
        {
            "s1": {
                "claim_id": "s1",
                "status": "SINGLE_SOURCE",
                "evaluation_state": "complete",
                "public_rendering": _RESTRICTED,
                "verified_scope": single,
            },
            "s2": {
                "claim_id": "s2",
                "status": "SUPPORTED",
                "evaluation_state": "complete",
                "public_rendering": _OPEN,
                "verified_scope": supported,
            },
        },
    )
    attributed = surface_validation_findings(
        snapshot,
        SimpleNamespace(
            headline=f"Según un medio local, {single}",
            summary=f"Según un medio local, {single}",
            body=supported,
            body_blocks=None,
        ),
    )
    assert "surface_attribution" not in _reasons(attributed)
    assert "surface_categorical" not in _reasons(attributed)
    assert "surface_contract_incomplete" not in _reasons(attributed)

    own_voice = surface_validation_findings(
        snapshot,
        SimpleNamespace(
            headline=supported,
            summary="La llegada al JFK está prevista para el martes a las 9:30.",
            body=supported,
            body_blocks=None,
        ),
    )
    headline_issues = [issue for issue in own_voice if issue.claim_ref == "headline"]
    assert "surface_attribution" not in _reasons(headline_issues)
    assert "surface_categorical" not in _reasons(headline_issues)
    assert "surface_contract_incomplete" not in _reasons(headline_issues)


def test_out_of_scope_surface_stays_blocked_with_segun_conditional_or_neighbor() -> None:
    skipped = "Milei participará de la Asamblea General de la ONU."
    neighbor = "Milei llegará al aeropuerto JFK el martes a las 9:30."
    snapshot = _surface_snapshot(
        [
            {"id": "skipped", "canonical_text": skipped, "status": "OUTDATED", "importance": "LOW"},
            {"id": "neighbor", "canonical_text": neighbor, "status": "SUPPORTED", "importance": "HIGH"},
        ],
        {
            "skipped": {
                "claim_id": "skipped",
                "status": "OUTDATED",
                "evaluation_state": "skipped",
                "llm_reason": "veto",
                "public_rendering": _OPEN,
                "verified_scope": skipped,
            },
            "neighbor": {
                "claim_id": "neighbor",
                "status": "SUPPORTED",
                "evaluation_state": "complete",
                "public_rendering": _OPEN,
                "verified_scope": neighbor,
            },
        },
    )
    lead = f"Según la agenda, {skipped}"
    conditional = f"Según un medio, podría ser que {skipped}"
    article = SimpleNamespace(
        headline=neighbor,
        summary=neighbor,
        body=lead,
        body_blocks=[
            {
                "type": "paragraph",
                "segments": [{"text": lead, "claim_ids": ["neighbor"]}],
            }
        ],
    )
    issues = surface_validation_findings(snapshot, article)
    incomplete = [
        issue
        for issue in issues
        if getattr(issue.reason, "value", issue.reason) == "surface_contract_incomplete"
        and issue.claim_id == "skipped"
    ]
    assert incomplete
    assert all(issue.severity.value == "HIGH" for issue in incomplete)

    conditional_issues = surface_validation_findings(
        snapshot,
        SimpleNamespace(
            headline=neighbor,
            summary=neighbor,
            body=conditional,
            body_blocks=[{"type": "paragraph", "segments": [{"text": conditional, "claim_ids": ["neighbor"]}]}],
        ),
    )
    assert any(
        issue.claim_id == "skipped"
        and getattr(issue.reason, "value", issue.reason) == "surface_contract_incomplete"
        for issue in conditional_issues
    )
