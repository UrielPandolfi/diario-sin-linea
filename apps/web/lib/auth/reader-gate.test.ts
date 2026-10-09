import assert from "node:assert/strict";
import { test } from "node:test";

import { readerCookieExpiry, readerGateAction, signedReaderState } from "./reader-gate";

test("a signed cookie for a missing reader is rejected", () => {
  assert.equal(signedReaderState(false, false), "missing");
  assert.equal(signedReaderState(true, true), "accepted");
  assert.equal(signedReaderState(true, false), "rejected");
  assert.equal(signedReaderState(true, null), "unchecked");
});

test("a rejected reader cookie opens login and does not bounce back home", () => {
  assert.equal(readerGateAction("/", "rejected"), "clear-login");
  assert.equal(readerGateAction("/perfil", "rejected"), "clear-login");
  assert.equal(readerGateAction("/entrar", "rejected"), "clear-stay");
  assert.equal(readerGateAction("/registro", "rejected"), "clear-stay");
  assert.equal(readerGateAction("/noticias/nota", "rejected"), "clear-pass");
});

test("a live or unchecked cookie keeps the current gates", () => {
  assert.equal(readerGateAction("/", "accepted"), "pass");
  assert.equal(readerGateAction("/entrar", "accepted"), "show-app");
  assert.equal(readerGateAction("/entrar", "unchecked"), "show-app");
  assert.equal(readerGateAction("/", "missing"), "show-login");
  assert.equal(readerGateAction("/noticias/nota", "missing"), "pass");
});

test("cookie expiry covers secure and plain sessions", () => {
  const [plain, secure] = readerCookieExpiry();
  assert.match(plain, /^sl_reader=; Path=\/; Max-Age=0; HttpOnly; SameSite=Lax$/);
  assert.match(secure, /^sl_reader=; Path=\/; Max-Age=0; HttpOnly; SameSite=Lax; Secure$/);
});
