import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as fc from "../index.js";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const fix = join(root, "fixtures");
const load = (p: string) => JSON.parse(readFileSync(p, "utf8"));
const files = (d: string) => readdirSync(join(fix, d)).filter((f) => f.endsWith(".json")).sort();

for (const f of files("events/valid")) {
  test(`valid event ${f}`, () => fc.validateEvent(load(join(fix, "events/valid", f))));
}
for (const f of files("events/invalid")) {
  test(`invalid event ${f}`, () => {
    assert.throws(() => fc.validateEvent(load(join(fix, "events/invalid", f)).envelope), fc.ContractError);
  });
}
test("acceptance calls", () => {
  for (const f of files("calls/acceptance.request/valid")) fc.validateAcceptanceRequest(load(join(fix, "calls/acceptance.request/valid", f)));
  for (const f of files("calls/acceptance.request/invalid"))
    assert.throws(() => fc.validateAcceptanceRequest(load(join(fix, "calls/acceptance.request/invalid", f)).body), fc.ContractError);
  for (const f of files("calls/acceptance.response/valid")) fc.validateAcceptanceResponse(load(join(fix, "calls/acceptance.response/valid", f)));
});

const CALLS: Record<string, (b: unknown) => void> = {
  "acceptance.request": fc.validateAcceptanceRequest,
  "acceptance.response": fc.validateAcceptanceResponse,
  "document_upload.request": fc.validateDocumentUploadRequest,
  "document_upload.response": fc.validateDocumentUploadResponse,
  "document_complete.request": fc.validateDocumentCompleteRequest,
  "document_complete.response": fc.validateDocumentCompleteResponse,
};
for (const [name, check] of Object.entries(CALLS)) {
  test(`call ${name}`, () => {
    const valid = files(`calls/${name}/valid`);
    assert.ok(valid.length > 0);
    for (const f of valid) check(load(join(fix, `calls/${name}/valid`, f)));
    let inv: string[] = [];
    try { inv = files(`calls/${name}/invalid`); } catch { inv = []; }
    for (const f of inv) assert.throws(() => check(load(join(fix, `calls/${name}/invalid`, f)).body), fc.ContractError);
  });
}
for (const v of load(join(fix, "signing-vectors.json")) as Array<{ description: string; key: string; timestamp: number; body: string; header: string }>) {
  test(`signing vector: ${v.description}`, () => {
    assert.equal(fc.sign(Buffer.from(v.body, "utf8"), v.key, v.timestamp), v.header);
    fc.verify(v.header, Buffer.from(v.body, "utf8"), [v.key], v.timestamp);
  });
}
test("verify rejects tampering, staleness, wrong key, garbage, no keys", () => {
  const h = fc.sign('{"a":1}', "k1", 1_000_000);
  assert.throws(() => fc.verify(h, '{"a":2}', ["k1"], 1_000_000), /mismatch/);
  assert.throws(() => fc.verify(h, '{"a":1}', ["k1"], 1_000_301), /tolerance/);
  assert.throws(() => fc.verify(h, '{"a":1}', ["other"], 1_000_000), /mismatch/);
  assert.throws(() => fc.verify("garbage", '{"a":1}', ["k1"], 1_000_000), /malformed/);
  assert.throws(() => fc.verify(h, '{"a":1}', [], 1_000_000), /no verification keys/);
});
test("rotation accepts old and new key", () => {
  fc.verify(fc.sign("{}", "old", 5000), "{}", ["new", "old"], 5000);
});


// ── chat templates (1.9): the same fixtures as Python ─────────────────────────
for (const f of files("chat/render")) {
  const c = load(join(fix, "chat/render", f));
  test(`chat render ${f}`, () => {
    if (f.startsWith("valid-")) {
      assert.equal(fc.renderChatMessage(c.template_code, c.params, c.sender_side).body, c.body);
    } else {
      assert.throws(() => fc.renderChatMessage(c.template_code, c.params, c.sender_side), fc.ContractError);
    }
  });
}

test("chat catalog", () => {
  assert.equal(fc.chatTemplates().length, 19);
  for (const t of fc.chatTemplates()) {
    if (!Object.keys(t.params_schema).length) {
      assert.equal(fc.renderChatMessage(t.code, {}, t.sender_side).body, t.body_template);
    }
  }
});
