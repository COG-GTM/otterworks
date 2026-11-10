# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdf==4.3.1", "openpyxl==3.1.5"]
# ///
"""
report-service behaviour baseline: capture and compare.

The committed baseline lives in src/test/resources/baseline/ and was captured from
the legacy stack (Java 8 / Spring Boot 2.5). Every upgrade ticket re-runs `compare`
against its own build to prove API contract and report output are unchanged.

    uv run scripts/baseline.py compare  [--url http://localhost:8091]
    uv run scripts/baseline.py capture  [--url http://localhost:8091]   # regenerate baseline
    uv run scripts/baseline.py tests    [--reports target/surefire-reports] [--update]
    uv run scripts/baseline.py metrics  [--update]                       # image size + startup time

Run from services/report-service. See src/test/resources/baseline/README.md.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SERVICE_DIR.parent.parent
BASELINE_DIR = SERVICE_DIR / "src/test/resources/baseline"

# Fixed period so report bodies are reproducible. USER_ACTIVITY is used because it is
# the category whose upstream fallback works when auth-service is unreachable; the
# analytics/audit categories FAIL in that situation (recorded as its own case below).
PERIOD = {"dateFrom": "2026-01-01T00:00:00Z", "dateTo": "2026-01-31T00:00:00Z"}
REPORT_CASES = {
    "pdf": {"reportName": "Baseline User Activity", "category": "USER_ACTIVITY", "reportType": "PDF"},
    "csv": {"reportName": "Baseline User Activity", "category": "USER_ACTIVITY", "reportType": "CSV"},
    "xlsx": {"reportName": "Baseline User Activity", "category": "USER_ACTIVITY", "reportType": "EXCEL"},
}
UPSTREAM_DOWN_CASE = {"reportName": "Baseline Usage Analytics", "category": "USAGE_ANALYTICS", "reportType": "CSV"}

ISO_TS = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")
DISPLAY_TS = r"[A-Z][a-z]{2} \d{2}, \d{4} \d{2}:\d{2}"
GENERATED_LINE = re.compile(r"(Generated:\s*)" + DISPLAY_TS)
FILE_TS = re.compile(r"_\d{8}_\d{6}\.")

# Spring/JDK types SpringFox documents for the download endpoint's Resource return
# type. They are generator artefacts, not API DTOs, so they stay out of the summary.
FRAMEWORK_MODELS = {"Resource", "InputStream", "File", "URI", "URL"}

# Files whose differences fail `compare`. Everything else under contract/ and
# reports/ is informational: shown in the diff output but does not fail the run.
STRICT = [
    "reports/pdf.txt",
    "reports/csv.csv",
    "reports/xlsx.txt",
    "reports/metadata.json",
    "contract/api-summary.txt",
    "contract/health.json",
    "contract/actuator-health.json",
    "contract/actuator-info.json",
    "contract/behaviour.json",
]


# --------------------------------------------------------------------------- HTTP


class Client:
    def __init__(self, url: str, headers: list[str]):
        self.url = url.rstrip("/")
        self.headers = {}
        for h in headers:
            k, _, v = h.partition(":")
            self.headers[k.strip()] = v.strip()

    def request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method, headers=dict(self.headers))
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def json(self, method: str, path: str, body: dict | None = None):
        status, _, raw = self.request(method, path, body)
        return status, (json.loads(raw) if raw else None)

    def wait_healthy(self, timeout: float = 120) -> float:
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                if self.request("GET", "/health")[0] == 200:
                    return time.monotonic() - start
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.25)
        raise SystemExit(f"{self.url}/health did not respond within {timeout}s")


# ------------------------------------------------------------------ normalisers


def mask(text: str) -> str:
    text = GENERATED_LINE.sub(r"\1<GENERATED>", text)
    return ISO_TS.sub("<TIMESTAMP>", text)


def normalise_pdf(raw: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    out = [f"pages: {len(reader.pages)}"]
    for i, page in enumerate(reader.pages, 1):
        out.append(f"--- page {i} ---")
        for line in (page.extract_text() or "").splitlines():
            line = " ".join(line.split())
            if line:
                out.append(mask(line))
    return "\n".join(out) + "\n"


def normalise_csv(raw: bytes) -> str:
    # Line-based on purpose: quoting and column order are part of the export format.
    return mask(raw.decode("utf-8"))


def normalise_xlsx(raw: bytes) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), data_only=False)
    out = []
    for ws in wb.worksheets:
        out.append(f"--- sheet {ws.title} ({ws.max_row}x{ws.max_column}) ---")
        for row in ws.iter_rows():
            label = None
            for cell in row:
                if cell.value is None:
                    continue
                v = cell.value
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                shown = "<GENERATED>" if label == "Generated:" else mask(str(v))
                out.append(f"{cell.coordinate}\t{type(v).__name__}\t{shown}")
                label = v
    return "\n".join(out) + "\n"


NORMALISERS = {"pdf": normalise_pdf, "csv": normalise_csv, "xlsx": normalise_xlsx}


def normalise_metadata(resp: dict) -> dict:
    strict = {k: v for k, v in resp.items() if k not in ("id", "createdAt", "completedAt", "fileSizeBytes", "errorMessage")}
    if strict.get("downloadUrl"):
        strict["downloadUrl"] = strict["downloadUrl"].replace(f"/{resp['id']}/", "/{id}/")
    return strict


def api_docs(client: Client) -> tuple[str, dict]:
    for path in ("/v2/api-docs", "/v3/api-docs"):
        status, body = client.json("GET", path)
        if status == 200 and isinstance(body, dict):
            return path, body
    raise SystemExit("no OpenAPI document at /v2/api-docs or /v3/api-docs")


def _ref_name(schema: dict | None) -> str:
    if not schema:
        return "-"
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if schema.get("type") == "array":
        return f"array<{_ref_name(schema.get('items'))}>"
    return schema.get("type", "object")


def _returns(op: dict) -> str:
    """Schema of the first documented 2xx response; framework/binary bodies collapse to 'binary'."""
    for code in sorted(c for c in op.get("responses", {}) if c.startswith("2")):
        r = op["responses"][code]
        schema = r.get("schema") or next(iter(r.get("content", {}).values()), {}).get("schema")
        if schema:
            name = _ref_name(schema)
            binary = name in FRAMEWORK_MODELS or (schema.get("type") == "string" and schema.get("format") == "binary")
            return "binary" if binary else name
    return "-"


def _prop_type(p: dict) -> str:
    if "$ref" in p:
        return _ref_name(p)
    t = p.get("type", "object")
    if t == "array":
        return f"array<{_prop_type(p.get('items', {}))}>"
    if p.get("format"):
        t += f"({p['format']})"
    if p.get("enum"):
        t += "[" + ",".join(sorted(p["enum"])) + "]"
    return t


def api_summary(doc: dict) -> tuple[str, str]:
    """Format-agnostic (Swagger 2 / OpenAPI 3) summary: operations, params, models.

    Returns (strict summary, informational documented-response-codes listing).
    """
    ops, responses = [], []
    for path, item in sorted(doc.get("paths", {}).items()):
        for method, op in sorted(item.items()):
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            params, body = [], "-"
            for p in op.get("parameters", []):
                if p.get("in") == "body":  # Swagger 2
                    body = _ref_name(p.get("schema"))
                    continue
                schema = p.get("schema", p)
                params.append(f"{p['name']}:{p['in']}:{'required' if p.get('required') else 'optional'}:{_prop_type(schema)}")
            rb = op.get("requestBody", {}).get("content", {})  # OpenAPI 3
            if rb:
                body = _ref_name(next(iter(rb.values())).get("schema"))
            ops.append(f"{method.upper()} {path}\n  params: {', '.join(params) or '-'}\n  body: {body}\n  returns: {_returns(op)}")
            responses.append(f"{method.upper()} {path}: {' '.join(sorted(op.get('responses', {})))}")
    models = doc.get("definitions") or doc.get("components", {}).get("schemas", {})
    lines = ["# operations"] + ops + ["", "# models"]
    for name, m in sorted(models.items()):
        if name in FRAMEWORK_MODELS:
            continue
        req = set(m.get("required", []))
        lines.append(name)
        for pname, p in sorted(m.get("properties", {}).items()):
            lines.append(f"  {pname}: {_prop_type(p)}{' (required)' if pname in req else ''}")
    return "\n".join(lines) + "\n", "\n".join(responses) + "\n"


def prometheus_families(text: str) -> str:
    fams = sorted({line.split()[2] + " " + line.split()[3] for line in text.splitlines() if line.startswith("# TYPE ")})
    return "\n".join(fams) + "\n"


# ---------------------------------------------------------------------- capture


def submit_and_wait(client: Client, body: dict, timeout: float = 60) -> dict:
    status, created = client.json("POST", "/api/v1/reports", {**body, "requestedBy": "baseline", **PERIOD})
    if status != 202:
        raise SystemExit(f"POST /api/v1/reports returned {status}: {created}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, rep = client.json("GET", f"/api/v1/reports/{created['id']}")
        if rep["status"] in ("COMPLETED", "FAILED"):
            return rep
        time.sleep(0.5)
    raise SystemExit(f"report {created['id']} did not finish within {timeout}s")


def capture(client: Client, out: Path) -> None:
    created: list[int] = []
    try:
        _capture(client, out, created)
    finally:
        for report_id in created:  # leave no reports behind, even when the capture aborts
            client.request("DELETE", f"/api/v1/reports/{report_id}")


def _capture(client: Client, out: Path, created: list[int]) -> None:
    for sub in ("reports", "contract", "raw"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    write_json = lambda p, d: (out / p).write_text(json.dumps(d, indent=2, sort_keys=True) + "\n")

    # Contract: health + actuator first so the prometheus scrape sees a fixed request history.
    for name, path in (("health", "/health"), ("actuator-health", "/actuator/health"), ("actuator-info", "/actuator/info")):
        status, body = client.json("GET", path)
        write_json(f"contract/{name}.json", {"status": status, "body": body})
    status, _, prom = client.request("GET", "/actuator/prometheus")
    (out / "contract/actuator-prometheus-families.txt").write_text(f"status: {status}\n" + prometheus_families(prom.decode()))

    docs_path, doc = api_docs(client)
    if "host" in doc:
        doc["host"] = "<HOST>"
    write_json("contract/api-docs.json", {"path": docs_path, "document": doc})
    summary, codes = api_summary(doc)
    (out / "contract/api-summary.txt").write_text(summary)
    (out / "contract/api-responses.txt").write_text(codes)

    # Reports: one per format, downloaded and normalised.
    metadata, info = {}, {}
    for fmt, body in REPORT_CASES.items():
        rep = submit_and_wait(client, body)
        created.append(rep["id"])
        if rep["status"] != "COMPLETED":
            raise SystemExit(f"{fmt} report failed: {rep.get('errorMessage')}")
        status, headers, raw = client.request("GET", f"/api/v1/reports/{rep['id']}/download")
        headers = {k.lower(): v for k, v in headers.items()}
        (out / f"raw/report.{fmt}").write_bytes(raw)
        (out / f"reports/{fmt}{'.txt' if fmt != 'csv' else '.csv'}").write_text(NORMALISERS[fmt](raw))
        metadata[fmt] = {
            "report": normalise_metadata(rep),
            "download": {
                "status": status,
                "contentType": headers.get("content-type"),
                "contentDisposition": FILE_TS.sub("_<TS>.", headers.get("content-disposition", "")),
                "fileSizeMatchesDownload": bool(raw) and rep["fileSizeBytes"] == len(raw),
            },
        }
        info[fmt] = {"fileSizeBytes": rep["fileSizeBytes"], "downloadBytes": len(raw)}
    write_json("reports/metadata.json", metadata)

    # Behaviour: error paths and the upstream-unreachable path.
    failed = submit_and_wait(client, UPSTREAM_DOWN_CASE)
    created.append(failed["id"])
    info["upstreamDown"] = {"errorMessage": mask(failed.get("errorMessage") or "")}
    write_json("reports/info.json", info)
    list_status, listing = client.json("GET", "/api/v1/reports")
    behaviour = {
        "getUnknownReport": client.request("GET", "/api/v1/reports/999999999")[0],
        "downloadUnknownReport": client.request("GET", "/api/v1/reports/999999999/download")[0],
        "deleteUnknownReport": client.request("DELETE", "/api/v1/reports/999999999")[0],
        "createEmptyBody": client.request("POST", "/api/v1/reports", {})[0],
        "createMissingType": client.request(
            "POST", "/api/v1/reports", {"reportName": "x", "category": "USER_ACTIVITY", "requestedBy": "baseline"})[0],
        "listCompleted": {
            "status": list_status,
            "keys": sorted(listing.keys()),
            "itemKeys": sorted(listing["reports"][0].keys()) if listing.get("reports") else [],
        },
        # Legacy: 500 on PostgreSQL once a FAILED report (non-null @Lob errorMessage) is listed.
        "listByUser": client.request("GET", "/api/v1/reports?userId=baseline")[0],
        "listFailed": client.request("GET", "/api/v1/reports?status=FAILED")[0],
        "upstreamDownReport": normalise_metadata(failed),
    }
    deleted = created.pop(0)
    behaviour["deleteReport"] = client.request("DELETE", f"/api/v1/reports/{deleted}")[0]
    behaviour["getDeletedReport"] = client.request("GET", f"/api/v1/reports/{deleted}")[0]
    write_json("contract/behaviour.json", behaviour)


# ---------------------------------------------------------------------- compare


def diff_dirs(expected: Path, actual: Path) -> int:
    strict_failures = 0
    files = sorted({p.relative_to(expected).as_posix() for p in expected.rglob("*") if p.is_file()}
                   | {p.relative_to(actual).as_posix() for p in actual.rglob("*") if p.is_file()})
    for rel in files:
        if rel.startswith("raw/") or rel.startswith("tests/") or rel in ("README.md", "metrics.json"):
            continue
        e, a = expected / rel, actual / rel
        el = e.read_text().splitlines(keepends=True) if e.exists() else []
        al = a.read_text().splitlines(keepends=True) if a.exists() else []
        if el == al:
            print(f"  same      {rel}")
            continue
        strict = rel in STRICT
        strict_failures += strict
        print(f"  {'DIFFERENT' if strict else 'changed  '} {rel}{'' if strict else '  (informational)'}")
        sys.stdout.writelines("      " + l for l in difflib.unified_diff(el, al, "baseline/" + rel, "current/" + rel, n=1))
        if al and not al[-1].endswith("\n"):
            print()
    return strict_failures


# ------------------------------------------------------------------- surefire


def surefire_summary(reports: Path) -> str:
    lines, totals, jdk = [], [0, 0, 0, 0], None
    for xml in sorted(reports.glob("TEST-*.xml")):
        root = ET.parse(xml).getroot()
        jdk = jdk or next((p.get("value") for p in root.iter("property") if p.get("name") == "java.version"), None)
        t, f, e, s = (int(root.get(k, 0)) for k in ("tests", "failures", "errors", "skipped"))
        passed = t - f - e - s
        totals = [totals[0] + passed, totals[1] + f + e, totals[2] + s, totals[3] + t]
        lines.append(f"{root.get('name')}\tpassed={passed}\tfailed={f + e}\tskipped={s}")
    lines.insert(0, f"# surefire results, java.version={jdk}")
    lines.append(f"TOTAL\tpassed={totals[0]}\tfailed={totals[1]}\tskipped={totals[2]}\ttests={totals[3]}")
    return "\n".join(lines) + "\n"


def parse_summary(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if line and not line.startswith("#"):
            name, *kv = line.split("\t")
            out[name] = {k: int(v) for k, v in (x.split("=") for x in kv)}
    return out


# --------------------------------------------------------------------- metrics


def compose(*args: str) -> list[str]:
    return ["docker", "compose", "-f", str(REPO_ROOT / "docker-compose.infra.yml"), "-f", str(REPO_ROOT / "docker-compose.yml"), *args]


def measure(url: str, build: bool) -> dict:
    m = {}
    if build:
        start = time.monotonic()
        subprocess.run(compose("build", "report-service"), check=True)
        m["buildSeconds"] = round(time.monotonic() - start, 1)
    image = subprocess.run(compose("images", "-q", "report-service"), capture_output=True, text=True).stdout.strip()
    if not image:
        image = subprocess.run(compose("config", "--images"), capture_output=True, text=True, check=True).stdout
        image = next(l for l in image.splitlines() if "report-service" in l)
    size = int(subprocess.run(["docker", "image", "inspect", "-f", "{{.Size}}", image],
                              capture_output=True, text=True, check=True).stdout.strip())
    m["imageSizeBytes"] = size
    m["imageSizeMB"] = round(size / 1_000_000, 1)
    # `docker image ls` reports unpacked disk usage; .Size above is the content (layer) size.
    listing = subprocess.run(["docker", "image", "ls", "--no-trunc", "--format", "{{.ID}} {{.Repository}} {{.Size}}"],
                             capture_output=True, text=True).stdout.splitlines()
    m["imageDiskUsage"] = next((l.split()[-1] for l in listing
                                if image in l.split()[0] or image.split(":")[0] == l.split()[1]), None)
    subprocess.run(compose("up", "-d", "--wait", "postgres"), check=True)
    subprocess.run(compose("rm", "-sf", "report-service"), check=True, capture_output=True)
    start = time.monotonic()
    subprocess.run(compose("up", "-d", "--no-build", "--no-deps", "report-service"), check=True)
    Client(url, []).wait_healthy(180)
    m["startupSecondsToHealth"] = round(time.monotonic() - start, 1)
    started = None
    for _ in range(10):
        out = subprocess.run(["docker", "logs", "otterworks-report-service"], capture_output=True, text=True)
        started = re.search(r"Started \w+ in ([\d.]+) seconds", out.stdout + out.stderr)
        if started:
            break
        time.sleep(1)
    if started:
        m["springStartedInSeconds"] = float(started.group(1))
    jv = subprocess.run(["docker", "exec", "otterworks-report-service", "java", "-version"], capture_output=True, text=True)
    m["runtimeJava"] = (jv.stderr or jv.stdout).splitlines()[0] if (jv.stderr or jv.stdout) else None
    return m


# ------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("capture", "compare"):
        p = sub.add_parser(name)
        p.add_argument("--url", default="http://localhost:8091", help="report-service base URL")
        p.add_argument("-H", "--header", action="append", default=[], help="extra request header, e.g. 'Authorization: Bearer ...'")
        p.add_argument("--out", type=Path, help="capture: output dir (default: the baseline); compare: keep current capture here")
    p = sub.add_parser("tests")
    p.add_argument("--reports", type=Path, default=SERVICE_DIR / "target/surefire-reports")
    p.add_argument("--update", action="store_true")
    p = sub.add_parser("metrics")
    p.add_argument("--url", default="http://localhost:8091")
    p.add_argument("--no-build", action="store_true", help="measure the existing image instead of rebuilding")
    p.add_argument("--update", action="store_true")
    args = ap.parse_args()

    if args.cmd == "capture":
        out = args.out or BASELINE_DIR
        client = Client(args.url, args.header)
        client.wait_healthy()
        for sub_dir in ("reports", "contract", "raw"):
            shutil.rmtree(out / sub_dir, ignore_errors=True)
        capture(client, out)
        print(f"captured baseline into {out}")
        return 0

    if args.cmd == "compare":
        client = Client(args.url, args.header)
        client.wait_healthy()
        out = args.out or Path(tempfile.mkdtemp(prefix="report-baseline-"))
        capture(client, out)
        print(f"comparing {out} against {BASELINE_DIR}")
        failures = diff_dirs(BASELINE_DIR, out)
        print(f"\n{'PASS' if not failures else 'FAIL'}: {failures} strict difference(s)")
        if failures or args.out:
            print(f"current capture kept in {out}")
        else:
            shutil.rmtree(out, ignore_errors=True)
        return 1 if failures else 0

    if args.cmd == "tests":
        current = surefire_summary(args.reports)
        target = BASELINE_DIR / "tests/surefire-summary.txt"
        if args.update:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(current)
            print(current, end="")
            return 0
        base, cur = parse_summary(target.read_text()), parse_summary(current)
        problems = 0
        for name in sorted(set(base) | set(cur)):
            b, c = base.get(name), cur.get(name)
            if b == c:
                status = "same"
            elif c is None:
                status, problems = "MISSING", problems + 1
            elif c["failed"]:
                status, problems = "FAILING", problems + 1
            elif b and c["passed"] < b["passed"]:
                status, problems = "FEWER PASSING", problems + 1
            else:
                status = "changed"
            print(f"  {status:<13} {name}  baseline={b}  current={c}")
        print(f"\n{'PASS' if not problems else 'FAIL'}: {problems} regression(s)")
        return 1 if problems else 0

    if args.cmd == "metrics":
        m = measure(args.url, build=not args.no_build)
        target = BASELINE_DIR / "metrics.json"
        if args.update:
            base_meta = json.loads(target.read_text()) if target.exists() else {}
            target.write_text(json.dumps({**base_meta, **m}, indent=2) + "\n")
        elif target.exists():
            base = json.loads(target.read_text())
            for k, v in m.items():
                bv = base.get(k)
                delta = f"  ({v - bv:+.1f})" if isinstance(v, (int, float)) and isinstance(bv, (int, float)) else ""
                print(f"  {k}: baseline={bv} current={v}{delta}")
        print(json.dumps(m, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
