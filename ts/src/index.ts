/**
 * Ficium integration contract v1: schema validation and HMAC signing.
 * Mirrors python/ficium_contract exactly; both are tested against the same
 * fixtures and signing vectors.
 */
import { createHmac, timingSafeEqual } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import Ajv2020Module from "ajv/dist/2020.js";
import addFormatsModule from "ajv-formats";

const Ajv2020 = (Ajv2020Module as unknown as { default?: typeof Ajv2020Module }).default ?? Ajv2020Module;
const addFormats = (addFormatsModule as unknown as { default?: typeof addFormatsModule }).default ?? addFormatsModule;

export const VERSION = "1.4.0";
export const SIGNATURE_HEADER = "Ficium-Signature";
export const DEFAULT_TOLERANCE_SECONDS = 300;

export class ContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ContractError";
  }
}

const here = dirname(fileURLToPath(import.meta.url));
// ts/dist/index.js -> repo root (or package root when installed)
const schemaRoot = join(here, "..", "..", "schemas");

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((n) => {
    const p = join(dir, n);
    return statSync(p).isDirectory() ? walk(p) : p.endsWith(".json") ? [p] : [];
  });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ajv = new (Ajv2020 as any)({ allErrors: true, strict: false });
(addFormats as any)(ajv);
const ids: Record<string, string> = {};
for (const f of walk(schemaRoot).sort()) {
  const doc = JSON.parse(readFileSync(f, "utf8"));
  ajv.addSchema(doc);
  ids[relative(schemaRoot, f).split("\\").join("/")] = doc.$id;
}

function check(name: string, instance: unknown): void {
  const validate = ajv.getSchema(ids[name]);
  if (!validate) throw new Error(`schema ${name} not loaded`);
  if (!validate(instance)) {
    const msg = (validate.errors ?? [])
      .map((e: { instancePath: string; message?: string }) => `${e.instancePath || "<root>"}: ${e.message}`)
      .sort()
      .join("; ");
    throw new ContractError(msg);
  }
}

export const validateEvent = (envelope: unknown): void => check("envelope.v1.json", envelope);
export const validateAcceptanceRequest = (body: unknown): void => check("calls/acceptance.request.v1.json", body);
export const validateAcceptanceResponse = (body: unknown): void => check("calls/acceptance.response.v1.json", body);
export const validateDocumentUploadRequest = (body: unknown): void => check("calls/document_upload.request.v1.json", body);
export const validateDocumentUploadResponse = (body: unknown): void => check("calls/document_upload.response.v1.json", body);
export const validateDocumentCompleteRequest = (body: unknown): void => check("calls/document_complete.request.v1.json", body);
export const validateDocumentCompleteResponse = (body: unknown): void => check("calls/document_complete.response.v1.json", body);

function mac(key: Buffer | string, t: number, rawBody: Buffer | string): string {
  return createHmac("sha256", key).update(`${t}.`).update(rawBody).digest("hex");
}

export function sign(rawBody: Buffer | string, key: Buffer | string, timestamp?: number): string {
  const t = timestamp ?? Math.floor(Date.now() / 1000);
  return `t=${t},v1=${mac(key, t, rawBody)}`;
}

export function verify(
  header: string,
  rawBody: Buffer | string,
  keys: Array<Buffer | string>,
  now?: number,
  tolerance = DEFAULT_TOLERANCE_SECONDS,
): void {
  const parts = Object.fromEntries(
    header.split(",").map((p) => {
      const i = p.indexOf("=");
      return i < 0 ? [p, ""] : [p.slice(0, i), p.slice(i + 1)];
    }),
  );
  const t = Number(parts.t);
  if (!parts.t || !parts.v1 || !Number.isInteger(t)) throw new ContractError("malformed signature header");
  const current = now ?? Math.floor(Date.now() / 1000);
  if (Math.abs(current - t) > tolerance) throw new ContractError("signature timestamp outside tolerance");
  const usable = keys.filter((k) => k && k.length > 0);
  if (usable.length === 0) throw new ContractError("no verification keys configured");
  const given = Buffer.from(parts.v1, "utf8");
  for (const k of usable) {
    const expected = Buffer.from(mac(k, t, rawBody), "utf8");
    if (expected.length === given.length && timingSafeEqual(expected, given)) return;
  }
  throw new ContractError("signature mismatch");
}
