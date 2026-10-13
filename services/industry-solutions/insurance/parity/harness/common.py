"""Shared paths, fingerprints, contract loading and value normalisation."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

PARITY = Path(__file__).resolve().parents[1]
INSURANCE = PARITY.parent
ROOT = INSURANCE.parents[2]
DB = INSURANCE / "db"
SCENARIOS = PARITY / "scenarios"
TRANSCRIPTS = PARITY / "transcripts"
RULES = PARITY / "rules"
REPORTS = PARITY / "reports"
ROUTES = PARITY / "routes.yaml"
SERVICE_TESTS = INSURANCE / "commission-service" / "tests"

SOURCE_FILES = (DB / "oltp" / "03_commission_pkg.sql", DB / "olap" / "02_etl_pkg.sql")
FIXTURE_FILES = (
    DB / "oltp" / "01_tables.sql",
    DB / "oltp" / "02_seed.sql",
    DB / "olap" / "01_star_schema.sql",
    DB / "setup" / "01_users.sql",
)


def _digest(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def source_sha() -> str:
    return _digest(SOURCE_FILES)


def fixture_sha() -> str:
    return _digest(FIXTURE_FILES)


def load_routes() -> dict[str, Any]:
    return yaml.safe_load(ROUTES.read_text())


def load_scenarios(module: str | None = None) -> list[dict[str, Any]]:
    modules = [module] if module else sorted(p.name for p in SCENARIOS.iterdir() if p.is_dir())
    scenarios = []
    for name in modules:
        for path in sorted((SCENARIOS / name).glob("*.yaml")):
            scenario = yaml.safe_load(path.read_text())
            if scenario.get("module") != name:
                raise ValueError(f"{path}: module must be {name}")
            scenarios.append(scenario)
    return scenarios


def transcript_path(scenario: dict[str, Any]) -> Path:
    return TRANSCRIPTS / scenario["module"] / f"{scenario['id']}.json"


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def normalize(value: Any, kind: str) -> Any:
    """Canonical comparison form shared by Oracle and HTTP values."""
    if value is None:
        return None
    if kind == "integer":
        return int(value)
    if kind == "decimal":
        try:
            number = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError(f"not a decimal: {value!r}") from exc
        return format(number.normalize(), "f") if number != 0 else "0"
    if kind == "text":
        return str(value).rstrip() if isinstance(value, str) else str(value)
    raise ValueError(f"unknown type {kind}")


def normalize_row(row: dict[str, Any], columns: dict[str, str]) -> dict[str, Any]:
    lowered = {str(key).lower(): value for key, value in row.items()}
    return {name: normalize(lowered.get(name), kind) for name, kind in columns.items()}


def is_application_error(ora_code: int | None) -> bool:
    """RAISE_APPLICATION_ERROR range: the only messages that are business contract."""
    return ora_code is not None and -20999 <= ora_code <= -20000


def comparable_outcome(outcome: dict[str, Any]) -> dict[str, Any]:
    if outcome.get("status") != "error":
        return outcome
    graded = {"status": "error", "ora_code": outcome.get("ora_code")}
    if is_application_error(outcome.get("ora_code")):
        graded["message"] = outcome.get("message")
    return graded
