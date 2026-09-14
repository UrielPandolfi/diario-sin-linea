import json

from sqlalchemy.orm import Session

from app.core.article_body import annotated_article_draft, resolve_article_draft
from app.core.prompts import load_prompt
from app.domain.enums import ClaimImportance, ClaimStatus, EventStatus, EvidenceType
from app.models import ClaimEvidence
from app.providers.fakes import FakeStructuredLLM
from app.schemas import ArticleCreate
from app.schemas.auditing import (
    ArticleAuditResult,
    AuditIssue,
    AuditIssueAction,
    AuditIssueReason,
    AuditIssueSeverity,
    AuditIssueType,
)
from app.services.article_context import build_article_context
from app.services.article_service import ArticleService
from app.services.audit_service import AuditService, normalize_audit_result
from app.services.writing_service import WritingService
from tests.editorial_snapshot import persist_version_snapshot
from tests.test_audit import _claim, _event, _item, _source, _pass_audit


def _issue(*, issue_type, reason, text, claim_id=None, claim_ref=None) -> AuditIssue:
    return AuditIssue(
        type=issue_type,
        severity=AuditIssueSeverity.HIGH,
        text=text,
        explanation="exceso de certeza respecto del posture",
        suggested_fix="Atribuí o calificá; no borres el dato.",
        reason=reason,
        action=AuditIssueAction.ATTRIBUTE,
        claim_id=claim_id,
        claim_ref=claim_ref,
    )


def _seed(session: Session, *, claims: list[dict], headline: str, summary: str, paragraphs: list[list[tuple[str, list[str]]]]):
    source = _source(session)
    item = _item(
        session,
        source.id,
        url="https://lanacion.test/sanjose",
        title="San José 1111",
        body="Informe sobre departamentos en San José 1111.",
        content_hash="sanjose-1",
    )
    event = _event(
        session,
        item,
        title_internal="Departamentos en San José 1111",
        short_summary="Un informe vincula unidades del edificio con dirigentes.",
    )
    event.status = EventStatus.DETECTED
    rows = []
    for spec in claims:
        row = _claim(
            session,
            event,
            text=spec["text"],
            claim_type=spec.get("claim_type", "hecho"),
            importance=ClaimImportance.HIGH,
            status=spec["status"],
        )
        session.add(
            ClaimEvidence(
                claim_id=row.id,
                source_item_id=item.id,
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=spec["text"],
                source_url=item.url,
            )
        )
        rows.append(row)
    ref_map = {f"C{index}": str(row.id) for index, row in enumerate(rows, start=1)}
    draft = annotated_article_draft(headline, summary, paragraphs)
    body, body_blocks = resolve_article_draft(draft, claim_ref_map=ref_map)
    article, _created = ArticleService(session).create_draft(
        ArticleCreate(
            event_id=event.id,
            headline=headline,
            summary=summary,
            body=body,
            body_blocks=body_blocks,
        )
    )
    session.flush()
    persist_version_snapshot(session, event, article)
    return event, article, rows, ref_map


def _attributed_draft(headline: str, summary: str, body: str, refs: list[str]):
    return annotated_article_draft(headline, summary, [[(body, refs)]])


def _audit(session: Session, event, *, result: ArticleAuditResult, draft=None) -> tuple[dict, FakeStructuredLLM]:
    if result.passed:
        responses: dict = {"ArticleAuditResult": result}
    else:
        rewrite = draft or _attributed_draft(
            "Un informe periodístico vincula a Recalde con un departamento en San José 1111",
            "Según la cobertura, la unidad aparece asociada a Recalde.",
            "Según La Nación, Recalde figura como propietario del departamento 1° A.",
            ["C1"],
        )
        responses = {
            "ArticleAuditResult": [result, result, result],
            "ArticleDraft": [rewrite, rewrite],
        }
    llm = FakeStructuredLLM(responses)
    return AuditService(session, llm=llm, writer=llm).audit(event.id, trigger="test"), llm


def test_prompts_require_attribution_not_deletion() -> None:
    writing = load_prompt("article_writing.md")
    audit = load_prompt("article_audit.md")
    assert "NUNCA se convierte en hecho afirmado por Sin Línea" in writing
    assert "titular, bajada y primer párrafo" in writing.casefold()
    assert "dos o más claims SINGLE_SOURCE no autorizan" in writing
    assert "militante" in writing and "dirigente" in writing
    assert "no borres el dato" in writing.casefold()
    assert "headline, summary o lead" in audit.casefold()
    assert "la composición no eleva certeza" in audit
    assert "semantic_shift" in audit
    assert "un cuerpo correctamente atribuido no sana" in audit.casefold()


def test_writing_user_prompt_lists_single_source_and_forbids_synthesis(db_session: Session) -> None:
    source = _source(db_session)
    item = _item(
        db_session,
        source.id,
        url="https://lanacion.test/sanjose-write",
        title="San José 1111",
        body="Informe sobre Recalde y Calle.",
        content_hash="sanjose-write",
    )
    event = _event(db_session, item, title_internal="Departamentos en San José 1111")
    _claim(db_session, event, text="Recalde posee 1° A.", claim_type="hecho", importance=ClaimImportance.HIGH, status=ClaimStatus.SINGLE_SOURCE)
    _claim(db_session, event, text="Calle adquirió 1° B.", claim_type="hecho", importance=ClaimImportance.HIGH, status=ClaimStatus.SINGLE_SOURCE)
    db_session.flush()
    db_session.expire(event, ["claims"])
    prompt = WritingService(db_session)._user_prompt(build_article_context(event))
    assert "Recalde posee 1° A." in prompt
    assert "Calle adquirió 1° B." in prompt
    assert "síntesis categórica" in prompt
    assert "titular, bajada y primer párrafo" in prompt


def test_case_a_categorical_headline_fails(db_session: Session) -> None:
    headline = "Recalde es dueño de un departamento en San José 1111"
    event, _article, rows, refs = _seed(
        db_session,
        claims=[{"text": "Recalde es dueño del 1° A.", "status": ClaimStatus.SINGLE_SOURCE}],
        headline=headline,
        summary="El dirigente aparece como propietario de la unidad.",
        paragraphs=[[("Según La Nación, Recalde figura como propietario del departamento 1° A.", ["C1"])]],
    )
    fail = ArticleAuditResult(
        passed=False,
        issues=[_issue(issue_type=AuditIssueType.UNSUPPORTED_CLAIM, reason=AuditIssueReason.SINGLE_AS_CORROBORATED, text=headline, claim_id=str(rows[0].id), claim_ref="C1")],
    )
    result, llm = _audit(db_session, event, result=fail)
    payload = json.loads(llm.user_prompts[0].split("\n", 1)[1])
    assert payload["headline"] == headline
    assert payload["lead"].startswith("Según La Nación")
    statuses = {row["status"] for row in payload["evidence_posture"] + payload["headline_claim_candidates"]}
    assert "SINGLE_SOURCE" in statuses
    assert normalize_audit_result(fail).passed is False
    assert result["passed"] is False
    assert result["issues"][0]["severity"] == "HIGH"
    assert result["issues"][0]["reason"] == "single_as_corroborated"


def test_case_b_attributed_headline_does_not_fail_on_posture_alone(db_session: Session) -> None:
    headline = "Un informe periodístico vincula a Recalde con un departamento en San José 1111"
    event, article, rows, _refs = _seed(
        db_session,
        claims=[{"text": "Recalde es dueño del 1° A.", "status": ClaimStatus.SINGLE_SOURCE}],
        headline=headline,
        summary="Según la cobertura, Recalde aparece vinculado a la unidad 1° A.",
        paragraphs=[[("Según La Nación, Recalde figura como propietario del departamento 1° A.", ["C1"])]],
    )
    result, llm = _audit(db_session, event, result=_pass_audit())
    payload = json.loads(llm.user_prompts[0].split("\n", 1)[1])
    assert payload["headline"] == headline
    assert any(row["status"] == "SINGLE_SOURCE" for row in payload["evidence_posture"])
    assert result["passed"] is True
    assert result["rewrite_count"] == 0
    assert not any(issue.get("reason") == "single_as_corroborated" for issue in result["issues"])
    assert str(rows[0].id) in {row["claim_id"] for row in payload["evidence_posture"]}


def test_case_c_synthesis_of_two_single_source_fails(db_session: Session) -> None:
    headline = "Dos dirigentes de La Cámpora poseen departamentos en el edificio"
    event, _article, rows, _refs = _seed(
        db_session,
        claims=[
            {"text": "Recalde posee 1° A.", "status": ClaimStatus.SINGLE_SOURCE},
            {"text": "Calle adquirió 1° B.", "status": ClaimStatus.SINGLE_SOURCE},
        ],
        headline=headline,
        summary="Ambos figuran como propietarios de unidades en San José 1111.",
        paragraphs=[[
            ("Según La Nación, Recalde figura como propietario del 1° A.", ["C1"]),
            (" La misma cobertura atribuye a Calle la adquisición del 1° B.", ["C2"]),
        ]],
    )
    fail = ArticleAuditResult(
        passed=False,
        issues=[_issue(issue_type=AuditIssueType.UNSUPPORTED_CLAIM, reason=AuditIssueReason.SINGLE_AS_CORROBORATED, text=headline, claim_id=str(rows[0].id), claim_ref="C1")],
    )
    result, llm = _audit(db_session, event, result=fail)
    payload = json.loads(llm.user_prompts[0].split("\n", 1)[1])
    assert payload["headline"] == headline
    assert {row["canonical_text"] for row in payload["evidence_posture"]} >= {"Recalde posee 1° A.", "Calle adquirió 1° B."}
    assert result["passed"] is False
    assert result["issues"][0]["severity"] == "HIGH"


def test_case_d_supported_fact_in_headline_is_allowed(db_session: Session) -> None:
    headline = "Hubo un incendio en un depósito de Rosario"
    event, _article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": "Hubo un incendio en el depósito.", "status": ClaimStatus.SUPPORTED}],
        headline=headline,
        summary="Las llamas se registraron durante la madrugada.",
        paragraphs=[[("Hubo un incendio en un depósito de Rosario durante la madrugada.", ["C1"])]],
    )
    result, llm = _audit(db_session, event, result=_pass_audit())
    payload = json.loads(llm.user_prompts[0].split("\n", 1)[1])
    assert payload["headline"] == headline
    assert payload["evidence_posture"][0]["status"] == "SUPPORTED"
    assert result["passed"] is True
    assert result["rewrite_count"] == 0


def test_case_e_attributed_body_is_allowed(db_session: Session) -> None:
    event, _article, _rows, _refs = _seed(
        db_session,
        claims=[{"text": "Recalde es dueño del 1° A.", "status": ClaimStatus.SINGLE_SOURCE}],
        headline="Un informe periodístico vincula a Recalde con un departamento en San José 1111",
        summary="La cobertura atribuye la unidad 1° A al dirigente.",
        paragraphs=[[("Según La Nación, Recalde figura como propietario del departamento 1° A.", ["C1"])]],
    )
    result, llm = _audit(db_session, event, result=_pass_audit())
    payload = json.loads(llm.user_prompts[0].split("\n", 1)[1])
    assert payload["lead"] == "Según La Nación, Recalde figura como propietario del departamento 1° A."
    assert result["passed"] is True


def test_case_f_attribution_loss_fails(db_session: Session) -> None:
    text = "La deuda cayó 30%."
    event, _article, rows, _refs = _seed(
        db_session,
        claims=[{"text": "X afirmó que la deuda cayó 30%.", "status": ClaimStatus.SUPPORTED, "claim_type": "declaracion"}],
        headline="La deuda cayó 30%",
        summary="El indicador bajó durante la gestión.",
        paragraphs=[[(text, ["C1"])]],
    )
    fail = ArticleAuditResult(
        passed=False,
        issues=[_issue(issue_type=AuditIssueType.ATTRIBUTION, reason=AuditIssueReason.UTTERANCE_AS_TRUTH, text=text, claim_id=str(rows[0].id), claim_ref="C1")],
    )
    result, _llm = _audit(db_session, event, result=fail)
    assert normalize_audit_result(fail).passed is False
    assert result["passed"] is False
    assert result["issues"][0]["type"] == "ATTRIBUTION"
    assert result["issues"][0]["reason"] == "utterance_as_truth"
    assert result["issues"][0]["severity"] == "HIGH"


def test_case_g_semantic_elevation_fails(db_session: Session) -> None:
    text = "Calle, dirigente de La Cámpora, adquirió el departamento 1° B."
    event, _article, rows, _refs = _seed(
        db_session,
        claims=[{"text": "Calle está vinculada a La Cámpora", "status": ClaimStatus.SINGLE_SOURCE}],
        headline="Calle, dirigente de La Cámpora, tiene un departamento en el edificio",
        summary="La militante aparece asociada a la unidad 1° B.",
        paragraphs=[[(text, ["C1"])]],
    )
    fail = ArticleAuditResult(
        passed=False,
        issues=[_issue(issue_type=AuditIssueType.INFERENCE, reason=AuditIssueReason.SEMANTIC_SHIFT, text=text, claim_id=str(rows[0].id), claim_ref="C1")],
    )
    result, llm = _audit(db_session, event, result=fail)
    assert "un cuerpo bien atribuido no sana un titular categórico" in llm.user_prompts[0]
    assert result["passed"] is False
    assert result["issues"][0]["type"] == "INFERENCE"
    assert result["issues"][0]["reason"] == "semantic_shift"
    assert result["issues"][0]["severity"] == "HIGH"
