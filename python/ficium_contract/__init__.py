"""Ficium integration contract v1: schema validation and HMAC signing.

Used by both the borrower side and the institution side so they validate
and sign events identically. See README.md for the rules.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

__version__ = "1.7.0"

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
