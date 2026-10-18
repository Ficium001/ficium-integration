"""Repo-level checks CI runs: versions agree, $ids match paths, every event type has fixtures."""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://contract.ficium.net/schemas/"
errors = []

pkg = json.loads((ROOT / "package.json").read_text())["version"]
py = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M).group(1)
mod = re.search(r'__version__ = "([^"]+)"', (ROOT / "python/ficium_contract/__init__.py").read_text()).group(1)
ts = re.search(r'VERSION = "([^"]+)"', (ROOT / "ts/src/index.ts").read_text()).group(1)
if ts != pkg:
    errors.append(f"version mismatch: ts VERSION={ts} package.json={pkg}")
if not (pkg == py == mod):
    errors.append(f"version mismatch: package.json={pkg} pyproject={py} __init__={mod}")
if pkg.split(".")[0] != "1":
    errors.append("major version must stay 1 while only v1 schemas exist")

for f in (ROOT / "schemas").rglob("*.json"):
    if f.relative_to(ROOT / "schemas").parts[0] == "catalogs":
        # Data shipped with the schemas (e.g. chat templates), not schemas: no $id. Check its shape instead.
        doc = json.loads(f.read_text())
        if not (isinstance(doc.get("catalog"), str) and isinstance(doc.get("version"), int)):
            errors.append(f"{f}: a catalog needs 'catalog' (name) and 'version' (int)")
        continue
    sid = json.loads(f.read_text()).get("$id")
    want = BASE + str(f.relative_to(ROOT / "schemas"))
    if sid != want:
        errors.append(f"{f}: $id {sid} != {want}")

env = json.loads((ROOT / "schemas/envelope.v1.json").read_text())
types = env["properties"]["type"]["enum"]
valid = [json.loads(p.read_text())["type"] for p in (ROOT / "fixtures/events/valid").glob("*.json")]
invalid_dirs = {p.stem for p in (ROOT / "fixtures/events/invalid").glob("*.json")}
for t in types:
    if not (ROOT / f"schemas/events/{t}.v1.json").exists():
        errors.append(f"type {t} has no schema")
    if t not in valid:
        errors.append(f"type {t} has no valid fixture")

if errors:
    print("\n".join(errors)); sys.exit(1)
print(f"ok: version {pkg}, {len(types)} event types, {len(valid)} valid and {len(invalid_dirs)} invalid fixtures")
