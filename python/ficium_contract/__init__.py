"""Ficium integration contract v1: schema validation and HMAC signing.

Used by both the borrower side and the institution side so they validate
and sign events identically. See README.md for the rules.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

__version__ = "1.10.0"

SIGNATURE_HEADER = "Ficium-Signature"
DEFAULT_TOLERANCE_SECONDS = 300

_SCHEMA_ROOT_CANDIDATES = (
    Path(__file__).resolve().parent / "schemas",          # installed wheel
    Path(__file__).resolve().parents[2] / "schemas",      # repo checkout
)


class ContractError(ValueError):
    """Raised when an envelope, call body or signature fails the contract."""


def _schema_root() -> Path:
    for p in _SCHEMA_ROOT_CANDIDATES:
        if (p / "envelope.v1.json").exists():
            return p
    raise FileNotFoundError("ficium-contract schemas not found")


@lru_cache(maxsize=1)
def _registry() -> tuple[Registry, dict[str, dict]]:
    root = _schema_root()
    reg = Registry()
    by_name: dict[str, dict] = {}
    for f in sorted(root.rglob("*.json")):
        if f.relative_to(root).parts[0] == "catalogs":  # data, not schemas
            continue
        doc = json.loads(f.read_text())
        reg = reg.with_resource(doc["$id"], Resource.from_contents(doc))
        by_name[str(f.relative_to(root))] = doc
    return reg, by_name


def _validator(name: str) -> Draft202012Validator:
    reg, by_name = _registry()
    return Draft202012Validator(by_name[name], registry=reg, format_checker=FormatChecker())


def _errors(name: str, instance: Any) -> list[str]:
    v = _validator(name)
    return sorted(
        f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
        for e in v.iter_errors(instance)
    )


def validate_event(envelope: dict) -> None:
    """Validate a whole envelope, including its data, against v1. Raises ContractError."""
    errs = _errors("envelope.v1.json", envelope)
    if errs:
        raise ContractError("; ".join(errs))


def validate_acceptance_request(body: dict) -> None:
    errs = _errors("calls/acceptance.request.v1.json", body)
    if errs:
        raise ContractError("; ".join(errs))


def validate_acceptance_response(body: dict) -> None:
    errs = _errors("calls/acceptance.response.v1.json", body)
    if errs:
        raise ContractError("; ".join(errs))


def _check(name: str, body: dict) -> None:
    errs = _errors(f"calls/{name}.v1.json", body)
    if errs:
        raise ContractError("; ".join(errs))


def validate_document_upload_request(body: dict) -> None:
    _check("document_upload.request", body)


def validate_document_upload_response(body: dict) -> None:
    _check("document_upload.response", body)


def validate_document_complete_request(body: dict) -> None:
    _check("document_complete.request", body)


def validate_document_complete_response(body: dict) -> None:
    _check("document_complete.response", body)


# ── chat templates (contract 1.9) ───────────────────────────────────────────
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_INT_STR = re.compile(r"^-?\d+$")
_DEC_STR = re.compile(r"^-?\d+(\.\d+)?$")


@lru_cache(maxsize=1)
def _chat_catalog() -> dict[str, dict]:
    doc = json.loads((_schema_root() / "catalogs" / "chat-templates.v1.json").read_text())
    return {t["code"]: t for t in doc["templates"]}


def chat_templates(sender_side: str | None = None) -> list[dict]:
    """The structured chat templates, optionally only those one side may send."""
    rows = [dict(t) for t in _chat_catalog().values() if sender_side in (None, t["sender_side"])]
    return sorted(rows, key=lambda t: (t["sender_side"], t["sort_order"], t["code"]))


def _number(key: str, value: Any, integral: bool) -> float | int:
    if isinstance(value, bool):
        raise ContractError(f"'{key}' must be a number.")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if integral and not value.is_integer():
            raise ContractError(f"'{key}' must be a whole number.")
        return int(value) if integral else value
    if isinstance(value, str) and (_INT_STR if integral else _DEC_STR).match(value.strip()):
        return int(value.strip()) if integral else float(value.strip())
    raise ContractError(f"'{key}' must be {'a whole number' if integral else 'a number'}.")


def _fmt_decimal(n: float | int) -> str:
    out = f"{float(n):.4f}"
    return out.rstrip("0").rstrip(".") if "." in out else out


def render_chat_message(template_code: str, params: dict | None, sender_side: str) -> tuple[str, dict]:
    """Validate params against the template and render its body. Returns (body, cleaned params).

    Both sides render with this (or renderChatMessage in TypeScript); a receiver re-renders a structured
    chat.message and rejects it if the body differs. Unknown params are dropped; every placeholder must be filled.
    """
    tpl = _chat_catalog().get(template_code)
    if tpl is None:
        raise ContractError(f"Unknown template: {template_code}")
    if tpl["sender_side"] != sender_side:
        raise ContractError(f"Template {template_code} is not available to {sender_side}")
    params = params or {}
    cleaned: dict = {}
    rendered: dict[str, str] = {}
    for key, spec in (tpl.get("params_schema") or {}).items():
        if key not in params:
            continue
        value, kind = params[key], spec.get("type")
        if kind in ("int", "decimal"):
            num = _number(key, value, kind == "int")
            lo, hi = spec.get("min"), spec.get("max")
            if lo is not None and num < lo:
                raise ContractError(f"'{key}' must be at least {lo}.")
            if hi is not None and num > hi:
                raise ContractError(f"'{key}' must be at most {hi}.")
            cleaned[key] = num
            rendered[key] = str(num) if kind == "int" else _fmt_decimal(num)
        elif kind == "enum":
            if not isinstance(value, str) or value not in (spec.get("values") or []):
                raise ContractError(f"'{key}' must be one of: {', '.join(spec.get('values') or [])}.")
            cleaned[key] = rendered[key] = value
        elif kind in ("string_list", "label_amount_list"):
            items = value if isinstance(value, list) else [value]
            items = [str(v).strip() for v in items if isinstance(v, (str, int, float)) and str(v).strip()]
            if not items:
                raise ContractError(f"'{key}' needs at least one entry.")
            if spec.get("max_items") is not None and len(items) > spec["max_items"]:
                raise ContractError(f"'{key}' allows at most {spec['max_items']} entries.")
            if spec.get("max_len") is not None and any(len(v) > spec["max_len"] for v in items):
                raise ContractError(f"Each '{key}' entry must be {spec['max_len']} characters or fewer.")
            cleaned[key] = items
            rendered[key] = ", ".join(items)
        else:
            raise ContractError(f"Template {template_code}: unsupported param type {kind!r}")
    missing = sorted({k for k in _PLACEHOLDER.findall(tpl["body_template"]) if k not in rendered})
    if missing:
        raise ContractError(f"Missing template parameter(s): {', '.join(missing)}.")
    body = _PLACEHOLDER.sub(lambda m: rendered[m.group(1)], tpl["body_template"])
    return body, cleaned


def sign(raw_body: bytes, key: bytes, timestamp: int | None = None) -> str:
    """Return the Ficium-Signature header value for raw_body."""
    t = int(time.time()) if timestamp is None else int(timestamp)
    mac = hmac.new(key, f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(
    header: str,
    raw_body: bytes,
    keys: Iterable[bytes],
    now: int | None = None,
    tolerance: int = DEFAULT_TOLERANCE_SECONDS,
) -> None:
    """Verify a Ficium-Signature header. Accepts any of `keys` (rotation). Raises ContractError."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
        given = parts["v1"]
    except (KeyError, ValueError) as e:
        raise ContractError("malformed signature header") from e
    now = int(time.time()) if now is None else int(now)
    if abs(now - t) > tolerance:
        raise ContractError("signature timestamp outside tolerance")
    key_list = [k for k in keys if k]
    if not key_list:
        raise ContractError("no verification keys configured")
    for k in key_list:
        expected = hmac.new(k, f"{t}.".encode() + raw_body, hashlib.sha256).hexdigest()
        if hmac.compare_digest(expected, given):
            return
    raise ContractError("signature mismatch")
