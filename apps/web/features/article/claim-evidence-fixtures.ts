import type { ArticleClaim, ClaimCardPresentation } from "../../lib/api/types";

function presentation(overrides: Partial<ClaimCardPresentation>): ClaimCardPresentation {
  return {
    verification_label: "Confirmado",
    limitation: null,
    coverage: "Se consultaron 2 documentos; 2 documentos respaldan la proposición. 2 procedencias independientes conocidas figuran en el contrato.",
    explanation: "La proposición completa quedó respaldada por corroboración independiente.",
    evidence_detail: [
      { evidence_type: "SUPPORTS", stance: "respalda", name: "Diario A", url: "https://a.test/1" },
      { evidence_type: "SUPPORTS", stance: "respalda", name: "Diario B", url: "https://b.test/2" },
    ],
    basis_known: true,
    documents_consulted: 2,
    documents_supporting: 2,
    known_independent_count: 2,
    unknown_group_count: 0,
    presentation_kind: "confirmed",
    ...overrides,
  };
}

function claim(overrides: Partial<ArticleClaim> & { id: string; canonical_text: string }): ArticleClaim {
  return {
    status: "SUPPORTED",
    importance: "HIGH",
    source_count: 2,
    evidence_count: 2,
    verification: null,
    ...overrides,
  };
}

export const FIXTURE_CLAIMS: Record<string, ArticleClaim> = {
  confirmed: claim({
    id: "confirmed",
    canonical_text: "Hubo un incendio en el depósito de Rosario",
    presentation: presentation({}),
  }),
  utterance: claim({
    id: "utterance",
    canonical_text: "Pérez afirmó que el costo será de 40.000 millones",
    status: "SUPPORTED",
    presentation: presentation({
      presentation_kind: "confirmed_utterance",
      verification_label: "Declaración confirmada",
      explanation:
        "Se acreditó que Pérez hizo esta declaración: «Pérez afirmó que el costo será de 40.000 millones». Eso no comprueba el contenido de lo dicho ni una reacción adicional.",
      coverage: "Se consultaron 2 documentos; 2 documentos respaldan la proposición.",
      known_independent_count: 2,
    }),
  }),
  limited: claim({
    id: "limited",
    canonical_text: "Vital presentó una denuncia penal",
    status: "SINGLE_SOURCE",
    reason_code: "SINGLE_KNOWN_ORIGIN",
    presentation: presentation({
      presentation_kind: "limited_support",
      verification_label: "Respaldo limitado",
      explanation:
        "Hay respaldo admitido, pero una restricción de procedencia impide presentar la proposición completa como confirmada. Varios documentos no equivalen a corroboración independiente.",
      coverage: "Se consultaron 3 documentos; 3 documentos respaldan la proposición.",
      documents_consulted: 3,
      documents_supporting: 3,
      known_independent_count: 1,
      demotion: "insufficient_independence",
      evidence_detail: [
        { evidence_type: "SUPPORTS", stance: "respalda", name: "Medio", url: "https://medio.test/1" },
        { evidence_type: "SUPPORTS", stance: "respalda", name: "Copia", url: "https://copia.test/1" },
        { evidence_type: "SUPPORTS", stance: "respalda", name: "Otra copia", url: "https://copia.test/2" },
      ],
    }),
  }),
  disputed: claim({
    id: "disputed",
    canonical_text: "El índice subió 4%",
    status: "CONFLICTING",
    presentation: presentation({
      presentation_kind: "disputed",
      verification_label: "En disputa",
      explanation: "Hay versiones comparables y opuestas sobre esta proposición. No se toma una como confirmada.",
      coverage: "Se consultaron 2 documentos; 1 documento respalda la proposición.",
      documents_supporting: 1,
      known_independent_count: 1,
      evidence_detail: [
        { evidence_type: "SUPPORTS", stance: "respalda", name: "Fuente A", url: "https://a.test/i" },
        { evidence_type: "CONTRADICTS", stance: "contradice", name: "Fuente B", url: "https://b.test/i" },
      ],
    }),
  }),
  disproven: claim({
    id: "disproven",
    canonical_text: "El puente quedó destruido",
    status: "DISPROVEN",
    presentation: presentation({
      presentation_kind: "disproven",
      verification_label: "Contradicho",
      explanation: "La evidencia comparable desmiente esta proposición. Eso no atribuye mentira ni intención de engañar.",
      coverage: "Se consultaron 2 documentos; ninguno respalda la proposición.",
      documents_supporting: 0,
      evidence_detail: [
        { evidence_type: "CONTRADICTS", stance: "contradice", name: "Parte oficial", url: "https://oficial.test/p" },
      ],
    }),
  }),
  unevaluated: claim({
    id: "unevaluated",
    canonical_text: "El expediente ya tiene fecha de audiencia",
    status: "SINGLE_SOURCE",
    presentation: presentation({
      presentation_kind: "unevaluated",
      verification_label: "Sin evaluación disponible",
      explanation: "No hay información suficiente sobre la evaluación de esta afirmación en esta versión.",
      coverage: "No hay un desglose documental utilizable para esta versión.",
      evidence_detail: [],
      basis_known: false,
      documents_consulted: null,
      documents_supporting: null,
      known_independent_count: null,
    }),
  }),
  missing: claim({
    id: "missing",
    canonical_text: "Afirmación sin tarjeta",
    status: "SUPPORTED",
    presentation: undefined,
  }),
  partial: claim({
    id: "partial",
    canonical_text: "El decreto elimina el régimen y entra en vigencia mañana",
    status: "SINGLE_SOURCE",
    verified_scope: "El decreto elimina el régimen",
    unsupported_scope: null,
    presentation: presentation({
      presentation_kind: "limited_support",
      verification_label: "Respaldo limitado",
      explanation:
        "El respaldo alcanza solo a esta parte: «El decreto elimina el régimen». El resto del compuesto no está identificado y no se da por falso.",
      coverage: "Se consultó 1 documento; 1 documento respalda la proposición.",
      documents_consulted: 1,
      documents_supporting: 0,
      known_independent_count: 1,
      evidence_detail: [{ evidence_type: "QUALIFIES", stance: "matiza", name: "Boletín", url: "https://boletinoficial.gob.ar/x" }],
      limitation: "El documento oficial consultado no sostiene esta proposición.",
    }),
  }),
};

export const ARTICLE_FIXTURE_BLOCKS = [
  {
    type: "paragraph" as const,
    segments: [
      { text: "Según las pericias, ", claim_ids: [] },
      { text: "hubo un incendio en el depósito de Rosario", claim_ids: ["confirmed"] },
      { text: ". ", claim_ids: [] },
      { text: "Pérez afirmó que el costo será de 40.000 millones", claim_ids: ["utterance"] },
      { text: ".", claim_ids: [] },
    ],
  },
  {
    type: "paragraph" as const,
    segments: [
      { text: "Vital presentó una denuncia penal", claim_ids: ["limited"] },
      { text: ", aunque otras versiones dicen que ", claim_ids: [] },
      { text: "el índice subió 4%", claim_ids: ["disputed"] },
      { text: ".", claim_ids: [] },
    ],
  },
  {
    type: "paragraph" as const,
    segments: [
      { text: "Un mismo pasaje cubre dos afirmaciones: incendio y denuncia.", claim_ids: ["confirmed", "limited"] },
    ],
  },
  {
    type: "paragraph" as const,
    segments: [
      { text: "El puente quedó destruido", claim_ids: ["disproven"] },
      { text: " y ", claim_ids: [] },
      { text: "el expediente ya tiene fecha de audiencia", claim_ids: ["unevaluated"] },
      { text: ". Referencia huérfana: ", claim_ids: [] },
      { text: "texto sin claim resoluble", claim_ids: ["ghost"] },
      { text: ". ", claim_ids: [] },
      { text: "Afirmación sin tarjeta", claim_ids: ["missing"] },
      { text: ".", claim_ids: [] },
    ],
  },
];
