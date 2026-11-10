# /// script
# requires-python = ">=3.10"
# ///
"""
report-service end-to-end check through the api-gateway (LBG-25).

For PDF, CSV and XLSX: create -> poll until COMPLETED -> download -> delete, plus list by
userId / status=FAILED, trailing-slash variants, validation and 401 without a JWT. The
gateway requires a JWT on /api/v1/reports, so the script signs an HS256 token with the
gateway's JWT_SECRET (the docker compose default unless --jwt-secret / $JWT_SECRET is set).
Needs analytics-service to be unreachable so the USAGE_ANALYTICS report FAILS.

    uv run scripts/gateway_e2e.py [--url http://localhost:8080] [--out DIR]
"""
import argparse, base64, hashlib, hmac, json, os, sys, time, urllib.error, urllib.request
from pathlib import Path

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--url", default="http://localhost:8080", help="api-gateway base URL")
ap.add_argument("--jwt-secret", default=os.environ.get("JWT_SECRET", "otterworks-local-dev-jwt-secret-change-me-in-production"))
ap.add_argument("--user", default="lbg25-e2e-user")
ap.add_argument("--out", type=Path, help="keep the downloaded reports here")
args = ap.parse_args()
GW = args.url.rstrip("/")
SECRET = args.jwt_secret.encode()
USER = args.user
def b64(d): return base64.urlsafe_b64encode(d).rstrip(b"=").decode()
now = int(time.time())
h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
p = b64(json.dumps({"sub": USER, "email": "lbg25@example.com", "iat": now, "exp": now + 3600}).encode())
sig = b64(hmac.new(SECRET, f"{h}.{p}".encode(), hashlib.sha256).digest())
TOKEN = f"{h}.{p}.{sig}"
results = []
def req(method, path, body=None, auth=True):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(GW + path, data=data, method=method)
    if data: r.add_header("Content-Type", "application/json")
    if auth: r.add_header("Authorization", "Bearer " + TOKEN)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
def check(name, ok, detail=""):
    results.append((name, ok)); print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))
MAGIC = {"PDF": (b"%PDF", "application/pdf"), "CSV": (None, "text/csv"),
         "EXCEL": (b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
st, _, _ = req("GET", "/api/v1/reports?userId=" + USER, auth=False)
check("no JWT -> 401", st == 401, st)
for fmt, (magic, ctype) in MAGIC.items():
    body = {"reportName": f"LBG-25 E2E {fmt}", "category": "USER_ACTIVITY", "reportType": fmt,
            "requestedBy": USER, "dateFrom": "2026-01-01T00:00:00Z", "dateTo": "2026-01-31T00:00:00Z"}
    st, _, b = req("POST", "/api/v1/reports", body)
    rep = json.loads(b); rid = rep.get("id")
    check(f"{fmt} create 202", st == 202, f"{st} id={rid} status={rep.get('status')}")
    t0 = time.time()
    while True:
        st, _, b = req("GET", f"/api/v1/reports/{rid}"); rep = json.loads(b)
        if rep["status"] in ("COMPLETED", "FAILED") or time.time() - t0 > 60: break
        time.sleep(0.5)
    check(f"{fmt} poll -> COMPLETED", rep["status"] == "COMPLETED", f"{rep['status']} in {time.time()-t0:.1f}s rows={rep.get('rowCount')} size={rep.get('fileSizeBytes')}")
    st, hd, data = req("GET", f"/api/v1/reports/{rid}/download")
    ct = hd.get("Content-Type", ""); cd = hd.get("Content-Disposition", "")
    okmagic = data.startswith(magic) if magic else any(l.count(",") >= 2 and not l.startswith('"#') for l in data.decode().splitlines())
    check(f"{fmt} download 200 + type + body", st == 200 and ct.startswith(ctype) and okmagic and len(data) > 0, f"{st} {ct} {len(data)}B {cd}")
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / f"report.{ {'PDF': 'pdf', 'CSV': 'csv', 'EXCEL': 'xlsx'}[fmt] }").write_bytes(data)
    st, _, _ = req("GET", f"/api/v1/reports/{rid}/"); check(f"{fmt} GET /{{id}}/ trailing slash 200", st == 200, st)
    st, _, _ = req("GET", f"/api/v1/reports/{rid}/download/"); check(f"{fmt} GET /download/ trailing slash 200", st == 200, st)
    st, _, _ = req("DELETE", f"/api/v1/reports/{rid}"); check(f"{fmt} delete 204", st == 204, st)
    st, _, _ = req("GET", f"/api/v1/reports/{rid}"); check(f"{fmt} GET after delete 404", st == 404, st)
    st, _, _ = req("DELETE", f"/api/v1/reports/{rid}"); check(f"{fmt} delete again 404", st == 404, st)
# FAILED report: analytics-service is not running
st, _, b = req("POST", "/api/v1/reports/", {"reportName": "LBG-25 E2E failing", "category": "USAGE_ANALYTICS",
         "reportType": "CSV", "requestedBy": USER})
check("POST /api/v1/reports/ (trailing slash) 202", st == 202, st)
fid = json.loads(b)["id"]; t0 = time.time()
while True:
    rep = json.loads(req("GET", f"/api/v1/reports/{fid}")[2])
    if rep["status"] in ("COMPLETED", "FAILED") or time.time() - t0 > 60: break
    time.sleep(0.5)
check("USAGE_ANALYTICS (analytics down) -> FAILED", rep["status"] == "FAILED", rep.get("errorMessage", "")[:90])
st, _, _ = req("GET", f"/api/v1/reports/{fid}/download"); check("download FAILED report 404", st == 404, st)
for path in ["/api/v1/reports?userId=" + USER, "/api/v1/reports/?userId=" + USER,
             "/api/v1/reports?status=FAILED", "/api/v1/reports/?status=FAILED", "/api/v1/reports", "/api/v1/reports/"]:
    st, _, b = req("GET", path)
    tot = json.loads(b).get("total") if st == 200 else b[:120]
    check(f"GET {path} 200", st == 200, f"{st} total={tot}")
st, _, b = req("GET", "/api/v1/reports?status=FAILED")
check("status=FAILED list contains failed report w/ errorMessage", any(r["id"] == fid and r.get("errorMessage") for r in json.loads(b)["reports"]))
st, _, _ = req("POST", "/api/v1/reports", {"reportName": ""}); check("invalid body 400", st == 400, st)
st, _, _ = req("GET", "/api/v1/reports/999999999"); check("unknown id 404", st == 404, st)
st, _, _ = req("GET", "/api/v1/reports?status=BOGUS"); check("bad status enum 400", st == 400, st)
st, _, _ = req("DELETE", f"/api/v1/reports/{fid}"); check("delete FAILED report 204", st == 204, st)
print(f"\n{sum(ok for _, ok in results)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok in results) else 1)
