import assert from "node:assert/strict";
import { test } from "node:test";

import { isAuthEntryPath, isPrivateAppPath } from "./paths";

test("home and personal areas require a session", () => {
  assert.equal(isPrivateAppPath("/"), true);
  assert.equal(isPrivateAppPath("/perfil"), true);
  assert.equal(isPrivateAppPath("/perfil/cuenta"), true);
  assert.equal(isPrivateAppPath("/guardados"), true);
  assert.equal(isPrivateAppPath("/seguidos"), true);
  assert.equal(isPrivateAppPath("/notificaciones"), true);
});

test("public sections stay outside the home gate", () => {
  for (const path of [
    "/noticias/colectivo-pellegrini",
    "/buscar",
    "/local",
    "/en-vivo",
    "/contacto",
    "/seguimiento/abc",
    "/como-funciona",
    "/onboarding",
    "/entrar",
    "/registro",
    "/admin",
    "/api/v1/articles/colectivo",
    "/api/v1/auth/login",
  ]) {
    assert.equal(isPrivateAppPath(path), false, path);
  }
  assert.equal(isAuthEntryPath("/entrar"), true);
  assert.equal(isAuthEntryPath("/registro"), true);
  assert.equal(isAuthEntryPath("/entrada"), false);
  assert.equal(isPrivateAppPath("/perfiles"), false);
});
