import assert from "node:assert/strict";
import { test } from "node:test";

import { REJECTED_DRAFT_WARNING, publishedArticlePath } from "./copy";

test("rejected draft warning names the status in words", () => {
  assert.match(REJECTED_DRAFT_WARNING, /^Borrador no aprobado\./);
  assert.match(REJECTED_DRAFT_WARNING, /No forma parte de las noticias publicadas/);
  assert.equal(REJECTED_DRAFT_WARNING.includes("Próximamente"), false);
});

test("published link stays on a news path", () => {
  assert.equal(publishedArticlePath("/noticias/puente-publicado"), "/noticias/puente-publicado");
  assert.equal(publishedArticlePath("https://evil.test/noticias/x"), null);
  assert.equal(publishedArticlePath("/transparencia/borradores/1"), null);
  assert.equal(publishedArticlePath(null), null);
});
