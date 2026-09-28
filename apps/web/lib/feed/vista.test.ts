import assert from "node:assert/strict";
import test from "node:test";

import { parseVista } from "./vista";

test("home opens on Principal and keeps Últimas in the query", () => {
  assert.equal(parseVista(null), "principal");
  assert.equal(parseVista("principal"), "principal");
  assert.equal(parseVista("local"), "principal");
  assert.equal(parseVista("argentina"), "principal");
  assert.equal(parseVista("ultimas"), "ultimas");
});
