import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import ficium_contract as fc

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


def _load(p):
    return json.loads(p.read_text())


@pytest.mark.parametrize("path", sorted((ROOT / "schemas").rglob("*.json")), ids=lambda p: p.name)
def test_schema_is_valid_2020_12(path):
    Draft202012Validator.check_schema(_load(path))


@pytest.mark.parametrize("path", sorted((FIX / "events/valid").glob("*.json")), ids=lambda p: p.stem)
def test_valid_events_pass(path):
    fc.validate_event(_load(path))


@pytest.mark.parametrize("path", sorted((FIX / "events/invalid").glob("*.json")), ids=lambda p: p.stem)
def test_invalid_events_fail(path):
    case = _load(path)
    with pytest.raises(fc.ContractError):
        fc.validate_event(case["envelope"])


def test_acceptance_calls():
    for p in (FIX / "calls/acceptance.request/valid").glob("*.json"):
        fc.validate_acceptance_request(_load(p))
    for p in (FIX / "calls/acceptance.request/invalid").glob("*.json"):
        with pytest.raises(fc.ContractError):
            fc.validate_acceptance_request(_load(p)["body"])
    for p in (FIX / "calls/acceptance.response/valid").glob("*.json"):
        fc.validate_acceptance_response(_load(p))


CALLS = {
    "acceptance.request": fc.validate_acceptance_request,
    "acceptance.response": fc.validate_acceptance_response,
    "document_upload.request": fc.validate_document_upload_request,
    "document_upload.response": fc.validate_document_upload_response,
    "document_complete.request": fc.validate_document_complete_request,
    "document_complete.response": fc.validate_document_complete_response,
}


def test_every_call_has_a_validator_and_fixtures():
    on_disk = {p.stem.removesuffix(".v1") for p in (ROOT / "schemas/calls").glob("*.json")}
    assert on_disk == set(CALLS)
    for name in CALLS:
        assert list((FIX / f"calls/{name}/valid").glob("*.json")), name


@pytest.mark.parametrize("name", sorted(CALLS))
def test_calls(name):
    check = CALLS[name]
    for p in (FIX / f"calls/{name}/valid").glob("*.json"):
        check(_load(p))
    for p in (FIX / f"calls/{name}/invalid").glob("*.json"):
        with pytest.raises(fc.ContractError):
            check(_load(p)["body"])


@pytest.mark.parametrize("vec", _load(FIX / "signing-vectors.json"), ids=lambda v: v["description"])
def test_signing_vectors(vec):
    body, key = vec["body"].encode(), vec["key"].encode()
    assert fc.sign(body, key, vec["timestamp"]) == vec["header"]
    fc.verify(vec["header"], body, [key], now=vec["timestamp"])


def test_verify_rejects_tampering_staleness_and_wrong_key():
    key, body = b"k1", b'{"a":1}'
    h = fc.sign(body, key, 1_000_000)
    with pytest.raises(fc.ContractError, match="mismatch"):
        fc.verify(h, b'{"a":2}', [key], now=1_000_000)
    with pytest.raises(fc.ContractError, match="tolerance"):
        fc.verify(h, body, [key], now=1_000_000 + 301)
    with pytest.raises(fc.ContractError, match="mismatch"):
        fc.verify(h, body, [b"other"], now=1_000_000)
    with pytest.raises(fc.ContractError, match="malformed"):
        fc.verify("garbage", body, [key], now=1_000_000)
    with pytest.raises(fc.ContractError, match="no verification keys"):
        fc.verify(h, body, [], now=1_000_000)


def test_rotation_accepts_old_and_new_key():
    body = b"{}"
    old = fc.sign(body, b"old", 5000)
    fc.verify(old, body, [b"new", b"old"], now=5000)


# ── chat templates (1.9) ─────────────────────────────────────────────────────
RENDER = sorted((FIX / "chat/render").glob("*.json"))


@pytest.mark.parametrize("path", [p for p in RENDER if p.name.startswith("valid-")], ids=lambda p: p.stem)
def test_chat_render_valid(path):
    case = _load(path)
    body, _ = fc.render_chat_message(case["template_code"], case["params"], case["sender_side"])
    assert body == case["body"]


@pytest.mark.parametrize("path", [p for p in RENDER if p.name.startswith("invalid-")], ids=lambda p: p.stem)
def test_chat_render_invalid(path):
    case = _load(path)
    with pytest.raises(fc.ContractError):
        fc.render_chat_message(case["template_code"], case["params"], case["sender_side"])


def test_chat_catalog_is_complete_and_renders():
    codes = {t["code"] for t in fc.chat_templates()}
    assert len(codes) == 19
    assert {t["sender_side"] for t in fc.chat_templates("borrower")} == {"borrower"}
    for t in fc.chat_templates():
        if not t["params_schema"]:  # every parameterless template renders to itself
            assert fc.render_chat_message(t["code"], {}, t["sender_side"])[0] == t["body_template"]
