import assert from "node:assert/strict";
import test from "node:test";

import { formatLiveClock, formatUpdatedAgo, isFresh, isNewArrival, prefixArrivals } from "./radar";

test("live clock keeps hours, minutes and seconds", () => {
  const sample = formatLiveClock(Date.parse("2026-10-04T22:08:32Z"));
  assert.match(sample, /^\d{2}:\d{2}:\d{2}$/);
});

test("status age uses the real elapsed time", () => {
  const now = 1_700_000_000_000;
  assert.equal(formatUpdatedAgo(now, now), "Actualizado ahora");
  assert.equal(formatUpdatedAgo(now - 8_000, now), "Actualizado hace 8 s");
  assert.equal(formatUpdatedAgo(now - 59_000, now), "Actualizado hace 59 s");
  assert.equal(formatUpdatedAgo(now - 90_000, now), "Actualizado hace 1 min");
  assert.equal(formatUpdatedAgo(now - 3_600_000, now), "Actualizado hace 1 h");
});

test("fresh dot lasts five minutes", () => {
  const now = Date.parse("2026-10-04T19:08:00Z");
  assert.equal(isFresh("2026-10-04T19:07:30Z", now), true);
  assert.equal(isFresh("2026-10-04T19:03:01Z", now), true);
  assert.equal(isFresh("2026-10-04T19:03:00Z", now), false);
  assert.equal(isFresh("2026-10-04T19:09:00Z", now), false);
  assert.equal(isFresh(null, now), false);
  assert.equal(isFresh("2026-10-04T19:07:30Z", 0), false);
});

test("nuevo label expires after eight seconds", () => {
  const arrived = 10_000;
  assert.equal(isNewArrival(arrived, arrived + 7_999), true);
  assert.equal(isNewArrival(arrived, arrived + 8_000), false);
  assert.equal(isNewArrival(undefined, arrived), false);
});

test("only a new prefix counts as an arrival", () => {
  assert.deepEqual(prefixArrivals(null, ["a", "b"]), []);
  assert.deepEqual(prefixArrivals(["b", "c"], ["a", "b", "c"]), ["a"]);
  assert.deepEqual(prefixArrivals(["c"], ["a", "b", "c"]), ["a", "b"]);
  assert.deepEqual(prefixArrivals(["a", "b"], ["a", "b", "c"]), []);
  assert.deepEqual(prefixArrivals(["a", "c"], ["a", "b", "c"]), []);
});
