import assert from "node:assert/strict";
import { test } from "node:test";

import type { ArticleClaim } from "../../lib/api/types";
import {
  EMPTY_DOCUMENTS,
  MISSING_PRESENTATION_EXPLANATION,
  MISSING_PRESENTATION_HEADING,
  claimEvidenceCopy,
  claimPopoverCopy,
  documentsAvailability,
  EVIDENCE_SIDE_MIN_WIDTH,
  HOVER_CLOSE_MS,
  HOVER_OPEN_MS,
  evidenceSurface,
  hoverBridgeRect,
  placePopover,
  placeSidePopover,
} from "./claim-popover-copy";
import { FIXTURE_CLAIMS } from "./claim-evidence-fixtures";

function claim(overrides: Partial<ArticleClaim> & { presentation?: ArticleClaim["presentation"] }): ArticleClaim {
  return {
    id: "c1",
    canonical_text: "La afirmación",
    status: "SINGLE_SOURCE",
    importance: "HIGH",
    source_count: 3,
    evidence_count: 3,
    verification: null,
    ...overrides,
  };
}

test("consume backend copy without inferring certainty from status or document counts", () => {
  const copy = claimPopoverCopy(
    claim({
      status: "SUPPORTED",
      source_count: 3,
      evidence_count: 3,
      presentation: {
        presentation_kind: "limited_support",
        verification_label: "Respaldo limitado",
        limitation: null,
        coverage: "Se consultaron 3 documentos; 3 documentos respaldan la proposición.",
        explanation: "Hay respaldo admitido, pero una restricción de procedencia impide presentar la proposición completa como confirmada.",
        evidence_detail: [],
        basis_known: true,
        documents_consulted: 3,
        documents_supporting: 3,
        known_independent_count: 1,
        unknown_group_count: 0,
      },
    }),
  );
  assert.equal(copy.heading, "Respaldo limitado");
  assert.match(copy.explanation ?? "", /restricción de procedencia/);
  assert.notEqual(copy.heading, "Confirmado");
});

test("tolerates missing presentation_kind and missing counts", () => {
  const copy = claimPopoverCopy(
    claim({
      presentation: {
        verification_label: "Sin evaluación disponible",
        limitation: null,
        coverage: "No hay un desglose documental utilizable para esta versión.",
        explanation: "No hay información suficiente sobre la evaluación de esta afirmación en esta versión.",
        evidence_detail: [],
        basis_known: false,
        documents_consulted: null,
        known_independent_count: null,
        unknown_group_count: null,
      },
    }),
  );
  assert.equal(copy.heading, "Sin evaluación disponible");
  assert.match(copy.explanation ?? "", /información suficiente/);
});

test("does not fall back to status or demotion when presentation copy is present", () => {
  const copy = claimPopoverCopy(
    claim({
      status: "DISPROVEN",
      presentation: {
        verification_label: "No confirmado",
        limitation: null,
        coverage: "Se consultó 1 documento; ninguno respalda la proposición.",
        explanation: "La evaluación no permite confirmar esta proposición. Eso no equivale a desmentirla.",
        evidence_detail: [],
        basis_known: true,
        documents_consulted: 1,
        documents_supporting: 0,
        known_independent_count: 0,
        unknown_group_count: 0,
        demotion: "unproven_independence",
      },
    }),
  );
  assert.equal(copy.heading, "No confirmado");
  assert.notEqual(copy.heading, "Contradicho");
  assert.doesNotMatch(copy.explanation ?? "", /unproven_independence|demotion|DISPROVEN/i);
});

test("missing presentation uses a neutral fallback, not a C9 evaluation family", () => {
  const copy = claimEvidenceCopy(claim({ presentation: undefined, status: "SUPPORTED" }));
  assert.equal(copy.heading, MISSING_PRESENTATION_HEADING);
  assert.equal(copy.explanation, MISSING_PRESENTATION_EXPLANATION);
  assert.notEqual(copy.heading, "Confirmado");
  assert.notEqual(copy.heading, "Sin evaluación disponible");
  assert.equal(copy.kind, null);
});

const FAMILY_CASES: Array<[string, string, string]> = [
  ["confirmed", "Confirmado", "corroboración independiente"],
  ["utterance", "Declaración confirmada", "no comprueba el contenido"],
  ["limited", "Respaldo limitado", "restricción de procedencia"],
  ["disputed", "En disputa", "versiones comparables"],
  ["disproven", "Contradicho", "no atribuye mentira"],
  ["unevaluated", "Sin evaluación disponible", "información suficiente"],
];

for (const [id, heading, snippet] of FAMILY_CASES) {
  test(`C9 family ${id} keeps backend copy`, () => {
    const copy = claimEvidenceCopy(FIXTURE_CLAIMS[id]);
    assert.equal(copy.heading, heading);
    assert.match(copy.explanation ?? "", new RegExp(snippet, "i"));
    assert.equal(copy.kind, FIXTURE_CLAIMS[id].presentation?.presentation_kind ?? null);
  });
}

test("unknown counts stay distinct from an empty document list", () => {
  const unknown = claimEvidenceCopy(FIXTURE_CLAIMS.unevaluated);
  assert.equal(documentsAvailability(unknown), "unknown");
  assert.equal(unknown.documentsConsulted, null);
  const empty = claimEvidenceCopy(
    claim({
      presentation: {
        verification_label: "No confirmado",
        limitation: null,
        coverage: "No hay documentos contabilizados en esta verificación.",
        explanation: "La evaluación no permite confirmar esta proposición. Eso no equivale a desmentirla.",
        evidence_detail: [],
        basis_known: true,
        documents_consulted: 0,
        documents_supporting: 0,
        known_independent_count: 0,
        unknown_group_count: 0,
        presentation_kind: "not_confirmed",
      },
    }),
  );
  assert.equal(documentsAvailability(empty), "empty");
  assert.equal(EMPTY_DOCUMENTS.includes("documentos listados"), true);
});

test("identified scopes are exposed without inventing the missing side", () => {
  const copy = claimEvidenceCopy(FIXTURE_CLAIMS.partial);
  assert.equal(copy.verifiedScope, "El decreto elimina el régimen");
  assert.equal(copy.unsupportedScope, null);
});

test("evidence surface uses hover and width, not user-agent strings", () => {
  assert.equal(evidenceSurface({ hoverFine: true, viewportWidth: 1280 }), "popover");
  assert.equal(evidenceSurface({ hoverFine: true, viewportWidth: 390 }), "sheet");
  assert.equal(evidenceSurface({ hoverFine: true, viewportWidth: 768 }), "sheet");
  assert.equal(evidenceSurface({ hoverFine: false, viewportWidth: 1280 }), "sheet");
  assert.ok(EVIDENCE_SIDE_MIN_WIDTH >= 1200);
});

test("hover delays stay inside the requested band", () => {
  assert.ok(HOVER_OPEN_MS >= 150 && HOVER_OPEN_MS <= 250);
  assert.ok(HOVER_CLOSE_MS >= 180 && HOVER_CLOSE_MS <= 320);
});

test("popover placement stays inside the viewport", () => {
  const placed = placePopover(
    { top: 700, left: 1100, bottom: 720, right: 1200 },
    { width: 320, height: 240 },
    { width: 1280, height: 800 },
  );
  assert.ok(placed.left + 320 <= 1280 - 16);
  assert.ok(placed.top >= 16);
  assert.ok(placed.top + 240 <= 800 || placed.top < 700);
});

test("side popover anchors to the reserved column and keeps an arrow on the trigger", () => {
  const placed = placeSidePopover(
    { top: 120, left: 200, bottom: 160, right: 520, height: 40 },
    { width: 360, height: 280 },
    { width: 1440, height: 900 },
    { left: 760, width: 360 },
  );
  assert.equal(placed.left, 760);
  assert.ok(placed.top >= 16);
  assert.ok(placed.top + 280 <= 900 - 16);
  assert.ok(placed.arrow >= 22);
});

test("hover bridge covers the gap between trigger and panel", () => {
  const bridge = hoverBridgeRect(
    { top: 100, left: 40, bottom: 140, right: 400 },
    { top: 80, left: 440, bottom: 360, right: 800 },
  );
  assert.ok(bridge);
  assert.equal(bridge?.left, 400);
  assert.equal(bridge?.width, 40);
  assert.ok((bridge?.height ?? 0) >= 40);
});
