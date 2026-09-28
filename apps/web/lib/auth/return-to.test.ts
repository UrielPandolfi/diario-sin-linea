import assert from "node:assert/strict";
import { test } from "node:test";

import { loginPath, registerPath, safeReturnTo } from "./return-to";

test("internal article and home destinations are kept", () => {
  assert.equal(safeReturnTo("/noticias/colectivo-pellegrini"), "/noticias/colectivo-pellegrini");
  assert.equal(safeReturnTo("/?vista=local"), "/?vista=local");
  assert.equal(safeReturnTo("/noticias/nota?x=1#fuentes"), "/noticias/nota?x=1#fuentes");
  assert.equal(loginPath("/noticias/nota"), "/entrar?next=%2Fnoticias%2Fnota");
  assert.equal(registerPath("/noticias/nota"), "/registro?next=%2Fnoticias%2Fnota");
});

test("external and looping destinations fall back to the feed", () => {
  for (const value of [
    "https://evil.example/phish",
    "http://evil.example",
    "//evil.example",
    "/\\evil.example",
    "\\\\evil.example",
    "javascript:alert(1)",
    "/entrar",
    "/entrar?next=/",
    "/registro",
    "/registro/extra",
    " /noticias/nota",
    "",
    null,
    undefined,
  ]) {
    assert.equal(safeReturnTo(value), "/", String(value));
  }
  assert.equal(loginPath("https://evil.example"), "/entrar?next=%2F");
});
