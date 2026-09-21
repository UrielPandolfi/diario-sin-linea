from types import SimpleNamespace
from uuid import uuid4

from app.domain.enums import ClaimImportance, ClaimStatus, EvidenceType
from app.schemas.editorial_evidence import ReasonCode, SupportKind
from app.schemas.verification import VerificationPlan, VerificationSubject, VerificationTarget
from app.services.claim_service import clamp_supported_status
from app.services.editorial_label_policy import is_checked
from app.services.editorial_reason import reason_code_for
from app.services.information_origin import assess_origins, demotion_for, support_kind_for
from app.services.verification_outcome import VerificationView, is_strong_verification
from app.services.verification_plan import apply_primary_requirement, heuristic_plan
from app.services.verification_policy import requires_authoritative_source


def _item(*, url: str, body: str, title: str = "Nota", source_id=None, domain: str | None = None):
    host = domain or url.split("/")[2]
    return SimpleNamespace(
        clean_text=body,
        canonical_url=url,
        url=url,
        title=title,
        source=SimpleNamespace(id=source_id or uuid4(), domain=host, is_monitored=True),
        metadata_json={"body_source": "extracted_html", "fetch_ok": True},
    )


def _row(*, url: str, excerpt: str, body: str, evidence_type=EvidenceType.SUPPORTS, **item_kw):
    item = _item(url=url, body=body, **item_kw)
    return SimpleNamespace(
        evidence_type=evidence_type,
        excerpt=excerpt,
        source_item=item,
        source_url=url,
    )


def _claim(*, text: str, claim_type: str = "hecho", importance=ClaimImportance.MEDIUM, status=ClaimStatus.SINGLE_SOURCE, evidence=None, **extra):
    payload = {
        "id": uuid4(),
        "canonical_text": text,
        "claim_type": claim_type,
        "importance": importance,
        "status": status,
        "subject": extra.pop("subject", None),
        "predicate": extra.pop("predicate", None),
        "object_text": extra.pop("object_text", None),
        "normalized_value": extra.pop("normalized_value", None),
        "unit": extra.pop("unit", None),
        "occurred_at": None,
        "evidence": evidence or [],
    }
    payload.update(extra)
    return SimpleNamespace(**payload)


def _view(claim, *, kind: str, primary: bool = False, known: int = 2):
    cid = str(claim.id)
    return VerificationView(
        selected_ids={cid},
        paired=True,
        primary_source_supports={cid: primary},
        decision_by_claim_id={
            cid: {
                "claim_id": cid,
                "status": claim.status.value,
                "unresolved": False,
                "support_basis": {
                    "kind": kind,
                    "known_independent_count": known,
                    "demotion": "none",
                },
            }
        },
        sol_by_id={cid: {"claim_id": cid, "status_after": claim.status.value, "unresolved": False}},
    )


def _reason_code(claim, assessment, *, status: str, desired: str, primary_required: bool = False, primary_supports: bool = False):
    demotion = demotion_for(
        desired_status=desired,
        final_status=status,
        assessment=assessment,
        primary_required=primary_required,
        primary_supports=primary_supports,
        mixed=False,
        role=None,
    )
    kind = support_kind_for(status=status, assessment=assessment, primary_access=None)
    return reason_code_for(
        status=status,
        demotion=demotion,
        known_independent=assessment.known_independent,
        unknown_groups=assessment.unknown_groups,
        authoritative_independent=assessment.authoritative_independent,
        statement_evidence_class=assessment.statement_evidence_class,
        support_kind=kind,
        documents_supporting=assessment.documents_supporting,
        documents_qualifying=assessment.documents_qualifying,
    )


def test_observable_fact_two_independent_outlets_supported_without_primary() -> None:
    body_a = (
        "Se produjo un incendio en un depósito de Rosario durante la madrugada. "
        "Vecinos alertaron a los bomberos y las llamas se veían desde varias cuadras."
    )
    body_b = (
        "Bomberos trabajan en un incendio registrado en un depósito de Rosario. "
        "La columna de humo se extendió sobre la zona sur y no hay heridos reportados por esa redacción."
    )
    claim = _claim(
        text="Se produjo un incendio en un depósito de Rosario",
        evidence=[
            _row(url="https://medio-a.test/incendio", excerpt=body_a, body=body_a, domain="medio-a.test"),
            _row(url="https://medio-b.test/fuego", excerpt=body_b, body=body_b, domain="medio-b.test"),
        ],
    )
    assessment = assess_origins(claim)
    assert assessment.known_independent >= 2
    assert assessment.reporting_independent >= 2
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SUPPORTED
    plan = heuristic_plan(claim)
    assert plan.primary_source_required is False
    assert requires_authoritative_source(claim) is False
    status = apply_primary_requirement(claim, ClaimStatus.SUPPORTED, plan, primary_supports=False)
    assert status == ClaimStatus.SUPPORTED
    kind = support_kind_for(status="SUPPORTED", assessment=assessment, primary_access="not_found")
    assert kind == SupportKind.INDEPENDENT_REPORTING
    assert _reason_code(claim, assessment, status="SUPPORTED", desired="SUPPORTED") is ReasonCode.INDEPENDENT_CORROBORATION
    claim.status = ClaimStatus.SUPPORTED
    view = _view(claim, kind=kind.value, primary=False, known=assessment.known_independent)
    assert is_checked(claim, view) is True


def test_single_outlet_stays_single_source() -> None:
    body = "Se produjo un incendio en un depósito de Rosario durante la madrugada según testigos de la zona."
    claim = _claim(
        text="Se produjo un incendio en un depósito de Rosario",
        evidence=[_row(url="https://medio-a.test/incendio", excerpt=body, body=body, domain="medio-a.test")],
    )
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE
    assessment = assess_origins(claim)
    assert assessment.known_independent <= 1
    assert _reason_code(
        claim, assessment, status="SINGLE_SOURCE", desired="SUPPORTED"
    ) in {ReasonCode.SINGLE_KNOWN_ORIGIN, ReasonCode.INDEPENDENCE_NOT_ESTABLISHED}


def test_same_outlet_rss_and_research_source_is_single_origin() -> None:
    """RSS Source with empty domain + research Source for the same host is one outlet."""
    excerpt_a = (
        "Milei volverá hoy al país del norte, que ya visitó 18 veces. Pese al récord de giras, "
        "el Gobierno se niega a aportar información sobre los costos y las comitivas."
    )
    excerpt_b = (
        "Ante los pedidos de información pública, el gobierno sigue sin transparentar los gastos "
        "y la conformación de las comitivas, aportes de terceros y explotación comercial de la "
        "investidura presidencial."
    )
    rss = SimpleNamespace(
        id=uuid4(),
        domain=None,
        feed_url="https://www.pagina12.com.ar/arc/outboundfeeds/rss/secciones/el-pais/notas/",
        homepage_url=None,
        is_monitored=True,
    )
    research = SimpleNamespace(
        id=uuid4(),
        domain="pagina12.com.ar",
        feed_url=None,
        homepage_url=None,
        is_monitored=False,
    )
    item_a = SimpleNamespace(
        clean_text=excerpt_a,
        canonical_url="https://www.pagina12.com.ar/2026/09/21/el-world-tour-de-milei/",
        url="https://www.pagina12.com.ar/2026/09/21/el-world-tour-de-milei/",
        title="World Tour",
        source=rss,
        metadata_json={"body_source": "extracted_html", "fetch_ok": True},
    )
    item_b = SimpleNamespace(
        clean_text=excerpt_b,
        canonical_url="https://www.pagina12.com.ar/2026/09/21/nuevo-viaje-a-eeuu/",
        url="https://www.pagina12.com.ar/2026/09/21/nuevo-viaje-a-eeuu/",
        title="Cuentas",
        source=research,
        metadata_json={"body_source": "extracted_html", "fetch_ok": True},
    )
    claim = _claim(
        text="El gobierno argentino no ha transparentado los gastos y la conformación de las comitivas en las giras de Milei.",
        evidence=[
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=excerpt_a,
                source_item=item_a,
                source_url=item_a.url,
            ),
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=excerpt_b,
                source_item=item_b,
                source_url=item_b.url,
            ),
        ],
    )
    assessment = assess_origins(claim)
    assert assessment.known_independent == 1
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE


def test_same_agency_wire_is_one_origin_despite_distinct_wording() -> None:
    body_a = (
        "Según Télam, se produjo un incendio en un depósito de Rosario durante la madrugada "
        "y los equipos de emergencia acudieron al lugar con varias dotaciones."
    )
    body_b = (
        "Télam informó que bomberos trabajan en un incendio registrado en un depósito de Rosario "
        "después de que el cable de la agencia describiera el foco en la zona sur."
    )
    claim = _claim(
        text="Se produjo un incendio en un depósito de Rosario",
        evidence=[
            _row(url="https://diario-a.test/n", excerpt=body_a, body=body_a, domain="diario-a.test"),
            _row(url="https://diario-b.test/n", excerpt=body_b, body=body_b, domain="diario-b.test"),
            _row(
                url="https://diario-c.test/n",
                excerpt=body_a.replace("Según Télam", "De acuerdo a lo informado por Télam"),
                body=body_a.replace("Según Télam", "De acuerdo a lo informado por Télam"),
                domain="diario-c.test",
            ),
        ],
    )
    assessment = assess_origins(claim)
    assert assessment.known_independent == 1
    assert all(item.startswith("wire:") for item in assessment.information_origins)
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE
    assert _reason_code(claim, assessment, status="SINGLE_SOURCE", desired="SUPPORTED") is ReasonCode.INDEPENDENCE_NOT_ESTABLISHED


def test_five_reprints_of_one_agency_do_not_become_supported() -> None:
    excerpt = (
        "la agencia telam informo que el incendio en el deposito de rosario comenzo de madrugada "
        "y que los bomberos controlaban el fuego en la zona industrial"
    )
    rows = [
        _row(
            url=f"https://copia{index}.test/n",
            excerpt=excerpt,
            body=excerpt + " fin del cable de la agencia.",
            domain=f"copia{index}.test",
        )
        for index in range(5)
    ]
    claim = _claim(text="Se produjo un incendio en un depósito de Rosario", evidence=rows)
    assessment = assess_origins(claim)
    assert assessment.known_independent <= 1
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE
    assert _reason_code(
        claim, assessment, status="SINGLE_SOURCE", desired="SUPPORTED"
    ) in {ReasonCode.SINGLE_KNOWN_ORIGIN, ReasonCode.INDEPENDENCE_NOT_ESTABLISHED}


def test_numeric_conflict_is_not_resolved_by_majority() -> None:
    body_a = "El choque dejó 2 fallecidos en el lugar según el recuento de esa redacción en Rosario."
    body_b = "El choque dejó 3 fallecidos en el lugar según el recuento propio de otra redacción en Rosario."
    claim = _claim(
        text="El choque dejó 2 fallecidos",
        evidence=[
            _row(url="https://a.test/n", excerpt=body_a, body=body_a, domain="a.test"),
            _row(
                url="https://b.test/n",
                excerpt=body_b,
                body=body_b,
                evidence_type=EvidenceType.CONTRADICTS,
                domain="b.test",
            ),
        ],
    )
    assert clamp_supported_status(claim, ClaimStatus.CONFLICTING) == ClaimStatus.CONFLICTING
    plan = heuristic_plan(claim)
    assert apply_primary_requirement(claim, ClaimStatus.CONFLICTING, plan, primary_supports=False) == ClaimStatus.CONFLICTING
    assert reason_code_for(status=ClaimStatus.CONFLICTING.value) is ReasonCode.CONFLICTING_COMPARABLE_EVIDENCE


def test_law_age_not_supported_by_newspapers() -> None:
    body = "Tres diarios afirman que la ley aplica desde los 14 años en todo el país según su lectura política."
    rows = [
        _row(url=f"https://medio{index}.test/ley", excerpt=body + f" nota {index}", body=body + f" desarrollo {index} distinto", domain=f"medio{index}.test")
        for index in range(3)
    ]
    claim = _claim(text="La ley aplica desde los 14 años", claim_type="documento", importance=ClaimImportance.HIGH, evidence=rows)
    plan = heuristic_plan(claim)
    assert plan.primary_source_required is True
    assert requires_authoritative_source(claim) is True
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE
    assert apply_primary_requirement(claim, ClaimStatus.SUPPORTED, plan, primary_supports=False) == ClaimStatus.SINGLE_SOURCE
    assessment = assess_origins(claim)
    assert _reason_code(
        claim,
        assessment,
        status="SINGLE_SOURCE",
        desired="SUPPORTED",
        primary_required=True,
        primary_supports=False,
    ) is ReasonCode.MISSING_DOCUMENTARY_PRIMARY


def test_utterance_does_not_support_underlying_economic_fact() -> None:
    said = (
        "Milei afirmó en conferencia que la deuda cayó 30 por ciento durante su gestión "
        "según el registro de esa cobertura periodística propia."
    )
    other = (
        "El presidente dijo en el acto que la deuda cayó 30 por ciento y la redacción transcribió "
        "esa declaración sin reproducir un cable de agencia."
    )
    utterance = _claim(
        text="Milei afirmó que la deuda cayó 30%",
        claim_type="declaracion",
        subject="Milei",
        predicate="afirmó",
        evidence=[
            _row(url="https://a.test/dijo", excerpt=said, body=said, domain="a.test"),
            _row(url="https://b.test/dijo", excerpt=other, body=other, domain="b.test"),
        ],
    )
    fact = _claim(
        text="La deuda cayó 30%",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        evidence=utterance.evidence,
    )
    assert clamp_supported_status(utterance, ClaimStatus.SUPPORTED) == ClaimStatus.SUPPORTED
    assert requires_authoritative_source(fact) is True
    assert clamp_supported_status(fact, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE


def test_accusation_existence_vs_guilt() -> None:
    existence_body_a = (
        "X acusó a Y de corrupción durante una conferencia de prensa en Tribunales "
        "según la cobertura propia de esa redacción."
    )
    existence_body_b = (
        "En un acto distinto la diputada X acusó a Y de corrupción y esa segunda redacción "
        "relató el cruce sin citar agencia."
    )
    existence = _claim(
        text="X acusó a Y de corrupción",
        evidence=[
            _row(url="https://a.test/acuso", excerpt=existence_body_a, body=existence_body_a, domain="a.test"),
            _row(url="https://b.test/acuso", excerpt=existence_body_b, body=existence_body_b, domain="b.test"),
        ],
    )
    guilt = _claim(
        text="Y cometió corrupción",
        importance=ClaimImportance.HIGH,
        evidence=existence.evidence,
    )
    assert requires_authoritative_source(existence) is False
    assert clamp_supported_status(existence, ClaimStatus.SUPPORTED) == ClaimStatus.SUPPORTED
    assert requires_authoritative_source(guilt) is True
    assert clamp_supported_status(guilt, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE


def test_official_document_is_primary_source_kind() -> None:
    body = "El Boletín Oficial publica el decreto que designa a la funcionaria en el cargo indicado."
    item = _item(
        url="https://www.boletinoficial.gob.ar/detalle/1",
        body=body,
        domain="boletinoficial.gob.ar",
    )
    claim = _claim(
        text="Natalia Laura Federman fue designada en 2011",
        claim_type="documento",
        evidence=[
            SimpleNamespace(
                evidence_type=EvidenceType.SUPPORTS,
                excerpt=body,
                source_item=item,
                source_url=item.url,
            )
        ],
    )
    plan = heuristic_plan(claim)
    status = apply_primary_requirement(claim, ClaimStatus.SUPPORTED, plan, primary_supports=True)
    assert status == ClaimStatus.SUPPORTED
    assessment = assess_origins(claim)
    kind = support_kind_for(status="SUPPORTED", assessment=assessment, primary_access="found_relevant")
    assert kind == SupportKind.PRIMARY_SOURCE


def test_independent_reporting_upgrades_to_primary_without_duplicating() -> None:
    body_a = "Bomberos combatieron un incendio en un depósito de Rosario con dotaciones propias de esa ciudad."
    body_b = "Otra redacción relató que el incendio en un depósito de Rosario fue controlado entrada la mañana."
    claim = _claim(
        text="Se produjo un incendio en un depósito de Rosario",
        evidence=[
            _row(url="https://a.test/n", excerpt=body_a, body=body_a, domain="a.test"),
            _row(url="https://b.test/n", excerpt=body_b, body=body_b, domain="b.test"),
        ],
    )
    first = support_kind_for(status="SUPPORTED", assessment=assess_origins(claim), primary_access="not_found")
    assert first == SupportKind.INDEPENDENT_REPORTING
    upgraded = support_kind_for(status="SUPPORTED", assessment=assess_origins(claim), primary_access="found_relevant")
    assert upgraded == SupportKind.PRIMARY_SOURCE


def test_authoritative_contradiction_beats_independent_reporting() -> None:
    plan = VerificationPlan(
        verification_target=VerificationTarget.OFFICIAL_STATISTICS,
        subject=VerificationSubject.STATISTICS,
        primary_source_required=True,
    )
    claim = _claim(text="El IPC de julio fue 2,1%", claim_type="cifra", importance=ClaimImportance.HIGH)
    assert apply_primary_requirement(claim, ClaimStatus.DISPROVEN, plan, primary_supports=True) == ClaimStatus.DISPROVEN
    assert apply_primary_requirement(claim, ClaimStatus.CONFLICTING, plan, primary_supports=False) == ClaimStatus.CONFLICTING


def test_sensitive_accusation_not_checked_from_independent_reporting() -> None:
    claim = _claim(
        text="Un funcionario es responsable de fraude en la obra pública",
        importance=ClaimImportance.HIGH,
        status=ClaimStatus.SUPPORTED,
    )
    view = _view(claim, kind=SupportKind.INDEPENDENT_REPORTING.value, primary=False, known=2)
    assert is_strong_verification(claim.id, view, claim=claim) is False
    assert is_checked(claim, view) is False


def test_material_figure_still_requires_primary() -> None:
    body_a = "El costo de la medida será de 400 millones de pesos según el recuento propio del diario A."
    body_b = "Otra redacción estimó que el costo de la medida alcanza 400 millones de pesos en su investigación."
    claim = _claim(
        text="El costo de la medida será de 400 millones de pesos",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
        evidence=[
            _row(url="https://a.test/costo", excerpt=body_a, body=body_a, domain="a.test"),
            _row(url="https://b.test/costo", excerpt=body_b, body=body_b, domain="b.test"),
        ],
    )
    assert requires_authoritative_source(claim) is True
    assert heuristic_plan(claim).primary_source_required is True
    assert clamp_supported_status(claim, ClaimStatus.SUPPORTED) == ClaimStatus.SINGLE_SOURCE


def test_editorial_fixture_propositions_keep_authoritative_ceilings() -> None:
    designation = _claim(
        text="Natalia Laura Federman fue designada Directora Nacional de Derechos Humanos en 2011",
        claim_type="documento",
        importance=ClaimImportance.HIGH,
    )
    treason = _claim(
        text="Cristina Fernández de Kirchner cometió traición a la patria",
        importance=ClaimImportance.HIGH,
    )
    tariff = _claim(
        text="Las facturas de electricidad aumentarán 1,75%",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
    )
    ruling = _claim(
        text="La Suprema Corte de Mendoza sobreseyó a Hugo Auradou y Oscar Jegou",
        importance=ClaimImportance.HIGH,
    )
    normas = _claim(
        text="El Gobierno de Milei eliminó unas 17.000 normas",
        claim_type="cifra",
        importance=ClaimImportance.HIGH,
    )
    for claim in (designation, treason, tariff, ruling, normas):
        assert requires_authoritative_source(claim) is True
        assert heuristic_plan(claim).primary_source_required is True
    filing = _claim(
        text="Víctor Eduardo Vital presentó una denuncia penal contra Natalia Laura Federman",
        importance=ClaimImportance.HIGH,
    )
    assert requires_authoritative_source(filing) is False
    assert heuristic_plan(filing).primary_source_required is False
    assert heuristic_plan(filing).verification_target == VerificationTarget.JUDICIAL_RECORD
