#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdf==6.1.3", "openpyxl==3.1.5"]
# ///
"""Record or replay the report-service golden behaviour contract.

  uv run replay.py                 # replay against http://localhost:8091 and diff with fixtures/
  uv run replay.py --record        # re-record fixtures/ and files/ from a running instance
  uv run replay.py --base-url URL --api-docs-path /v3/api-docs

The service must run in standalone mode (analytics, audit and auth services unreachable) so
report data comes from the deterministic sample-data fallback. See README.md.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import openpyxl
from pypdf import PdfReader

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
FILES = HERE / "files"

GOLDEN_USER = "golden-fixture-user"
DATE_FROM = "2026-10-01T00:00:00Z"
DATE_TO = "2026-10-31T00:00:00Z"
MISSING_ID = 987654321
CATEGORIES = [
    "USAGE_ANALYTICS",
    "AUDIT_LOG",
    "STORAGE_SUMMARY",
    "USER_ACTIVITY",
    "COLLABORATION_METRICS",
    "SYSTEM_HEALTH",
    "COMPLIANCE",
]
TYPES = {"PDF": "pdf", "CSV": "csv", "EXCEL": "xlsx"}
# Fallback user-activity rows stamp last_login relative to "now".
VOLATILE_COLUMNS = {"last_login", "Last login"}
TIME_RELATIVE_CATEGORIES = {"USER_ACTIVITY", "STORAGE_SUMMARY"}
PROMETHEUS_FAMILIES = [
    "http_server_requests_seconds_count",
    "jvm_memory_used_bytes",
    "jvm_threads_live_threads",
    "process_uptime_seconds",
    "hikaricp_connections_active",
    "system_cpu_count",
]

TS = "<timestamp>"
# PDF text extraction splits the trailing "Z" into its own token, so it is optional here.
ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z?")
# The first lookup of an unresolvable host adds this suffix; later (JVM-cached) lookups do not.
DNS_DETAIL_RE = re.compile(r": Temporary failure in name resolution")
DISPLAY_TS_RE = re.compile(r"[A-Z][a-z]{2} \d{2}, \d{4} \d{2}:\d{2}")
FILE_TS_RE = re.compile(r"_\d{8}_\d{6}\.")


class Client:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def request(self, method: str, path: str, body=None, raw_body: bytes | None = None):
        data = raw_body
        headers = {"Accept": "*/*"}
        if body is not None:
            data = json.dumps(body).encode()
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


def header(headers: dict, name: str):
    for k, v in headers.items():
        if k.lower() == name.lower():
            return v
    return None


def parse_json(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return {"<non-json>": raw.decode(errors="replace")[:200]}


def norm_error(body):
    if isinstance(body, dict) and "timestamp" in body:
        body = dict(body, timestamp=TS)
    return body


class Recorder:
    def __init__(self, client: Client, api_docs_path: str, swagger_ui_path: str, files_dir: Path | None):
        self.c = client
        self.api_docs_path = api_docs_path
        self.swagger_ui_path = swagger_ui_path
        self.files_dir = files_dir
        self.results: dict[str, object] = {}
        self.ids: dict[int, str] = {}

    def add(self, name: str, value):
        self.results[name] = value

    def exchange(self, method, path, body=None, raw_body=None, normalize=lambda b: b, label=None):
        status, headers, raw = self.c.request(method, path, body, raw_body)
        ctype = header(headers, "Content-Type")
        return {
            "request": f"{method} {label or path}",
            "status": status,
            "content_type": ctype.split(";")[0] if ctype else None,
            "body": normalize(parse_json(raw)),
        }

    def norm_report(self, r):
        if not isinstance(r, dict):
            return r
        r = dict(r)
        key = self.ids.get(r.get("id"), r.get("id"))
        r["id"] = key
        for f in ("createdAt", "completedAt"):
            if r.get(f) is not None:
                r[f] = TS
        if r.get("errorMessage"):
            r["errorMessage"] = DNS_DETAIL_RE.sub("", r["errorMessage"])
        if r.get("downloadUrl"):
            r["downloadUrl"] = f"/api/v1/reports/{key}/download"
        if r.get("fileSizeBytes") is not None and r.get("reportType") != "CSV":
            r["fileSizeBytes"] = "<positive>" if r["fileSizeBytes"] > 0 else r["fileSizeBytes"]
        return r

    def norm_list(self, body):
        if not isinstance(body, dict) or "reports" not in body:
            return norm_error(body)
        mine = [self.norm_report(r) for r in body["reports"] if r.get("requestedBy") == GOLDEN_USER]
        return {"reports": mine, "total(golden user only)": len(mine)}

    # ----- scenarios -----

    def preclean(self):
        _, _, raw = self.c.request("GET", f"/api/v1/reports?userId={GOLDEN_USER}")
        for r in (parse_json(raw) or {}).get("reports", []):
            self.c.request("DELETE", f"/api/v1/reports/{r['id']}")

    def platform(self):
        self.add("health", self.exchange("GET", "/health"))
        self.add("actuator_root", self.exchange(
            "GET", "/actuator",
            normalize=lambda b: json.loads(json.dumps(b).replace(self.c.base, "<base>"))))
        self.add("actuator_health", self.exchange("GET", "/actuator/health"))
        self.add("actuator_info", self.exchange("GET", "/actuator/info"))
        self.add("actuator_env_not_exposed", self.exchange("GET", "/actuator/env", normalize=norm_error))

        status, headers, raw = self.c.request("GET", "/actuator/prometheus")
        names = {line.split("{")[0].split(" ")[0] for line in raw.decode().splitlines() if line and not line.startswith("#")}
        self.add("actuator_prometheus", {
            "request": "GET /actuator/prometheus",
            "status": status,
            "content_type": (header(headers, "Content-Type") or "").split(";")[0],
            "families_present": {f: f in names for f in PROMETHEUS_FAMILIES},
        })

        status, headers, raw = self.c.request("GET", self.api_docs_path)
        doc = parse_json(raw) or {}
        ops = sorted(
            f"{m.upper()} {p}"
            for p, item in (doc.get("paths") or {}).items()
            for m in item
            if m.lower() in {"get", "post", "put", "delete", "patch"}
        )
        self.add("api_docs", {
            "request": "GET <api-docs>",
            "status": status,
            "title": (doc.get("info") or {}).get("title"),
            "version": (doc.get("info") or {}).get("version"),
            "operations": ops,
        })
        if self.files_dir is not None and status == 200:
            (self.files_dir / "api-docs.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        status, headers, _ = self.c.request("GET", self.swagger_ui_path)
        self.add("swagger_ui", {
            "request": "GET <swagger-ui>",
            "status": status,
            "content_type": (header(headers, "Content-Type") or "").split(";")[0],
        })

    def errors(self):
        self.add("create_missing_fields", self.exchange("POST", "/api/v1/reports", body={}, normalize=norm_error))
        self.add("create_bad_enum", self.exchange("POST", "/api/v1/reports", body={
            "reportName": "x", "category": "NOPE", "reportType": "PDF", "requestedBy": GOLDEN_USER,
        }, normalize=norm_error))
        self.add("create_malformed_json", self.exchange(
            "POST", "/api/v1/reports", raw_body=b"{not json", normalize=norm_error))
        self.add("get_missing", self.exchange("GET", f"/api/v1/reports/{MISSING_ID}", normalize=norm_error))
        self.add("download_missing", self.exchange("GET", f"/api/v1/reports/{MISSING_ID}/download", normalize=norm_error))
        self.add("delete_missing", self.exchange("DELETE", f"/api/v1/reports/{MISSING_ID}", normalize=norm_error))
        self.add("list_bad_status", self.exchange("GET", "/api/v1/reports?status=BOGUS", normalize=norm_error))

    def reports(self):
        created: list[tuple[str, int, str, str]] = []
        for category in CATEGORIES:
            for rtype in TYPES:
                key = f"{category.lower()}_{rtype.lower()}"
                body = {
                    "reportName": f"Golden {category} {rtype}",
                    "category": category,
                    "reportType": rtype,
                    "requestedBy": GOLDEN_USER,
                    "dateFrom": DATE_FROM,
                    "dateTo": DATE_TO,
                }
                if category == "USAGE_ANALYTICS":
                    body["parameters"] = {"metric": "file_upload"}
                status, headers, raw = self.c.request("POST", "/api/v1/reports", body)
                resp = parse_json(raw)
                rid = resp.get("id") if isinstance(resp, dict) else None
                if rid is not None:
                    self.ids[rid] = key
                self.add(f"report_{key}_create", {
                    "request": "POST /api/v1/reports", "status": status, "body": self.norm_report(resp)})
                created.append((key, rid, category, rtype))

        for key, rid, category, rtype in created:
            final = None
            deadline = time.time() + 90
            while time.time() < deadline:
                _, _, raw = self.c.request("GET", f"/api/v1/reports/{rid}")
                final = parse_json(raw)
                if isinstance(final, dict) and final.get("status") in ("COMPLETED", "FAILED"):
                    break
                time.sleep(0.5)
            self.add(f"report_{key}_get", self.exchange(
                "GET", f"/api/v1/reports/{rid}", normalize=self.norm_report, label=f"/api/v1/reports/{{{key}}}"))
            self.add(f"report_{key}_download", self.download(key, rid, category, rtype))

        self.add("list_by_user", self.exchange("GET", f"/api/v1/reports?userId={GOLDEN_USER}", normalize=self.norm_list))
        self.add("list_completed", self.exchange("GET", "/api/v1/reports?status=COMPLETED", normalize=self.norm_list))
        self.add("list_failed", self.exchange("GET", "/api/v1/reports?status=FAILED", normalize=self.norm_list))
        self.add("list_default", self.exchange("GET", "/api/v1/reports", normalize=self.norm_list))

        for key, rid, _, _ in created:
            self.add(f"report_{key}_delete", self.exchange(
                "DELETE", f"/api/v1/reports/{rid}", normalize=norm_error, label=f"/api/v1/reports/{{{key}}}"))
        key, rid, _, _ = created[0]
        self.add("get_after_delete", self.exchange(
            "GET", f"/api/v1/reports/{rid}", normalize=norm_error, label=f"/api/v1/reports/{{{key}}}"))
        self.add("download_after_delete", self.exchange(
            "GET", f"/api/v1/reports/{rid}/download", normalize=norm_error, label=f"/api/v1/reports/{{{key}}}/download"))
        self.add("list_after_delete", self.exchange("GET", f"/api/v1/reports?userId={GOLDEN_USER}", normalize=self.norm_list))

    def download(self, key, rid, category, rtype):
        status, headers, raw = self.c.request("GET", f"/api/v1/reports/{rid}/download")
        disposition = header(headers, "Content-Disposition")
        out = {
            "request": f"GET /api/v1/reports/{{{key}}}/download",
            "status": status,
            "content_type": header(headers, "Content-Type"),
            "content_disposition": FILE_TS_RE.sub("_<timestamp>.", disposition) if disposition else None,
        }
        if status != 200:
            return out
        ext = TYPES[rtype]
        if self.files_dir is not None:
            (self.files_dir / f"{key}.{ext}").write_bytes(raw)
        if rtype == "CSV":
            out["content_length"] = int(header(headers, "Content-Length") or len(raw))
            out["content"] = extract_csv(raw)
        elif rtype == "EXCEL":
            out["content"] = extract_xlsx(raw)
        else:
            out["content"] = extract_pdf(raw, mask_iso=category in TIME_RELATIVE_CATEGORIES)
        return out


def extract_csv(raw: bytes):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    masked_cols: set[int] = set()
    out = []
    for row in rows:
        if row and row[0].startswith("# Generated:"):
            row = [DISPLAY_TS_RE.sub(TS, row[0])]
        elif not masked_cols and any(c in VOLATILE_COLUMNS for c in row):
            masked_cols = {i for i, c in enumerate(row) if c in VOLATILE_COLUMNS}
        elif masked_cols:
            row = [TS if i in masked_cols and v else v for i, v in enumerate(row)]
        out.append(row)
    return {"rows": out}


def extract_xlsx(raw: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    sheets = {}
    for ws in wb.worksheets:
        rows = []
        masked_cols: set[int] = set()
        for row in ws.iter_rows(values_only=True):
            row = list(row)
            while row and row[-1] is None:
                row.pop()
            if len(row) >= 2 and row[0] == "Generated:":
                row[1] = TS
            elif not masked_cols and any(c in VOLATILE_COLUMNS for c in row):
                masked_cols = {i for i, c in enumerate(row) if c in VOLATILE_COLUMNS}
            elif masked_cols:
                row = [TS if i in masked_cols and v else v for i, v in enumerate(row)]
            rows.append(row)
        sheets[ws.title] = {
            "rows": rows,
            "merged": sorted(str(r) for r in ws.merged_cells.ranges),
            "auto_filter": ws.auto_filter.ref,
        }
    return {"sheet_order": wb.sheetnames, "sheets": sheets}


def extract_pdf(raw: bytes, mask_iso: bool):
    reader = PdfReader(io.BytesIO(raw))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    text = re.sub(r"Generated: " + DISPLAY_TS_RE.pattern, "Generated: " + TS, text)
    if mask_iso:
        text = ISO_RE.sub(TS, text)
    # Tokens, not lines: line wrapping and page breaks are layout, not behaviour.
    return {"tokens": text.split()}


def dump(value) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base-url", default="http://localhost:8091")
    ap.add_argument("--record", action="store_true", help="overwrite fixtures/ and files/ with this run")
    ap.add_argument("--api-docs-path", default="/v2/api-docs")
    ap.add_argument("--swagger-ui-path", default="/swagger-ui/index.html")
    ap.add_argument("--actual-dir", type=Path, help="also write this run's normalized results here")
    args = ap.parse_args()

    files_dir = None
    if args.record:
        shutil.rmtree(FIXTURES, ignore_errors=True)
        shutil.rmtree(FILES, ignore_errors=True)
        FIXTURES.mkdir()
        FILES.mkdir()
        files_dir = FILES

    rec = Recorder(Client(args.base_url), args.api_docs_path, args.swagger_ui_path, files_dir)
    rec.preclean()
    rec.platform()
    rec.errors()
    rec.reports()

    if args.actual_dir:
        args.actual_dir.mkdir(parents=True, exist_ok=True)
        for name, value in rec.results.items():
            (args.actual_dir / f"{name}.json").write_text(dump(value))

    if args.record:
        for name, value in rec.results.items():
            (FIXTURES / f"{name}.json").write_text(dump(value))
        print(f"recorded {len(rec.results)} fixtures into {FIXTURES.relative_to(HERE)}/")
        return 0

    expected_names = {p.stem for p in FIXTURES.glob("*.json")}
    failures = 0
    for name in sorted(expected_names | rec.results.keys()):
        path = FIXTURES / f"{name}.json"
        if name not in rec.results:
            print(f"FAIL {name}: fixture exists but the replay produced nothing")
            failures += 1
            continue
        if not path.exists():
            print(f"FAIL {name}: no fixture recorded for this case")
            failures += 1
            continue
        expected, actual = path.read_text(), dump(rec.results[name])
        if expected == actual:
            print(f"PASS {name}")
        else:
            failures += 1
            print(f"FAIL {name}")
            sys.stdout.writelines(difflib.unified_diff(
                expected.splitlines(True), actual.splitlines(True),
                f"fixtures/{name}.json", f"actual/{name}.json", n=2))
    total = len(expected_names | rec.results.keys())
    print(f"\n{total - failures}/{total} cases match the golden fixtures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
