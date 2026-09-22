import assert from "node:assert/strict";
import { test } from "node:test";

import { formatArticleStamp, parseReadingSize, readingMinutes, resolveReadingSize } from "./reading";

test("reading minutes are deterministic from word count", () => {
  assert.equal(readingMinutes([]), null);
  assert.equal(readingMinutes(["uno"]), 1);
  const words = Array.from({ length: 460 }, (_, index) => `p${index}`).join(" ");
  assert.equal(readingMinutes([words]), 2);
});

test("reading size defaults to medium and rejects unknown values", () => {
  assert.equal(resolveReadingSize(undefined), "md");
  assert.equal(parseReadingSize("xl"), null);
  assert.equal(parseReadingSize("sm"), "sm");
});

test("article stamp stays locale-stable", () => {
  const stamp = formatArticleStamp("2026-09-18T11:33:00.000-03:00");
  assert.match(stamp, /18/);
  assert.match(stamp, /2026/);
  assert.match(stamp, /11:33/);
});
