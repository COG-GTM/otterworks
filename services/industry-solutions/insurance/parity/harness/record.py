"""Record legacy PL/SQL behaviour from the Oracle Free fixture into immutable transcripts.

Each scenario runs against a freshly re-seeded fixture. Transcripts are written
only when absent unless ALLOW_RERECORD=1 and RERECORD_REASON is given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from decimal import Decimal
from typing import Any

import oracledb

from harness.common import (
    DB,
    dump_json,
    fixture_sha,
    load_routes,
    load_scenarios,
    normalize,
    normalize_row,
    scenario_sha,
    source_sha,
    transcript_path,
)

oracledb.defaults.fetch_decimals = True

OLTP_TABLES = (
    "commission_ledger",
    "commission_splits",
    "rate_audit_log",
    "commission_rates",
    "policies",
    "agents",
    "products",
)
DW_TABLES = ("fact_commission", "dim_period", "dim_product", "dim_agent")


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"{name} must be set (see services/industry-solutions/insurance/commission.mk)")
    return value


def connect(schema: str) -> oracledb.Connection:
    dsn = _env("INSURANCE_ORACLE_DSN")
    if schema == "oltp":
        return oracledb.connect(user="commission_pay", password=_env("INSURANCE_OLTP_PASSWORD"), dsn=dsn)
    return oracledb.connect(user="commission_dw", password=_env("INSURANCE_DW_PASSWORD"), dsn=dsn)


def seed_statements() -> list[str]:
    text = "\n".join(
        line for line in (DB / "oltp" / "02_seed.sql").read_text().splitlines()
        if not re.match(r"^\s*(--|WHENEVER\b|EXIT\b)", line, re.IGNORECASE)
    )
    statements = []
    for chunk in text.split(";"):
        statement = chunk.strip()
        if not statement or re.match(r"^(WHENEVER|EXIT|COMMIT)\b", statement, re.IGNORECASE):
            continue
        statements.append(statement)
    return statements


def reset(oltp: oracledb.Connection, dw: oracledb.Connection) -> None:
    with dw.cursor() as cursor:
        for table in DW_TABLES:
            cursor.execute(f"DELETE FROM {table}")
    dw.commit()
    with oltp.cursor() as cursor:
        for table in OLTP_TABLES:
            cursor.execute(f"DELETE FROM {table}")
        for statement in seed_statements():
            cursor.execute(statement)
    oltp.commit()


def _date(value: Any) -> dt.date | None:
    return None if value is None else dt.date.fromisoformat(str(value))


def _decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def call(entrypoint: str, inputs: dict[str, Any], actor: str, oltp: oracledb.Connection,
         dw: oracledb.Connection, contract: dict[str, Any]) -> dict[str, Any]:
    try:
        fields = _invoke(entrypoint, inputs, actor, oltp, dw, contract)
    except oracledb.DatabaseError as exc:
        oltp.rollback()
        dw.rollback()
        error = exc.args[0]
        first = str(getattr(error, "message", error)).splitlines()[0]
        return {
            "status": "error",
            "ora_code": -int(error.code),
            "message": re.sub(r"^ORA-\d+:\s*", "", first),
        }
    return {"status": "ok", "fields": fields}


def _invoke(entrypoint: str, inputs: dict[str, Any], actor: str, oltp: oracledb.Connection,
            dw: oracledb.Connection, contract: dict[str, Any]) -> dict[str, Any]:
    spec = contract["entrypoints"][entrypoint]
    cursor = oltp.cursor()
    if entrypoint == "commission_pkg.upsert_commission_rate":
        rate_id = cursor.var(int)
        cursor.execute(
            "BEGIN commission_pkg.upsert_commission_rate(:p, :a, :r, :f, :actor, :o); END;",
            p=inputs["product_code"], a=inputs.get("agent_id"), r=_decimal(inputs.get("rate_pct")),
            f=_date(inputs["effective_from"]), actor=actor, o=rate_id,
        )
        raw = {"rate_id": rate_id.getvalue()}
    elif entrypoint == "commission_pkg.end_commission_rate":
        cursor.execute(
            "BEGIN commission_pkg.end_commission_rate(:p, :a, :t, :actor); END;",
            p=inputs["product_code"], a=inputs.get("agent_id"),
            t=_date(inputs["effective_to"]), actor=actor,
        )
        raw = {}
    elif entrypoint == "commission_pkg.resolve_rate":
        rate_id = cursor.var(int)
        cursor.execute(
            "BEGIN :o := commission_pkg.resolve_rate(:p, :a, :d); END;",
            o=rate_id, p=inputs["product_code"], a=inputs.get("agent_id"), d=_date(inputs["as_of"]),
        )
        cursor.execute("SELECT rate_pct FROM commission_rates WHERE rate_id = :i", i=rate_id.getvalue())
        raw = {"rate_id": rate_id.getvalue(), "rate_pct": cursor.fetchone()[0]}
    elif entrypoint == "commission_pkg.set_commission_splits":
        splits = inputs.get("splits") or []
        binds: dict[str, Any] = {"policy": inputs["policy_id"], "actor": actor}
        items = []
        for index, item in enumerate(splits):
            binds[f"a{index}"] = item["agent_id"]
            binds[f"s{index}"] = _decimal(item.get("split_pct"))
            items.append(f"split_alloc_t(:a{index}, :s{index})")
        cursor.execute(
            f"BEGIN commission_pkg.set_commission_splits(:policy, split_alloc_tab({', '.join(items)}), :actor); END;",
            binds,
        )
        raw = {}
    elif entrypoint == "commission_pkg.calculate_policy_commission":
        cursor.execute(
            "BEGIN commission_pkg.calculate_policy_commission(:p, :m, :actor); END;",
            p=inputs["policy_id"], m=inputs["period_month"], actor=actor,
        )
        cursor.execute(
            """SELECT agent_id, rate_id, split_pct, base_premium, commission_amt
                 FROM commission_ledger WHERE policy_id = :p AND period_month = :m
                ORDER BY split_pct DESC, agent_id""",
            p=inputs["policy_id"], m=inputs["period_month"],
        )
        columns = [c[0] for c in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return {"rows": [normalize_row(row, spec["rows"]["columns"]) for row in rows]}
    elif entrypoint == "dw_etl_pkg.load_commission_facts":
        merged = dw.cursor().var(int)
        dw.cursor().execute(
            "BEGIN dw_etl_pkg.load_commission_facts(:m, :o); END;",
            m=inputs.get("period_month"), o=merged,
        )
        raw = {"rows_merged": merged.getvalue()}
    else:
        raise ValueError(f"unknown entrypoint {entrypoint}")
    return {name: normalize(raw[name], kind) for name, kind in spec.get("fields", {}).items()}


def probe(name: str, params: dict[str, Any], oltp: oracledb.Connection, dw: oracledb.Connection,
          contract: dict[str, Any]) -> list[dict[str, Any]]:
    spec = contract["probes"][name]
    connection = oltp if spec["oracle"]["schema"] == "oltp" else dw
    with connection.cursor() as cursor:
        if spec["oracle"].get("refresh_mv"):
            cursor.callproc("DBMS_MVIEW.REFRESH", [spec["oracle"]["refresh_mv"], "C"])
        cursor.execute(spec["oracle"]["sql"], params)
        columns = [c[0] for c in cursor.description]
        rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
    return [normalize_row(row, spec["columns"]) for row in rows]


def record(scenario: dict[str, Any], oltp: oracledb.Connection, dw: oracledb.Connection,
           contract: dict[str, Any]) -> dict[str, Any]:
    reset(oltp, dw)
    actor = scenario.get("actor", "parity")
    setup = [
        call(step["entrypoint"], step.get("inputs", {}), actor, oltp, dw, contract)
        for step in scenario.get("setup", [])
    ]
    outcome = call(scenario["entrypoint"], scenario.get("inputs", {}), actor, oltp, dw, contract)
    probes = {
        f"{item['probe']}:{index}": {
            "probe": item["probe"],
            "params": item.get("params", {}),
            "rows": probe(item["probe"], item.get("params", {}), oltp, dw, contract),
        }
        for index, item in enumerate(scenario.get("probes", []))
    }
    return {
        "scenario": scenario["id"],
        "module": scenario["module"],
        "entrypoint": scenario["entrypoint"],
        "inputs": scenario.get("inputs", {}),
        "actor": actor,
        "setup": setup,
        "outcome": outcome,
        "probes": probes,
        "source_sha": source_sha(),
        "fixture_sha": fixture_sha(),
        "scenario_sha": scenario_sha(scenario),
        "recorded_against": os.environ.get("INSURANCE_ORACLE_IMAGE", "oracle-free"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--module")
    parser.add_argument("--scenario")
    args = parser.parse_args()
    allow = os.environ.get("ALLOW_RERECORD") == "1"
    reason = os.environ.get("RERECORD_REASON", "")
    if allow and not reason:
        print("RERECORD_REASON is required with ALLOW_RERECORD=1", file=sys.stderr)
        return 2
    contract = load_routes()
    oltp, dw = connect("oltp"), connect("dw")
    written = skipped = 0
    for scenario in load_scenarios(args.module):
        if args.scenario and scenario["id"] != args.scenario:
            continue
        path = transcript_path(scenario)
        if path.exists() and not allow:
            skipped += 1
            continue
        transcript = record(scenario, oltp, dw, contract)
        if allow and path.exists():
            transcript["rerecord_reason"] = reason
        dump_json(path, transcript)
        written += 1
        print(f"recorded {scenario['id']}: {transcript['outcome']['status']}")
    reset(oltp, dw)
    print(f"transcripts written={written} kept={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
