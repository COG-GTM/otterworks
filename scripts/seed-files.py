# /// script
# requires-python = ">=3.11"
# dependencies = ["requests"]
# ///
"""
OtterWorks web-app dashboard seed script.

Logs in as the seed user through the API gateway, creates demo folders,
uploads generated files into them, and creates a few documents so the
client app dashboard (recent files / documents / activity / storage)
shows real data. Idempotent: existing folders/files/documents are
skipped by name.

Usage:
    make seed-files        (or: uv run scripts/seed-files.py)

Environment overrides (all optional):
    API_BASE      default http://localhost:8080/api/v1
    SEED_EMAIL    default admin@otterworks.dev
    SEED_PASSWORD default Admin123!
"""

import base64
import io
import json
import os
import struct
import sys
import zlib

import requests

API_BASE = os.getenv("API_BASE", "http://localhost:8080/api/v1").rstrip("/")
SEED_EMAIL = os.getenv("SEED_EMAIL", "admin@otterworks.dev")
SEED_PASSWORD = os.getenv("SEED_PASSWORD", "Admin123!")

# ── Generated file content ────────────────────────────────────────────────────


def _png() -> bytes:
    """Tiny valid 64x64 orange PNG (otter-mascot placeholder)."""
    w = h = 64
    raw = b"".join(b"\x00" + bytes([224, 122, 58]) * w for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _pdf(title: str, lines: list[str]) -> bytes:
    """Minimal single-page valid PDF."""
    stream = "BT /F1 18 Tf 50 760 Td ({}) Tj".format(title) + "".join(
        f" 0 -22 Td ({line}) Tj" for line in lines
    ) + " ET"
    stream_b = stream.encode("latin-1", "replace")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream_b), stream_b),
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objs, 1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % i + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1))
    for off in offsets:
        out.write(b"%010d 00000 n \n" % off)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref))
    return out.getvalue()


MD_ROADMAP = """# Q3 2026 Roadmap

## Themes
- **Reliability**: cut p95 upload latency below 400ms
- **Collaboration**: ship real-time co-editing beta
- **Admin**: self-serve tenant provisioning

## Milestones
| Date | Deliverable | Owner |
|------|-------------|-------|
| Jul 15 | Collab beta behind flag | Eng |
| Aug 01 | Storage quota GA | Platform |
| Sep 10 | Q3 launch review | PM |

## Risks
- LocalStack parity gaps for S3 multipart uploads
- Search index rebuild time on large tenants
"""

OKR_CSV = """objective,key_result,target,current,owner
Improve reliability,p95 upload latency (ms),400,612,platform-team
Improve reliability,failed upload rate (%),0.5,1.8,platform-team
Grow adoption,weekly active workspaces,1200,843,growth
Grow adoption,documents created per user/week,6,4.1,product
Ship collaboration,co-editing beta tenants,25,9,eng
"""

CHECKLIST = """Launch checklist — workspace sharing
[ ] Final security review sign-off
[ ] Load test share-link resolution (10k rps)
[ ] Draft release notes + in-app banner copy
[ ] Enable feature flag for 5% of tenants
[ ] Monitor error budget burn for 48h
[ ] Ramp to 100%
"""

BRAND_PDF = _pdf(
    "OtterWorks Brand Guidelines",
    ["Primary palette: Otter Orange #E07A3A, River Slate #3A4A5A",
     "Wordmark: always paired with the otter glyph",
     "Minimum clear space: 0.5x glyph height on all sides",
     "Do not recolor, outline, or stretch the mascot"],
)

LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 40">
  <circle cx="20" cy="20" r="16" fill="#E07A3A"/>
  <circle cx="15" cy="16" r="3" fill="#fff"/>
  <circle cx="25" cy="16" r="3" fill="#fff"/>
  <ellipse cx="20" cy="24" rx="6" ry="4" fill="#fff"/>
  <text x="44" y="26" font-family="Helvetica" font-size="16" fill="#3A4A5A">OtterWorks</text>
</svg>
"""

ARCH_NOTES = """# Architecture notes — file ingest path

Upload -> api-gateway -> file-service -> S3 (LocalStack) -> metadata in Postgres.
Event emitted on `file.uploaded`; notification-service fans out to collaborators.

## Open questions
- Move virus-scan to async worker? Currently synchronous on upload.
- Thumbnail generation for PDF/SVG lives in file-service; consider splitting.
"""

API_SPEC = json.dumps(
    {
        "openapi": "3.0.3",
        "info": {"title": "OtterWorks Files API", "version": "0.9.0"},
        "paths": {
            "/api/v1/files": {"get": {"summary": "List files", "parameters": ["owner_id", "folder_id"]}},
            "/api/v1/files/upload": {"post": {"summary": "Upload a file (multipart)"}},
            "/api/v1/files/{id}/share": {"post": {"summary": "Share a file"}},
        },
    },
    indent=2,
)

RUNBOOK = """# Deploy runbook

1. Merge to main; CI builds all service images.
2. `scripts/deploy-dev.sh` rolls services via Helm (rolling, 1 at a time).
3. Verify: `curl https://api.dev.otterworks.app/health` on each service.
4. Watch Grafana error-rate panel for 15 min before closing the deploy.

## Rollback
`helm rollback otterworks-<service>` — DB migrations are expand-only, so
rollbacks never require a schema restore mid-release.
"""

BUDGET_CSV = """category,item,q1,q2,q3,q4,owner
Infra,EKS cluster,4200,4200,4400,4400,platform
Infra,RDS (shared),1800,1800,1900,1900,platform
Tooling,Observability stack,600,600,650,650,sre
Tooling,CI runners,900,950,950,1000,devx
Headcount,Contract design,3000,1500,0,0,product
"""

INVOICE_PDF = _pdf(
    "Invoice #0042 — OtterWorks Cloud",
    ["Bill to: Acme Robotics", "Period: 2026-09-01 to 2026-09-30",
     "Storage (2.4 TB)............ $218.00", "Egress (310 GB)............ $27.90",
     "Support plan............... $99.00", "Total due: $344.90"],
)

README_ROOT = """# OtterWorks workspace

Seeded demo content. Folders map to teams; drag files in the UI to reorganize.
"""

NOTES_TXT = """Meeting notes — infra sync 10/13
- LocalStack S3 lifecycle rules still not honored; track upstream issue.
- Meilisearch index grows ~40MB/day; revisit ranking rules next sprint.
- Action: Vedant to draft quota-exceeded UX copy.
"""

# folder name -> list of (filename, bytes, mime)
TREE: dict[str | None, list[tuple[str, bytes, str]]] = {
    "Q3 Planning": [
        ("Q3-roadmap.md", MD_ROADMAP.encode(), "text/markdown"),
        ("okr-tracker.csv", OKR_CSV.encode(), "text/csv"),
        ("launch-checklist.txt", CHECKLIST.encode(), "text/plain"),
    ],
    "Design Assets": [
        ("brand-guidelines.pdf", BRAND_PDF, "application/pdf"),
        ("logo.svg", LOGO_SVG.encode(), "image/svg+xml"),
        ("otter-mascot.png", _png(), "image/png"),
    ],
    "Engineering": [
        ("architecture-notes.md", ARCH_NOTES.encode(), "text/markdown"),
        ("api-spec.json", API_SPEC.encode(), "application/json"),
        ("deploy-runbook.md", RUNBOOK.encode(), "text/markdown"),
    ],
    "Finance": [
        ("2026-budget.csv", BUDGET_CSV.encode(), "text/csv"),
        ("invoice-0042.pdf", INVOICE_PDF, "application/pdf"),
    ],
    None: [  # root
        ("README.md", README_ROOT.encode(), "text/markdown"),
        ("meeting-notes-10-13.txt", NOTES_TXT.encode(), "text/plain"),
        ("otter-mascot.png", _png(), "image/png"),
    ],
}

DOCUMENTS = [
    {
        "title": "Q3 Planning Notes",
        "content": "# Q3 planning\n\n- Prioritize collab beta\n- Defer mobile offline mode\n- Owner: product council\n",
    },
    {
        "title": "Onboarding Guide",
        "content": "# Welcome to OtterWorks\n\n1. Upload a file\n2. Share it with your team\n3. Install the desktop client\n",
    },
    {
        "title": "Incident Review — Upload Timeouts",
        "content": "# IR-2026-031\n\n**Impact**: 12% of uploads timed out over 40 min.\n\n**Root cause**: S3 multipart threshold misconfigured after config reload.\n\n**Follow-ups**: add canary upload probe; alert on p99, not mean.\n",
    },
    {
        "title": "Team Retro — Sprint 18",
        "content": "# Retro\n\nWent well: search latency fix, design QA loop.\nImprove: flaky e2e tests blocked two releases.\n",
    },
]

# ── API helpers ───────────────────────────────────────────────────────────────


def fail(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def login() -> tuple[str, str]:
    try:
        r = requests.post(
            f"{API_BASE}/auth/login",
            json={"email": SEED_EMAIL, "password": SEED_PASSWORD},
            timeout=15,
        )
    except requests.RequestException as e:
        fail(f"cannot reach API gateway at {API_BASE} ({e}) — is the stack up? Try `make up`.")
    if r.status_code != 200:
        fail(f"login failed for {SEED_EMAIL}: {r.status_code} {r.text[:300]} — "
             "is the stack seeded? Try `make up` (or `make up seed=1`).")
    token = r.json()["accessToken"]
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    sub = json.loads(base64.urlsafe_b64decode(payload))["sub"]
    return token, sub


def main() -> None:
    token, owner_id = login()
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    print(f"Logged in as {SEED_EMAIL} (owner_id={owner_id})")

    created: list[str] = []
    skipped: list[str] = []

    # Folders — reuse by name
    existing_folders = s.get(f"{API_BASE}/folders", params={"owner_id": owner_id}).json()["folders"]
    folder_ids: dict[str | None, str] = {None: None}
    for name in TREE:
        if name is None:
            continue
        match = next((f for f in existing_folders if f["name"] == name and f["parent_id"] is None), None)
        if match:
            folder_ids[name] = match["id"]
            skipped.append(f"folder:{name}")
        else:
            r = s.post(f"{API_BASE}/folders",
                       json={"name": name, "parent_id": None, "owner_id": owner_id})
            r.raise_for_status()
            folder_ids[name] = r.json()["id"]
            created.append(f"folder:{name}")

    # Files — skip if same name already in that folder
    existing_files = s.get(
        f"{API_BASE}/files", params={"owner_id": owner_id, "page_size": 500}
    ).json()["files"]
    have = {(f["name"], f.get("folder_id")) for f in existing_files}
    for folder_name, files in TREE.items():
        fid = folder_ids[folder_name]
        label = folder_name or "(root)"
        for fname, data, mime in files:
            if (fname, fid) in have:
                skipped.append(f"file:{label}/{fname}")
                continue
            parts = {"file": (fname, data, mime), "owner_id": owner_id}
            if fid:
                parts["folder_id"] = fid
            r = s.post(f"{API_BASE}/files/upload", files=parts)
            if r.status_code not in (200, 201):
                fail(f"upload {label}/{fname} failed: {r.status_code} {r.text[:300]}")
            created.append(f"file:{label}/{fname}")

    # Documents — skip if title exists
    docs = s.get(f"{API_BASE}/documents", params={"owner_id": owner_id, "size": 100}).json()
    have_titles = {d["title"] for d in docs.get("items", [])}
    for doc in DOCUMENTS:
        if doc["title"] in have_titles:
            skipped.append(f"doc:{doc['title']}")
            continue
        r = s.post(f"{API_BASE}/documents",
                   json={**doc, "content_type": "text/markdown", "owner_id": owner_id})
        if r.status_code not in (200, 201):
            fail(f"create document '{doc['title']}' failed: {r.status_code} {r.text[:300]}")
        created.append(f"doc:{doc['title']}")

    print(f"\nCreated ({len(created)}):")
    for c in created:
        print(f"  + {c}")
    print(f"Skipped, already present ({len(skipped)}):")
    for k in skipped:
        print(f"  = {k}")
    print("\nDone. Open http://localhost:3000/dashboard and log in as "
          f"{SEED_EMAIL} to see the data.")


if __name__ == "__main__":
    main()
