from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[2]
PROC_DIR = ROOT / "services" / "legacy-billing" / "db" / "procs"
TRANSCRIPTS = ROOT / "procs" / "transcripts"
ROUTES = ROOT / "procs" / "routes.yaml"
REPORT_DIR = ROOT / "procs" / "reports"

FAIL = 1
TARGET_UNREACHABLE = 3
CONTRACT_MISSING = 6
SOURCE_MISMATCH = 7


def source_sha() -> str:
    digest = hashlib.sha256()
    for path in sorted(PROC_DIR.glob("*.sql")):
        digest.update(str(path.relative_to(PROC_DIR)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def normalize(value: Any, kind: str | None = None) -> Any:
    if value is None:
        return None
    if kind == "decimal":
        return str(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    if kind == "integer":
        return int(value)
    if kind == "date":
        return date.fromisoformat(str(value)).isoformat()
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in sorted(value.items())}
    return value


def json_path(value: Any, path: str) -> Any:
    if path == "$":
        return value
    current: list[Any] = [value]
    tokens = re.findall(r"\[\*\]|\[\d+\]|[^.\[\]]+", path[1:])
    for token in tokens:
        if token == "[*]":
            current = [child for item in current for child in item]
        elif token.startswith("["):
            current = [item[int(token[1:-1])] for item in current]
        else:
            current = [item[token] for item in current]
    return current if "[*]" in path else (current[0] if current else None)


def operation(value: Any, spec: dict[str, Any]) -> Any:
    if spec.get("operation") == "join_fields":
        items = value if isinstance(value, list) else [value]
        if spec.get("sort_by"):
            items = sorted(items, key=lambda item: item[spec["sort_by"]])
        return spec["separator"].join(
            spec.get("field_separator", ":").join(
                str(spec.get("null_value", ""))
                if item[field] is None
                else str(normalize(item[field]))
                for field in spec["fields"]
            )
            for item in items
        )
    if spec.get("operation") == "join_rows":
        items = sorted(value, key=lambda item: item[spec["sort_by"]])
        return spec["separator"].join(
            spec["row_separator"].join(
                str(spec.get("null_value", ""))
                if item[field] is None
                else str(normalize(item[field]))
                for field in spec["fields"]
            )
            for item in items
        )
    return value


def extract(payload: Any, spec: dict[str, Any]) -> Any:
    value = json_path(payload, spec["json_path"])
    value = operation(value, spec)
    if spec.get("collect"):
        return [normalize(item, spec.get("type")) for item in value]
    return normalize(value, spec.get("type"))


def request_json(base_url: str, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        f"{base_url}{path}",
        method=method,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as error:
        raw = error.read()
        return error.code, json.loads(raw) if raw else None


def target_request(base_url: str, contract: dict[str, Any], inputs: dict[str, Any]) -> tuple[int, Any]:
    path = contract["path"]
    for name, input_name in contract.get("inputs", {}).get("path", {}).items():
        path = path.replace("{" + name + "}", str(inputs[input_name]))
    query = contract.get("inputs", {}).get("query", {})
    if query:
        path += "?" + "&".join(f"{name}={inputs[input_name]}" for name, input_name in query.items())
    body = {name: inputs[input_name] for name, input_name in contract.get("inputs", {}).get("body", {}).items()}
    return request_json(base_url, contract["method"], path, body or None)


def load_transcripts(module: str | None) -> list[dict[str, Any]]:
    paths = sorted(TRANSCRIPTS.glob(f"{module}/*.json" if module else "*/*.json"))
    return [json.loads(path.read_text()) for path in paths]


def compare(transcript: dict[str, Any], contract: dict[str, Any], payload: Any) -> list[dict[str, Any]]:
    failures = []
    for field, spec in contract["response"].get("business_fields", {}).items():
        if field not in transcript["business_fields"]:
            continue
        expected = transcript["business_fields"][field]
        actual = extract(payload, spec)
        if expected != actual:
            failures.append({"kind": "field", "name": field, "expected": expected, "actual": actual})
    for probe_id, expected in transcript.get("probes", {}).items():
        spec = contract["response"].get("probes", {}).get(probe_id)
        if spec is None:
            failures.append({"kind": "probe-contract", "name": probe_id, "expected": expected, "actual": None})
            continue
        actual = extract(payload, spec)
        if expected != actual:
            failures.append({"kind": "probe", "name": probe_id, "expected": expected, "actual": actual})
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module")
    parser.add_argument("--scenario")
    parser.add_argument("--base-url", default=os.getenv("BILLING_SVC_URL", "http://localhost:8097"))
    args = parser.parse_args()
    routes = yaml.safe_load(ROUTES.read_text())["modules"]
    expected_sha = (TRANSCRIPTS / "SOURCE_SHA").read_text().strip()
    current_sha = source_sha()
    if expected_sha != current_sha:
        print(f"transcript SOURCE_SHA {expected_sha} does not match current procs {current_sha}", file=sys.stderr)
        return SOURCE_MISMATCH
    selected = [
        item for item in load_transcripts(args.module)
        if args.scenario is None or item["scenario"] == args.scenario
    ]
    extracted_modules = {
        transcript["module"]
        for transcript in selected
        if routes.get(transcript["module"], {}).get("status") == "extracted"
    }
    for extracted_module in sorted(extracted_modules):
        gate = subprocess.run(
            [sys.executable, str(ROOT / "procs" / "harness" / "rules_gate.py"), "--module", extracted_module],
            capture_output=True,
            text=True,
            check=False,
        )
        if gate.returncode:
            print(
                f"rules gate for {extracted_module} is not green:\n{gate.stderr or gate.stdout}",
                file=sys.stderr,
            )
            return CONTRACT_MISSING
    try:
        request_json(args.base_url, "POST", "/internal/reset")
    except (URLError, OSError) as error:
        print(f"target unreachable: {error}", file=sys.stderr)
        return TARGET_UNREACHABLE
    results = []
    contract_errors = []
    for transcript in selected:
        module = routes.get(transcript["module"])
        if module is None:
            contract_errors.append(f"{transcript['scenario']}: module missing from routes.yaml")
            continue
        if module["status"] == "pending":
            results.append({"scenario": transcript["scenario"], "module": transcript["module"], "status": "SKIP"})
            continue
        contract = module.get("entrypoints", {}).get(transcript["entrypoint"])
        if contract is None:
            contract_errors.append(f"{transcript['scenario']}: entrypoint {transcript['entrypoint']} missing")
            continue
        override = module.get("scenario_overrides", {}).get(transcript["scenario"], {})
        if override:
            contract = json.loads(json.dumps(contract))
            contract["response"]["business_fields"].update(
                override.get("response", {}).get("business_fields", {})
            )
            contract["response"]["probes"].update(
                override.get("response", {}).get("probes", {})
            )
        try:
            request_json(args.base_url, "POST", "/internal/reset")
            status, payload = target_request(args.base_url, contract, transcript["inputs"])
        except (URLError, OSError) as error:
            print(f"target unreachable during {transcript['scenario']}: {error}", file=sys.stderr)
            return TARGET_UNREACHABLE
        failures = [] if status == 200 else [{"kind": "status", "name": "status", "expected": 200, "actual": status}]
        failures.extend(compare(transcript, contract, payload))
        results.append({
            "scenario": transcript["scenario"],
            "module": transcript["module"],
            "status": "PASS" if not failures else "FAIL",
            "failures": failures,
        })
    if contract_errors:
        status = CONTRACT_MISSING
        for error in contract_errors:
            print(error, file=sys.stderr)
    else:
        status = FAIL if any(item["status"] == "FAIL" for item in results) else 0
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"source_sha": current_sha, "results": results, "contract_errors": contract_errors}
    (REPORT_DIR / "parity.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    lines = ["# Billing parity report", "", f"Source SHA: `{current_sha}`", ""]
    for item in results:
        lines.append(f"- **{item['status']}** `{item['module']}/{item['scenario']}`")
        for failure in item.get("failures", []):
            lines.append(
                f"  - {failure['kind']} `{failure['name']}`: expected `{failure['expected']}`, "
                f"actual `{failure['actual']}`"
            )
    lines.extend("", *[f"- Contract error: {error}" for error in contract_errors])
    (REPORT_DIR / "parity.md").write_text("\n".join(lines) + "\n")
    print(f"Parity PASS={sum(item['status'] == 'PASS' for item in results)} "
          f"FAIL={sum(item['status'] == 'FAIL' for item in results)} "
          f"SKIP={sum(item['status'] == 'SKIP' for item in results)}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
