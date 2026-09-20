import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { ReactNode } from "react";

import { ArticleBody } from "./article-body";
import { ClaimEvidenceList } from "./claim-evidence-panel";
import { ARTICLE_FIXTURE_BLOCKS, FIXTURE_CLAIMS } from "./claim-evidence-fixtures";
import { MISSING_PRESENTATION_EXPLANATION, MISSING_PRESENTATION_HEADING } from "./claim-popover-copy";

const claims = Object.values(FIXTURE_CLAIMS);

function env() {
  return (globalThis as { setEvidenceEnv?: (options: { hoverFine?: boolean; width?: number }) => void }).setEvidenceEnv;
}

let root: Root | null = null;
let host: HTMLDivElement | null = null;

async function render(node: ReactNode) {
  host ??= document.createElement("div");
  document.body.append(host);
  root ??= createRoot(host);
  await act(async () => {
    root!.render(node);
  });
  await act(async () => {
    await Promise.resolve();
  });
  return host;
}

async function cleanup() {
  if (root) {
    await act(async () => {
      root!.unmount();
    });
  }
  root = null;
  host?.remove();
  host = null;
  document.body.style.overflow = "";
  for (const leftover of document.querySelectorAll("[data-evidence-surface]")) leftover.remove();
}

afterEach(cleanup);

function triggerByKey(key: string) {
  const match = document.querySelector<HTMLButtonElement>(`button[data-claim-segment="${key}"]`);
  assert.ok(match, `missing trigger ${key}`);
  return match;
}

function surfaceNode(kind?: "popover" | "sheet") {
  return kind
    ? document.querySelector(`[data-evidence-surface='${kind}']`)
    : document.querySelector("[data-evidence-surface]");
}

async function fire(target: EventTarget, type: string, init?: MouseEventInit | KeyboardEventInit | PointerEventInit) {
  await act(async () => {
    if (type === "mouseenter" || type === "mouseover") {
      const related = (init as MouseEventInit | undefined)?.relatedTarget ?? document.body;
      target.dispatchEvent(new MouseEvent("mouseover", { bubbles: true, cancelable: true, relatedTarget: related, ...init }));
      target.dispatchEvent(new MouseEvent("mouseenter", { bubbles: false, cancelable: true, relatedTarget: related, ...init }));
      return;
    }
    if (type === "mouseleave" || type === "mouseout") {
      target.dispatchEvent(new MouseEvent("mouseout", { bubbles: true, cancelable: true, ...init }));
      target.dispatchEvent(new MouseEvent("mouseleave", { bubbles: false, cancelable: true, ...init }));
      return;
    }
    if (type === "focus" || type === "focusin") {
      if (target instanceof HTMLElement) target.focus();
      target.dispatchEvent(new FocusEvent("focusin", { bubbles: true, cancelable: true, ...init }));
      target.dispatchEvent(new FocusEvent("focus", { bubbles: false, cancelable: true, ...init }));
      return;
    }
    if (type.startsWith("key")) {
      target.dispatchEvent(new KeyboardEvent(type, { bubbles: true, cancelable: true, ...init }));
      return;
    }
    if (type.startsWith("pointer")) {
      target.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, ...init }));
      return;
    }
    target.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true, ...init }));
  });
}

test("panel copy matches C9 families and ignores status, demotion and reason_code", async () => {
  await render(<ClaimEvidenceList claims={[FIXTURE_CLAIMS.confirmed, FIXTURE_CLAIMS.limited, FIXTURE_CLAIMS.disputed]} />);
  const text = document.body.textContent ?? "";
  assert.match(text, /Confirmado/);
  assert.match(text, /corroboración independiente/);
  assert.match(text, /Respaldo limitado/);
  assert.match(text, /En disputa/);
  assert.doesNotMatch(text, /SINGLE_SOURCE|SUPPORTED|insufficient_independence|SINGLE_KNOWN_ORIGIN|Chequeado/);
});

test("declaration, contradiction and missing evaluation keep distinct copy", async () => {
  await render(
    <ClaimEvidenceList claims={[FIXTURE_CLAIMS.utterance, FIXTURE_CLAIMS.disproven, FIXTURE_CLAIMS.unevaluated]} />,
  );
  const text = document.body.textContent ?? "";
  assert.match(text, /Declaración confirmada/);
  assert.match(text, /no comprueba el contenido/);
  assert.match(text, /Contradicho/);
  assert.match(text, /Sin evaluación disponible/);
});

test("missing presentation is neutral and does not invent a verdict", async () => {
  await render(<ClaimEvidenceList claims={[FIXTURE_CLAIMS.missing]} />);
  const text = document.body.textContent ?? "";
  assert.match(text, new RegExp(MISSING_PRESENTATION_HEADING));
  assert.match(text, new RegExp(MISSING_PRESENTATION_EXPLANATION));
  assert.doesNotMatch(text, /Confirmado|pendiente|fallid|falso/i);
});

test("desktop hover, click, link and escape keep a single popover", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  assert.equal(document.querySelector("[data-evidence-mode]")?.getAttribute("data-evidence-mode"), "popover");
  const button = triggerByKey("0-1");
  await fire(button, "mouseenter");
  const popover = surfaceNode("popover");
  assert.ok(popover);
  assert.match(popover?.textContent ?? "", /Confirmado/);
  const link = popover?.querySelector("a[href]") as HTMLAnchorElement | null;
  assert.ok(link);
  await fire(popover as EventTarget, "mouseenter");
  await fire(link, "mouseenter");
  assert.ok(surfaceNode("popover"));
  await fire(button, "click");
  assert.ok(surfaceNode("popover"));
  assert.equal(document.querySelectorAll("[data-evidence-surface]").length, 1);
  await fire(window, "keydown", { key: "Escape" });
  assert.equal(surfaceNode(), null);
});

test("keyboard enter pins the popover and does not double-toggle", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  const button = triggerByKey("0-1");
  await fire(button, "focus");
  assert.ok(surfaceNode("popover"));
  await fire(button, "keydown", { key: "Enter" });
  assert.ok(surfaceNode("popover"));
  await fire(button, "keydown", { key: "Enter" });
  assert.equal(surfaceNode(), null);
  assert.equal(document.activeElement, button);
});

test("keyboard tab moves into the popover and space does not double-toggle", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  const button = triggerByKey("0-1");
  await fire(button, "focus");
  await fire(button, "keydown", { key: " " });
  const popover = surfaceNode("popover");
  assert.ok(popover);
  await fire(button, "keydown", { key: "Tab" });
  assert.ok(popover?.contains(document.activeElement));
  assert.notEqual(document.activeElement, button);
  await fire(button, "keydown", { key: " " });
  assert.equal(surfaceNode(), null);
});

test("outside pointerdown closes the popover without crashing", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  const button = triggerByKey("0-1");
  await fire(button, "click");
  assert.ok(surfaceNode("popover"));
  await fire(document.body, "pointerdown");
  assert.equal(surfaceNode(), null);
});

test("mobile sheet is modal, labelled, traps background scroll and restores it", async () => {
  env()?.({ hoverFine: false, width: 390 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  assert.equal(document.querySelector("[data-evidence-mode]")?.getAttribute("data-evidence-mode"), "sheet");
  const button = triggerByKey("0-1");
  await fire(button, "click");
  const sheet = surfaceNode("sheet");
  const dialog = document.querySelector("[role='dialog'][aria-modal='true']");
  assert.ok(sheet);
  assert.ok(dialog);
  const labelledBy = dialog?.getAttribute("aria-labelledby");
  assert.ok(labelledBy);
  assert.equal(document.getElementById(labelledBy)?.textContent, "Respaldo de la afirmación");
  assert.equal(document.body.style.overflow, "hidden");
  const close = document.querySelector("[aria-label='Cerrar']") as HTMLButtonElement | null;
  assert.ok(close);
  await fire(close, "click");
  assert.equal(surfaceNode(), null);
  assert.equal(document.body.style.overflow, "");
});

test("several claims in one fragment keep separate copy", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  const button = triggerByKey("2-0");
  await fire(button, "click");
  const text = surfaceNode()?.textContent ?? "";
  assert.match(text, /Confirmado/);
  assert.match(text, /Respaldo limitado/);
  assert.match(text, /incendio/);
  assert.match(text, /denuncia penal/);
  assert.match(text, /Afirmaciones de este pasaje|Respaldo de las afirmaciones/);
});

test("documents disclosure keeps counts out of the label and lists unknown vs empty", async () => {
  await render(<ClaimEvidenceList claims={[FIXTURE_CLAIMS.limited, FIXTURE_CLAIMS.unevaluated]} />);
  const summaries = Array.from(document.querySelectorAll("summary"));
  assert.equal(
    summaries.every((summary) => /Ver documentos/.test(summary.textContent ?? "")),
    true,
  );
  assert.equal(
    summaries.some((summary) => /3 documentos/.test(summary.textContent ?? "")),
    false,
  );
  await act(async () => {
    for (const summary of summaries) {
      const details = summary.parentElement;
      if (details instanceof HTMLDetailsElement) details.open = true;
    }
  });
  const text = document.body.textContent ?? "";
  assert.match(text, /Ver documentos/);
  assert.match(text, /Se consultaron 3 documentos/);
  assert.match(text, /No hay un desglose documental utilizable/);
  assert.doesNotMatch(text, /3 fuentes = confirmado/i);
});

test("unresolved claim ids stay plain text", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  assert.equal(
    Array.from(document.querySelectorAll("button[data-claim-segment]")).some((button) =>
      (button.textContent ?? "").includes("texto sin claim resoluble"),
    ),
    false,
  );
  assert.match(document.body.textContent ?? "", /texto sin claim resoluble/);
});

test("opening evidence does not call fetch", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  let fetchCalls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = (async () => {
    fetchCalls += 1;
    return new Response("{}");
  }) as typeof fetch;
  try {
    await render(
      <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
    );
    await fire(triggerByKey("0-1"), "click");
    assert.equal(fetchCalls, 0);
  } finally {
    globalThis.fetch = original;
  }
});

test("article text and surrounding copy stay intact", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  const text = document.body.textContent ?? "";
  assert.match(text, /Según las pericias,/);
  assert.match(text, /hubo un incendio en el depósito de Rosario/);
  assert.match(text, /Pérez afirmó que el costo será de 40.000 millones/);
  const incendio = triggerByKey("0-1");
  assert.equal(incendio.tagName, "BUTTON");
  assert.match(incendio.className, /underline/);
  assert.match(incendio.className, /dotted/);
  assert.equal(
    triggerByKey("2-0").getAttribute("aria-label"),
    "Un mismo pasaje cubre dos afirmaciones: incendio y denuncia. Consultar respaldo",
  );
});

test("changing sourceKey closes the overlay and does not mix versions", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="slug:1" />,
  );
  await fire(triggerByKey("0-1"), "click");
  assert.ok(surfaceNode());
  assert.match(surfaceNode()?.textContent ?? "", /Confirmado/);
  await render(
    <ArticleBody
      body=""
      bodyBlocks={[
        {
          type: "paragraph",
          segments: [{ text: "Pérez afirmó que el costo será de 40.000 millones", claim_ids: ["utterance"] }],
        },
      ]}
      claims={[FIXTURE_CLAIMS.utterance]}
      sourceKey="slug:2"
    />,
  );
  assert.equal(surfaceNode(), null);
  assert.doesNotMatch(document.body.textContent ?? "", /hubo un incendio en el depósito de Rosario/);
  assert.match(document.body.textContent ?? "", /Pérez afirmó/);
  await fire(triggerByKey("0-0"), "click");
  assert.match(surfaceNode()?.textContent ?? "", /Declaración confirmada/);
  assert.doesNotMatch(surfaceNode()?.textContent ?? "", /Hubo un incendio/);
});

test("disappearing selected claim removes the overlay without inventing copy", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  await fire(triggerByKey("0-1"), "click");
  assert.ok(surfaceNode());
  await render(
    <ArticleBody
      body=""
      bodyBlocks={ARTICLE_FIXTURE_BLOCKS}
      claims={[FIXTURE_CLAIMS.utterance]}
      sourceKey="fixture:1"
    />,
  );
  assert.equal(surfaceNode(), null);
  assert.match(document.body.textContent ?? "", /hubo un incendio en el depósito de Rosario/);
  assert.equal(document.querySelector("button[data-claim-segment='0-1']"), null);
});

test("viewport mode change closes the overlay and does not leave two surfaces", async () => {
  env()?.({ hoverFine: true, width: 1280 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  await fire(triggerByKey("0-1"), "click");
  assert.ok(surfaceNode("popover"));
  await act(async () => {
    env()?.({ hoverFine: false, width: 390 });
  });
  assert.equal(surfaceNode(), null);
  assert.equal(document.querySelector("[data-evidence-mode]")?.getAttribute("data-evidence-mode"), "sheet");
  await fire(triggerByKey("0-1"), "click");
  assert.ok(surfaceNode("sheet"));
  assert.equal(document.querySelectorAll("[data-evidence-surface]").length, 1);
});

test("unmount restores overflow and removes the overlay", async () => {
  env()?.({ hoverFine: false, width: 390 });
  await render(
    <ArticleBody body="" bodyBlocks={ARTICLE_FIXTURE_BLOCKS} claims={claims} sourceKey="fixture:1" />,
  );
  await fire(triggerByKey("0-1"), "click");
  assert.equal(document.body.style.overflow, "hidden");
  await cleanup();
  assert.equal(surfaceNode(), null);
  assert.equal(document.body.style.overflow, "");
});
