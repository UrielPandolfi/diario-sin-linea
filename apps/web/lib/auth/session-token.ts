export const READER_COOKIE = "sl_reader";

const VECTOR_SUB = "11111111-1111-4111-8111-111111111111";

function bytesToBinary(bytes: Uint8Array): string {
  let binary = "";
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index] ?? 0);
  }
  return binary;
}

function b64urlEncode(bytes: Uint8Array): string {
  return btoa(bytesToBinary(bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlDecode(value: string): Uint8Array | null {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) return null;
  const padded = value + "=".repeat((4 - (value.length % 4)) % 4);
  try {
    const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
    return bytes;
  } catch {
    return null;
  }
}

function canonicalPayload(sub: string, exp: number): string {
  return JSON.stringify({ exp, sub });
}

async function hmacKey(secret: string): Promise<CryptoKey> {
  return crypto.subtle.importKey("raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

export async function signReaderToken(sub: string, secret: string, exp: number): Promise<string> {
  const body = b64urlEncode(new TextEncoder().encode(canonicalPayload(sub, exp)));
  const signature = new Uint8Array(await crypto.subtle.sign("HMAC", await hmacKey(secret), new TextEncoder().encode(body)));
  return `${body}.${b64urlEncode(signature)}`;
}

export async function verifyReaderToken(
  token: string | undefined | null,
  secret: string,
  nowSeconds = Math.floor(Date.now() / 1000),
): Promise<string | null> {
  if (!token || !secret) return null;
  const parts = token.split(".");
  if (parts.length !== 2) return null;
  const [body, signature] = parts;
  if (!body || !signature) return null;
  const given = b64urlDecode(signature);
  if (!given) return null;
  const signatureBytes = new Uint8Array(given.byteLength);
  signatureBytes.set(given);
  const valid = await crypto.subtle.verify(
    "HMAC",
    await hmacKey(secret),
    signatureBytes,
    new TextEncoder().encode(body),
  );
  if (!valid) return null;
  const raw = b64urlDecode(body);
  if (!raw) return null;
  let payload: unknown;
  try {
    payload = JSON.parse(new TextDecoder().decode(raw));
  } catch {
    return null;
  }
  if (!payload || typeof payload !== "object") return null;
  const record = payload as { sub?: unknown; exp?: unknown };
  if (typeof record.sub !== "string" || typeof record.exp !== "number" || !Number.isInteger(record.exp)) return null;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(record.sub)) return null;
  if (record.exp <= nowSeconds) return null;
  return record.sub;
}

export const READER_TOKEN_VECTOR = {
  sub: VECTOR_SUB,
  secret: "dev-secret-change-me",
  exp: 1_700_000_300,
  token:
    "eyJleHAiOjE3MDAwMDAzMDAsInN1YiI6IjExMTExMTExLTExMTEtNDExMS04MTExLTExMTExMTExMTExMSJ9.6sMAInyt9h_J7aYFTaBfTldLe-1J9dRDU2srTf3d4S4",
};
