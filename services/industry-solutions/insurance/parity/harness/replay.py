"""Replay recorded Oracle transcripts against commission-service and diff the results."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

import httpx
import jwt

from harness.common import (
    REPORTS,
    comparable_outcome,
    dump_json,
    fixture_sha,
    load_routes,
    load_scenarios,
    normalize,
    normalize_row,
    source_sha,
    transcript_path,
)


def token(secret: str, tenant: str, actor: str) -> str:
    claims = {
        "sub": actor,
        "tenant_id": tenant,
        "roles": ["ADMIN"],
        "type": "access",
        "exp": int(time.time()) + 600,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def _pick(names: list[str], inputs: dict[str, Any]) -> dict[str, Any]:
    return {name: inputs.get(name) for name in names}


def call(client: httpx.Client, contract: dict[str, Any], entrypoint: str,
         inputs: dict[str, Any]) -> dict[str, Any]:
    spec = contract["entrypoints"][entrypoint]
    path = contract["base_path"] + spec["path"].format(**inputs)
    query = {k: v for k, v in _pick(spec.get("query", []), inputs).items() if v is not None}
    body = _pick(spec.get("body", []), inputs) if spec.get("body") else None
    response = client.request(spec["method"], path, params=query, json=body)
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        error = payload.get("error") if isinstance(payload, dict) else None
        if not error:
            return {"status": "error", "ora_code": None, "message": f"HTTP {response.status_code}"}
        return {"status": "error", "ora_code": error["legacy_ora_code"], "message": error["message"]}
    if "rows" in spec:
        rows = payload[spec["rows"]["json_path"]]
        return {"status": "ok", "fields": {"rows": [normalize_row(r, spec["rows"]["columns"]) for r in rows]}}
    return {
        "status": "ok",
        "fields": {name: normalize(payload.get(name), kind) for name, kind in spec.get("fields", {}).items()},
    }


def probe(client: httpx.Client, contract: dict[str, Any], name: str,
          params: dict[str, Any]) -> list[dict[str, Any]] | str:
    spec = contract["probes"][name]
    target = spec["target"]
    path = contract["base_path"] + target["path"].format(**params)
    query = {k: v for k, v in _pick(target.get("query", []), params).items() if v is not None}
    response = client.get(path, params=query)
    if response.status_code >= 400:
        return f"HTTP {response.status_code}"
    payload = response.json()
    rows = payload[target["json_path"]] if target.get("json_path") else payload
    return [normalize_row(row, spec["columns"]) for row in rows]


def diff(expected: Any, actual: Any, where: str) -> list[str]:
    if expected == actual:
        return []
    return [f"{where}: expected {json.dumps(expected, sort_keys=True)} got {json.dumps(actual, sort_keys=True)}"]


def replay(client: httpx.Client, contract: dict[str, Any], scenario: dict[str, Any],
           transcript: dict[str, Any]) -> dict[str, Any]:
    reset = client.post(contract["base_path"] + "/internal/reset")
    reset.raise_for_status()
    problems: list[str] = []
    for index, step in enumerate(scenario.get("setup", [])):
        actual = call(client, contract, step["entrypoint"], step.get("inputs", {}))
        problems += diff(comparable_outcome(transcript["setup"][index]),
                         comparable_outcome(actual), f"setup[{index}]")
    expected_outcome = transcript["outcome"]
    expected_probes = {key: value["rows"] for key, value in transcript["probes"].items()}
    divergence = scenario.get("divergence")
    if divergence:
        target = divergence.get("target", {})
        expected_outcome = target.get("outcome", expected_outcome)
        expected_probes.update(target.get("probes", {}))
    actual = call(client, contract, scenario["entrypoint"], scenario.get("inputs", {}))
    problems += diff(comparable_outcome(expected_outcome), comparable_outcome(actual), "outcome")
    for index, item in enumerate(scenario.get("probes", [])):
        key = f"{item['probe']}:{index}"
        rows = probe(client, contract, item["probe"], item.get("params", {}))
        problems += diff(expected_probes[key], rows, f"probe {key}")
    status = "FAIL" if problems else ("DIVERGED-APPROVED" if divergence else "PASS")
    return {
        "scenario": scenario["id"],
        "module": scenario["module"],
        "entrypoint": scenario["entrypoint"],
        "status": status,
        "rule": divergence["rule"] if divergence else None,
        "problems": problems,
    }


def write_report(results: list[dict[str, Any]]) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    dump_json(REPORTS / "parity.json", results)
    counts: dict[str, int] = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    lines = [
        "# Insurance Commission Pay parity (Oracle PL/SQL transcripts vs commission-service)",
        "",
        f"source_sha `{source_sha()[:12]}` fixture_sha `{fixture_sha()[:12]}`",
        "",
        " | ".join(f"{k}: {v}" for k, v in sorted(counts.items())),
        "",
        "| Scenario | Entrypoint | Result | Notes |",
        "|---|---|---|---|",
    ]
    for result in results:
        note = result["rule"] or "; ".join(result["problems"])[:300]
        lines.append(f"| {result['scenario']} | `{result['entrypoint']}` | {result['status']} | {note or ''} |")
    (REPORTS / "parity.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module")
    parser.add_argument("--base-url", default=os.environ.get("COMMISSION_SVC_URL", "http://127.0.0.1:8098"))
    args = parser.parse_args()
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        print("JWT_SECRET must be set to mint parity tokens", file=sys.stderr)
        return 2
    contract = load_routes()
    results = []
    for scenario in load_scenarios(args.module):
        path = transcript_path(scenario)
        if not path.exists():
            results.append({"scenario": scenario["id"], "module": scenario["module"],
                            "entrypoint": scenario["entrypoint"], "status": "FAIL", "rule": None,
                            "problems": ["no transcript recorded"]})
            continue
        transcript = json.loads(path.read_text())
        stale = [name for name, sha in (("source_sha", source_sha()), ("fixture_sha", fixture_sha()))
                 if transcript.get(name) != sha]
        if stale:
            results.append({"scenario": scenario["id"], "module": scenario["module"],
                            "entrypoint": scenario["entrypoint"], "status": "FAIL", "rule": None,
                            "problems": [f"stale transcript: {', '.join(stale)} changed"]})
            continue
        headers = {"Authorization": f"Bearer {token(secret, contract['parity_tenant'], transcript['actor'])}"}
        with httpx.Client(base_url=args.base_url, headers=headers, timeout=30) as client:
            results.append(replay(client, contract, scenario, transcript))
    write_report(results)
    return 1 if any(r["status"] == "FAIL" for r in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
