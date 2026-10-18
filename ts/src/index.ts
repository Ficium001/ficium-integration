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

export const VERSION = "1.10.0";
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
  if (relative(schemaRoot, f).split(/[\\/]/)[0] === "catalogs") continue; // data, not schemas
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

// ── chat templates (contract 1.9) ─────────────────────────────────────────────
export type SenderSide = "borrower" | "institution";
export interface ChatTemplate {
  code: string;
  sender_side: SenderSide;
  label: string;
  body_template: string;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  params_schema: Record<string, any>;
  sort_order: number;
}

let catalog: Map<string, ChatTemplate> | null = null;
function chatCatalog(): Map<string, ChatTemplate> {
  if (!catalog) {
    const doc = JSON.parse(readFileSync(join(schemaRoot, "catalogs", "chat-templates.v1.json"), "utf8"));
    catalog = new Map((doc.templates as ChatTemplate[]).map((t) => [t.code, t]));
  }
  return catalog;
}

/** The structured chat templates, optionally only those one side may send. */
export function chatTemplates(senderSide?: SenderSide): ChatTemplate[] {
  return [...chatCatalog().values()]
    .filter((t) => !senderSide || t.sender_side === senderSide)
    .map((t) => ({ ...t }))
    .sort((a, b) => a.sender_side.localeCompare(b.sender_side) || a.sort_order - b.sort_order || a.code.localeCompare(b.code));
}

const INT_STR = /^-?\d+$/;
const DEC_STR = /^-?\d+(\.\d+)?$/;

function toNumber(key: string, value: unknown, integral: boolean): number {
  if (typeof value === "boolean") throw new ContractError(`'${key}' must be a number.`);
  if (typeof value === "number" && Number.isFinite(value)) {
    if (integral && !Number.isInteger(value)) throw new ContractError(`'${key}' must be a whole number.`);
    return value;
  }
  if (typeof value === "string" && (integral ? INT_STR : DEC_STR).test(value.trim())) return Number(value.trim());
  throw new ContractError(`'${key}' must be ${integral ? "a whole number" : "a number"}.`);
}

function fmtDecimal(n: number): string {
  let out = n.toFixed(4);
  if (out.includes(".")) out = out.replace(/0+$/, "").replace(/\.$/, "");
  return out;
}

/**
 * Validate params against the template and render its body. Same algorithm as the Python
 * render_chat_message; both pass the shared fixtures in fixtures/chat/render. A receiver
 * re-renders a structured chat.message and rejects it if the body differs.
 */
export function renderChatMessage(
  templateCode: string, params: Record<string, unknown> | null | undefined, senderSide: SenderSide,
): { body: string; params: Record<string, unknown> } {
  const tpl = chatCatalog().get(templateCode);
  if (!tpl) throw new ContractError(`Unknown template: ${templateCode}`);
  if (tpl.sender_side !== senderSide) throw new ContractError(`Template ${templateCode} is not available to ${senderSide}`);
  const p = params ?? {};
  const cleaned: Record<string, unknown> = {};
  const rendered: Record<string, string> = {};
  for (const [key, spec] of Object.entries(tpl.params_schema ?? {})) {
    if (!(key in p)) continue;
    const value = p[key];
    const kind = spec?.type;
    if (kind === "int" || kind === "decimal") {
      const num = toNumber(key, value, kind === "int");
      if (spec.min != null && num < spec.min) throw new ContractError(`'${key}' must be at least ${spec.min}.`);
      if (spec.max != null && num > spec.max) throw new ContractError(`'${key}' must be at most ${spec.max}.`);
      cleaned[key] = num;
      rendered[key] = kind === "int" ? String(num) : fmtDecimal(num);
    } else if (kind === "enum") {
      const values: string[] = spec.values ?? [];
      if (typeof value !== "string" || !values.includes(value)) {
        throw new ContractError(`'${key}' must be one of: ${values.join(", ")}.`);
      }
      cleaned[key] = value;
      rendered[key] = value;
    } else if (kind === "string_list" || kind === "label_amount_list") {
      const raw = Array.isArray(value) ? value : [value];
      const items = raw
        .filter((v) => typeof v === "string" || typeof v === "number")
        .map((v) => String(v).trim())
        .filter((v) => v.length > 0);
      if (!items.length) throw new ContractError(`'${key}' needs at least one entry.`);
      if (spec.max_items != null && items.length > spec.max_items) {
        throw new ContractError(`'${key}' allows at most ${spec.max_items} entries.`);
      }
      if (spec.max_len != null && items.some((v) => v.length > spec.max_len)) {
        throw new ContractError(`Each '${key}' entry must be ${spec.max_len} characters or fewer.`);
      }
      cleaned[key] = items;
      rendered[key] = items.join(", ");
    } else {
      throw new ContractError(`Template ${templateCode}: unsupported param type ${String(kind)}`);
    }
  }
  const missing = [...new Set([...tpl.body_template.matchAll(/\{(\w+)\}/g)].map((m) => m[1]))]
    .filter((k) => !(k in rendered)).sort();
  if (missing.length) throw new ContractError(`Missing template parameter(s): ${missing.join(", ")}.`);
  return { body: tpl.body_template.replace(/\{(\w+)\}/g, (_m, k: string) => rendered[k]), params: cleaned };
}
