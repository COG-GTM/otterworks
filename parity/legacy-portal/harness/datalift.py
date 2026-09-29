"""Cutover drill on PostgreSQL: monolith -> handover -> services -> rollback.

See scenarios/datalift.yaml for the sequence. Unlike transcript replay, every
comparison here is strict equality of the parsed bodies, because it is the same
rows being read back through a different process.
"""

from __future__ import annotations

from typing import Any

import yaml

from . import client, pg, stack
from .scenario import BUSINESS_CONTEXTS, SCENARIO_DIR, diff, load_contexts, media_type, parse_body

EXPECTED_FLYWAY_HISTORY = ["0|BASELINE|t", "1|SQL|t"]


def load_drill() -> dict[str, dict[str, list[dict[str, Any]]]]:
    return yaml.safe_load((SCENARIO_DIR / "datalift.yaml").read_text(encoding="utf-8"))


def call(base_url: str, request: dict[str, Any]) -> dict[str, Any]:
    resp = client.send(base_url, request)
    return {"status": resp.status, "body": parse_body(resp.body, media_type(resp.content_type))}


def write_all(base_url: str, requests: list[dict[str, Any]], who: str) -> list[str]:
    problems = []
    for req in requests:
        got = call(base_url, req)
        if got["status"] >= 300:
            problems.append(f"{who}: {req['method']} {req['path']} -> {got['status']} {got['body']}")
    return problems


def read_all(base_url: str, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [call(base_url, req) for req in requests]


def compare_reads(
    step: str, requests: list[dict[str, Any]], before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    results = []
    for req, exp, act in zip(requests, before, after):
        problems = [f"status {act['status']} != {exp['status']}"] if exp["status"] != act["status"] else []
        problems += diff(exp["body"], act["body"])
        if exp["status"] >= 300:
            problems.append(f"baseline read failed with {exp['status']}")
        results.append({"step": step, "request": f"{req['method']} {req['path']}", "ok": not problems, "problems": problems})
    return results


def check(step: str, request: str, problems: list[str]) -> dict[str, Any]:
    return {"step": step, "request": request, "ok": not problems, "problems": problems}


def run() -> list[dict[str, Any]]:
    cfg = load_contexts()
    drill = load_drill()
    mono = cfg["monolith"]
    mono_spec = [(mono["name"], mono["jar"], mono["java"], mono["port"])]
    mono_args = {mono["name"]: pg.spring_args(mono["db_role"])}
    svc = {c: cfg["contexts"][c] for c in BUSINESS_CONTEXTS}
    svc_specs = [(s["service"], s["jar"], s["java"], s["port"]) for s in svc.values()]
    svc_args = {s["service"]: pg.spring_args(s["db_role"]) for s in svc.values()}
    results: dict[str, list[dict[str, Any]]] = {c: [] for c in BUSINESS_CONTEXTS}

    pg.reset("legacy")

    with stack.running(mono_spec, mono_args) as procs:
        url = procs[mono["name"]].base_url
        for ctx in BUSINESS_CONTEXTS:
            results[ctx].append(check("seed via monolith", f"{len(drill['seed'][ctx])} writes", write_all(url, drill["seed"][ctx], mono["name"])))
        before = {ctx: read_all(url, drill["reads"][ctx]) for ctx in BUSINESS_CONTEXTS}

    pg.psql(file=pg.HANDOVER)

    with stack.running(svc_specs, svc_args) as procs:
        for ctx, s in svc.items():
            url = procs[s["service"]].base_url
            after = read_all(url, drill["reads"][ctx])
            results[ctx] += compare_reads("services read monolith data", drill["reads"][ctx], before[ctx], after)
            results[ctx].append(
                check("cutover writes via service", f"{len(drill['cutover_writes'][ctx])} writes", write_all(url, drill["cutover_writes"][ctx], s["service"]))
            )
        served = {ctx: read_all(procs[s["service"]].base_url, drill["rollback_reads"][ctx]) for ctx, s in svc.items()}

    for ctx, s in svc.items():
        history = pg.psql(
            f'SELECT version, type, success FROM "{s["schema"]}".flyway_schema_history ORDER BY installed_rank', role=s["db_role"]
        ).stdout.split()
        results[ctx].append(
            check(
                "flyway adopted legacy schema",
                f"{s['schema']}.flyway_schema_history",
                [] if history == EXPECTED_FLYWAY_HISTORY else [f"history {history} != {EXPECTED_FLYWAY_HISTORY}"],
            )
        )
        foreign = [o["schema"] for c, o in svc.items() if c != ctx]
        leaks = []
        for schema in foreign:
            for table in pg.psql(f"SELECT tablename FROM pg_tables WHERE schemaname = '{schema}'").stdout.split():
                probe = pg.psql(f'SELECT count(*) FROM "{schema}"."{table}"', role=s["db_role"], check=False)
                if probe.returncode == 0 or "permission denied" not in probe.stderr:
                    leaks.append(f"{s['db_role']} can read {schema}.{table}")
        results[ctx].append(check("schema isolation", f"{s['db_role']} vs {', '.join(foreign)}", leaks))

    with stack.running(mono_spec, mono_args) as procs:
        url = procs[mono["name"]].base_url
        for ctx in BUSINESS_CONTEXTS:
            back = read_all(url, drill["rollback_reads"][ctx])
            results[ctx] += compare_reads("rollback: monolith reads service writes", drill["rollback_reads"][ctx], served[ctx], back)

    return [{"context": ctx, "target": "datalift", "baseUrl": pg.jdbc_url(), "results": results[ctx]} for ctx in BUSINESS_CONTEXTS]
