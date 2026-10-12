import assert from "node:assert/strict";
import { test } from "node:test";

import {
  PLAUSIBLE_TRANSFORM_SOURCE,
  isPlausibleEnabled,
  plausibleInitSnippet,
  requestHostname,
} from "./plausible";

type Payload = {
  n?: string;
  u?: string;
  d?: string;
  r?: string | null;
  i?: boolean;
  p?: unknown;
  $?: unknown;
  email?: string;
} | null;

const transform = new Function(`return (${PLAUSIBLE_TRANSFORM_SOURCE})`)() as (payload: Payload) => Payload;

test("requestHostname drops port and extra forwarded hosts", () => {
  assert.equal(requestHostname("WWW.SINLINEA.AR:443"), "www.sinlinea.ar");
  assert.equal(requestHostname("sinlinea.ar, www.sinlinea.ar"), "sinlinea.ar");
  assert.equal(requestHostname("localhost:3000"), "localhost");
  assert.equal(requestHostname("[::1]:3000"), "::1");
  assert.equal(requestHostname(null), "");
});

test("Plausible loads only on the production hosts", () => {
  const production = { NODE_ENV: "production", VERCEL_ENV: "production" };
  assert.equal(isPlausibleEnabled(production, "sinlinea.ar"), true);
  assert.equal(isPlausibleEnabled(production, "www.sinlinea.ar"), true);
  assert.equal(isPlausibleEnabled(production, "www.sinlinea.ar:443"), true);
  assert.equal(isPlausibleEnabled(production, "sinlinea.com.ar"), false);
  assert.equal(isPlausibleEnabled(production, "localhost"), false);
  assert.equal(isPlausibleEnabled(production, "preview.vercel.app"), false);
  assert.equal(
    isPlausibleEnabled(
      { NODE_ENV: "production", VERCEL_ENV: "preview", SITE_URL: "https://www.sinlinea.ar" },
      "www.sinlinea.ar",
    ),
    false,
  );
  assert.equal(isPlausibleEnabled({ NODE_ENV: "production" }, "www.sinlinea.ar"), false);
  assert.equal(
    isPlausibleEnabled({ NODE_ENV: "development", VERCEL_ENV: "production" }, "www.sinlinea.ar"),
    false,
  );
});

test("pageviews keep the public path and drop query, hash and props", () => {
  const result = transform({
    n: "pageview",
    u: "https://www.sinlinea.ar/noticias/colectivo?token=secreto&email=a@b.c#parte",
    d: "sinlinea.ar",
    r: "https://www.google.com/search?q=a@b.c",
    i: true,
    p: { user: "ana" },
    $: { amount: 1, currency: "ARS" },
    email: "ana@example.com",
  });
  assert.deepEqual(result, {
    n: "pageview",
    u: "https://www.sinlinea.ar/noticias/colectivo",
    d: "sinlinea.ar",
    i: true,
    r: "https://www.google.com/search",
  });
});

test("account reset tokens stay out of the page URL", () => {
  const result = transform({
    n: "pageview",
    u: "https://sinlinea.ar/cuenta/restablecer?token=abc",
    d: "sinlinea.ar",
  });
  assert.equal(result?.u, "https://sinlinea.ar/cuenta/restablecer");
});

test("tracking tokens collapse to /seguimiento", () => {
  const result = transform({
    n: "pageview",
    u: "https://www.sinlinea.ar/seguimiento/token-privado?email=a@b.c",
    r: "https://sinlinea.ar/seguimiento/otro-token",
    d: "sinlinea.ar",
  });
  assert.deepEqual(result, {
    n: "pageview",
    u: "https://www.sinlinea.ar/seguimiento",
    d: "sinlinea.ar",
    r: "https://sinlinea.ar/seguimiento",
  });
});

test("admin pageviews are dropped, including client navigations", () => {
  assert.equal(transform({ n: "pageview", u: "https://www.sinlinea.ar/admin" }), null);
  assert.equal(transform({ n: "pageview", u: "https://sinlinea.ar/admin/login?next=/admin" }), null);
  assert.equal(
    transform({ n: "pageview", u: "https://www.sinlinea.ar/administrador" })?.u,
    "https://www.sinlinea.ar/administrador",
  );
  const fromAdmin = transform({
    n: "pageview",
    u: "https://www.sinlinea.ar/noticias/nota",
    r: "https://www.sinlinea.ar/admin/events/1",
  });
  assert.equal(fromAdmin?.u, "https://www.sinlinea.ar/noticias/nota");
  assert.equal(fromAdmin?.r, null);
});

test("non-pageviews and other hosts are not sent", () => {
  assert.equal(transform({ n: "outbound", u: "https://www.sinlinea.ar/" }), null);
  assert.equal(transform({ n: "pageview", u: "http://localhost:3000/" }), null);
  assert.equal(transform({ n: "pageview", u: "https://preview.vercel.app/noticias/nota" }), null);
  assert.equal(transform(null), null);
});

test("the inline snippet initializes once with the shared transform", () => {
  const snippet = plausibleInitSnippet();
  assert.equal(snippet.match(/plausible\.init\(/g)?.length, 1);
  assert.equal(snippet.includes("plausible.init({captureOnLocalhost:false,transformRequest:"), true);
  assert.equal(snippet.includes(PLAUSIBLE_TRANSFORM_SOURCE), true);
  assert.equal(snippet.includes("captureOnLocalhost:true"), false);
});
