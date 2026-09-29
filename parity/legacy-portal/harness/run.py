"""Parity harness CLI.

  record   Boot the monolith, replay every scenario and write golden transcripts.
  verify   Replay transcripts against targets and fail on any divergence.

Targets for ``verify``:
  --against monolith          boot the monolith (golden determinism check)
  --against services          boot each extracted service jar (default)
  --target ctx=URL ...        replay against already-running endpoints
                              (docker compose, kind port-forward, gateway)
  --db postgres               boot jars against the local PostgreSQL from
                              docker-compose.postgres.yml instead of H2
                              (schemas are reset first)

  datalift  Cutover drill on PostgreSQL: seed via the monolith, hand schemas
            over to the service roles, read through the services, write
            through them, then roll back to the monolith (scenarios/datalift.yaml).

Scenarios run in declaration order against a single fresh instance per
context, so a target must start with an empty database.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import client, datalift, pg, stack
from .scenario import (
    BUSINESS_CONTEXTS,
    CONTEXT_ORDER,
    REPO_ROOT,
    ROOT,
    TRANSCRIPT_DIR,
    diff,
    expand,
    json_path_get,
    load_contexts,
    load_scenarios,
    media_type,
    normalise_body,
    parse_body,
)

REPORT_DIR = ROOT / "reports"


def git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def source_fingerprint(directory: str) -> str:
    """Hash of the monolith's main sources: a stale transcript is detectable."""
    h = hashlib.sha256()
    base = REPO_ROOT / directory / "src" / "main"
    for path in sorted(p for p in base.rglob("*") if p.is_file()):
        h.update(str(path.relative_to(base)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()[:16]


def play(base_url: str, context: str) -> list[dict[str, Any]]:
    """Run every scenario of a context and return normalised exchanges."""
    sf = load_scenarios(context)
    out: list[dict[str, Any]] = []
    for sc in sf.scenarios:
        variables: dict[str, Any] = {}
        for step in sc.steps:
            req = expand(step.request, variables)
            resp = client.send(base_url, req)
            mtype = media_type(resp.content_type)
            body = parse_body(resp.body, mtype)
            for var, path in step.capture.items():
                variables[var] = json_path_get(body, path)
            out.append(
                {
                    "scenario": sc.id,
                    "step": step.name,
                    "request": {k: v for k, v in req.items() if k in ("method", "path")},
                    "status": resp.status,
                    "mediaType": mtype,
                    "body": normalise_body(body, step.ignore),
                    "_elapsed_ms": round(resp.elapsed_ms, 1),
                }
            )
    return out


def transcript_path(context: str) -> Path:
    return TRANSCRIPT_DIR / f"{context}.json"


def cmd_record(args: argparse.Namespace) -> int:
    cfg = load_contexts()
    mono = cfg["monolith"]
    with stack.running([(mono["name"], mono["jar"], mono["java"], mono["port"])]) as procs:
        base = procs[mono["name"]].base_url
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        for context in CONTEXT_ORDER:
            exchanges = play(base, context)
            for ex in exchanges:
                ex.pop("_elapsed_ms")
            doc = {
                "context": context,
                "recordedFrom": {
                    "service": mono["name"],
                    "runtime": "Spring Boot 2.7.18 / Java 11",
                    "sourceFingerprint": source_fingerprint(mono["dir"]),
                    "gitRev": git_rev(),
                },
                "exchanges": exchanges,
            }
            transcript_path(context).write_text(json.dumps(doc, indent=2, sort_keys=False) + "\n", encoding="utf-8")
            print(f"recorded {len(exchanges):3d} exchanges -> {transcript_path(context).relative_to(REPO_ROOT)}")
    return 0


def compare(context: str, target_label: str, base_url: str) -> dict[str, Any]:
    golden = json.loads(transcript_path(context).read_text(encoding="utf-8"))
    actual = play(base_url, context)
    results = []
    for exp, act in zip(golden["exchanges"], actual):
        problems: list[str] = []
        if (exp["scenario"], exp["step"]) != (act["scenario"], act["step"]):
            problems.append(f"scenario drift: transcript has {exp['scenario']}/{exp['step']}; re-record")
        if exp["status"] != act["status"]:
            problems.append(f"status {act['status']} != expected {exp['status']}")
        if exp["mediaType"] != act["mediaType"]:
            problems.append(f"media type {act['mediaType']} != expected {exp['mediaType']}")
        problems.extend(diff(exp["body"], act["body"]))
        results.append(
            {
                "scenario": act["scenario"],
                "step": act["step"],
                "request": f"{act['request']['method']} {act['request']['path']}",
                "ok": not problems,
                "problems": problems,
                "elapsedMs": act["_elapsed_ms"],
            }
        )
    if len(golden["exchanges"]) != len(actual):
        results.append(
            {
                "scenario": "-",
                "step": "-",
                "request": "-",
                "ok": False,
                "problems": [f"{len(actual)} exchanges played, transcript has {len(golden['exchanges'])}"],
                "elapsedMs": 0,
            }
        )
    return {"context": context, "target": target_label, "baseUrl": base_url, "results": results}


def selected_contexts(args: argparse.Namespace) -> list[str]:
    return args.context or BUSINESS_CONTEXTS


def cmd_verify(args: argparse.Namespace) -> int:
    cfg = load_contexts()
    contexts = selected_contexts(args)
    stale = []
    fp = source_fingerprint(cfg["monolith"]["dir"])
    for ctx in [*contexts, "platform"]:
        rec = json.loads(transcript_path(ctx).read_text(encoding="utf-8"))["recordedFrom"]["sourceFingerprint"]
        if rec != fp:
            stale.append(ctx)
    if stale:
        print(f"ERROR: transcripts {stale} were recorded from different monolith sources; run `make parity-record`")
        return 2

    reports: list[dict[str, Any]] = []
    explicit = dict(t.split("=", 1) for t in (args.target or []))

    def run_against(urls: dict[str, str], label_for: dict[str, str]) -> None:
        for ctx in contexts:
            reports.append(compare(ctx, label_for[ctx], urls[ctx]))
            reports.append(compare("platform", label_for[ctx], urls[ctx]))

    if explicit:
        missing = [c for c in contexts if c not in explicit]
        if missing:
            print(f"ERROR: no --target for {missing}")
            return 2
        run_against(explicit, {c: explicit[c] for c in contexts})
    elif args.against == "monolith":
        mono = cfg["monolith"]
        mono_args = {}
        if args.db == "postgres":
            pg.reset("legacy")
            mono_args[mono["name"]] = pg.spring_args(mono["db_role"])
        with stack.running([(mono["name"], mono["jar"], mono["java"], mono["port"])], mono_args) as procs:
            url = procs[mono["name"]].base_url
            for ctx in contexts:
                reports.append(compare(ctx, mono["name"], url))
            reports.append(compare("platform", mono["name"], url))
    else:
        specs = [
            (cfg["contexts"][c]["service"], cfg["contexts"][c]["jar"], cfg["contexts"][c]["java"], cfg["contexts"][c]["port"])
            for c in contexts
        ]
        svc_args = {}
        if args.db == "postgres":
            pg.reset("split")
            svc_args = {cfg["contexts"][c]["service"]: pg.spring_args(cfg["contexts"][c]["db_role"]) for c in contexts}
        with stack.running(specs, svc_args) as procs:
            labels = {c: cfg["contexts"][c]["service"] for c in contexts}
            run_against({c: procs[labels[c]].base_url for c in contexts}, labels)

    return report(reports, args)


def cmd_datalift(args: argparse.Namespace) -> int:
    reports = datalift.run()
    args.against, args.target = "datalift", None
    return report(reports, args, summary="datalift checks passed")


def report(reports: list[dict[str, Any]], args: argparse.Namespace, summary: str = "exchanges match the monolith transcript") -> int:
    total = sum(len(r["results"]) for r in reports)
    failed = [(r, x) for r in reports for x in r["results"] if not x["ok"]]
    lines = ["| target | context | exchanges | result |", "|---|---|---:|---|"]
    for r in reports:
        bad = sum(1 for x in r["results"] if not x["ok"])
        lines.append(f"| {r['target']} | {r['context']} | {len(r['results'])} | {'PASS' if not bad else f'FAIL ({bad})'} |")
    print("\n".join(lines))
    for r, x in failed:
        print(f"\nFAIL {r['target']} {r['context']}/{x.get('scenario', '-')}/{x['step']}  {x['request']}")
        for p in x["problems"]:
            print(f"    {p}")
    print(f"\n{total - len(failed)}/{total} {summary}")

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    label = args.label or (args.against if not args.target else "targets")
    out = REPORT_DIR / f"parity-{label}-{stamp}.json"
    out.write_text(json.dumps({"gitRev": git_rev(), "reports": reports}, indent=2) + "\n", encoding="utf-8")
    (REPORT_DIR / f"parity-{label}-latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report: {out.relative_to(REPO_ROOT)}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="parity", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("record", help="record golden transcripts from the monolith")
    v = sub.add_parser("verify", help="replay transcripts against targets")
    v.add_argument("--against", choices=["monolith", "services"], default="services")
    v.add_argument("--context", action="append", choices=BUSINESS_CONTEXTS, help="limit to a context (repeatable)")
    v.add_argument("--target", action="append", metavar="CTX=URL", help="replay against a running endpoint")
    v.add_argument("--label", help="report file label")
    v.add_argument("--db", choices=["h2", "postgres"], default="h2", help="database the booted jars use")
    d = sub.add_parser("datalift", help="PostgreSQL cutover + rollback drill")
    d.add_argument("--label", default="datalift", help="report file label")
    args = parser.parse_args(argv)
    if args.cmd == "record":
        return cmd_record(args)
    if args.cmd == "datalift":
        return cmd_datalift(args)
    return cmd_verify(args)


if __name__ == "__main__":
    sys.exit(main())
