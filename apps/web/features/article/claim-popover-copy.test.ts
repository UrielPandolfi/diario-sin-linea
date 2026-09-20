import assert from "node:assert/strict";
import { test } from "node:test";

import type { ArticleClaim } from "../../lib/api/types";
import { claimPopoverCopy } from "./claim-popover-copy";

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
  assert.equal(copy.heading, "Respaldo limitado");
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
