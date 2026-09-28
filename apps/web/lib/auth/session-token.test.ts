import assert from "node:assert/strict";
import { test } from "node:test";

import { READER_TOKEN_VECTOR, signReaderToken, verifyReaderToken } from "./session-token";

test("reader token matches the API contract and rejects tampering or expiry", async () => {
  const { sub, secret, exp, token } = READER_TOKEN_VECTOR;
  assert.equal(await signReaderToken(sub, secret, exp), token);
  assert.equal(await verifyReaderToken(token, secret, exp - 10), sub);
  assert.equal(await verifyReaderToken(token, secret, exp), null);
  assert.equal(await verifyReaderToken(`${token}x`, secret, exp - 10), null);
  assert.equal(await verifyReaderToken(token, "otra-clave", exp - 10), null);
  assert.equal(await verifyReaderToken(undefined, secret), null);
});
