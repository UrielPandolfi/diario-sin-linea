import assert from "node:assert/strict";
import { test } from "node:test";

import { isAuthEntryPath, isPrivateAppPath } from "./paths";

test("home and personal areas require a session", () => {
  assert.equal(isPrivateAppPath("/"), true);
  assert.equal(isPrivateAppPath("/perfil"), true);
  assert.equal(isPrivateAppPath("/perfil/cuenta"), true);
  assert.equal(isPrivateAppPath("/guardados"), true);
  assert.equal(isPrivateAppPath("/en-vivo"), true);
  assert.equal(isPrivateAppPath("/local"), true);
  assert.equal(isPrivateAppPath("/local/rosario"), true);
  assert.equal(isPrivateAppPath("/buscar"), true);
  assert.equal(isPrivateAppPath("/buscar/q"), true);
  assert.equal(isPrivateAppPath("/onboarding"), true);
  assert.equal(isPrivateAppPath("/dev/respaldo"), true);
  assert.equal(isPrivateAppPath("/transparencia"), true);
  assert.equal(isPrivateAppPath("/transparencia/borradores"), true);
  assert.equal(isPrivateAppPath("/transparencia/borradores/11111111-1111-4111-8111-111111111111"), true);
});

test("public sections stay outside the home gate", () => {
  for (const path of [
    "/noticias/colectivo-pellegrini",
    "/contacto",
    "/seguimiento/abc",
    "/como-funciona",
    "/privacidad",
    "/terminos",
    "/cuenta/recuperar",
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
  assert.equal(isPrivateAppPath("/seguidos"), false);
  assert.equal(isPrivateAppPath("/notificaciones"), false);
});
