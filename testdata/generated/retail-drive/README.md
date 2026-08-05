# OtterWorks Enterprise Drive — synthetic app-data seed

Populates the **OtterWorks company drive** (an enterprise retailer of products
for otters — SalmonSnax, shrimp treats, fish-oil supplements, kelp snacks,
otter apparel and grooming textiles) into a live OtterWorks deployment so the
web UI shows a deep, realistic, browsable, multimodal drive: ~15 departments as
top-level folders, a nested subfolder tree (3–4 levels), a multi-format corpus
(xlsx/docx/pptx/pdf/csv/txt/md/json/png/jpg/svg + committed mp4 clips), and
rich-text documents.

Unlike the schema-based harness in `testdata/generated/seed` / `.../golden`
(which writes relational rows into an `otterworks_<ns>` **schema**), this seed
creates **real application data through the public API gateway**:

| Resource | Service | Backing store |
|----------|---------|---------------|
| Folders  | file-service `/api/v1/folders` | DynamoDB (folders table) |
| Files    | file-service `/api/v1/files/upload` | DynamoDB (metadata) + S3 (bytes) |
| Documents| document-service `/api/v1/documents` | Postgres `public` |

All resources are owned by one shared account (credentials come from the
`DRIVE_EMAIL` / `DRIVE_PASSWORD` secrets) so the result is a single enterprise
drive. The data is **synthetic** — no real people, customers, or PII.

## Files

- `catalog.py` — the shared ~40-SKU product catalog + market price model.
  Loads the committed OTD-15 contract CSVs (see below) and exposes
  `price_on` / `cogs_usd` / `margin_pct`. **Fails fast** if
  `testdata/market-series/` is missing — figures never fall back to random.
- `taxonomy.py` — the department/subfolder/file-template definition (data-driven;
  templates expand over years, quarters, regions, stores, suppliers, campaigns,
  categories, skus). Suppliers/categories/SKUs come from `catalog.py`. Edit this
  to reshape the drive.
- `filegen.py` — produces real, openable bytes for each file type. Every
  financial figure comes from `catalog.py`. Multimodal builders: matplotlib
  chart PNGs (`kind: chart`), reportlab platypus PDFs with tables + embedded
  images (`kind: contract|spec_sheet|invoice`), image-bearing pptx decks,
  per-SKU product-art PNG/SVG.
- `assets/` — 3 tiny committed MP4 clips (video/mp4, <20 KB each), uploaded
  into the folders listed in `taxonomy.ASSET_PLACEMENTS` (the web app previews
  them with a native `<video>` player).
- `generate_drive.py` — logs in, walks the taxonomy for the requested
  departments, creates folders/files/documents, then uploads the committed
  assets. **Idempotent** (skips folders, files, and documents that already
  exist) and **shardable** by department.
- `tests/` — self-contained pytest suite for the pipeline (no stack needed).

## Shared market-series contract (OTD-15)

All prices/costs/margins derive from `testdata/market-series/`
(`series.csv`, `baseline_prices.csv`, `products.csv`), the committed dataset
**owned by OTD-15** and also consumed by the analytics-service margins
dashboard. `catalog.py` reads the CSVs verbatim and reimplements the
documented deterministic extension: past the last baseline date each series is
extended with a per-day seeded random walk using a bit-exact port of
`java.util.Random.nextGaussian` with `seed = series_code.hashCode ^ epochDay`
and the fixed per-series daily sigmas from the market-series README — so the
drive artifacts and the analytics dashboard produce **identical numbers** for
any date. The margin model is likewise the one locked by OTD-15:

```
commodity_cost_usd = commodity_price(native) × fx_to_usd × content_kg
freight_cost_usd   = (DREWRY_WCI_USD_FEU / 25000 kg-per-FEU) × freight_kg
cogs_usd           = (commodity_cost_usd + freight_cost_usd) × (1 + overhead_pct/100)
margin_pct         = (list_price_usd − cogs_usd) / list_price_usd × 100
```

## Run

```bash
pip install -r requirements.txt

# preview volume (nothing written)
python generate_drive.py --gateway http://<gw> --email x --password x \
    --departments all --scale 1.0 --dry-run

# populate one department (shard) ...
python generate_drive.py --gateway http://<gw-host>:8080 \
    --email "$DRIVE_EMAIL" --password "$DRIVE_PASSWORD" \
    --departments Finance --scale 1.0 --workers 6

# ... or the whole drive
python generate_drive.py --gateway http://<gw-host>:8080 \
    --email "$DRIVE_EMAIL" --password "$DRIVE_PASSWORD" \
    --departments all --scale 1.0
```

`--scale` multiplies per-axis breadth (default `1.0` ≈ 2,500 files across 15
departments; each file <5 MB, total corpus well under a few hundred MB).
Because every department is an independent top-level subtree and the generator
is idempotent, the work fans out safely across many parallel workers/sessions
all writing under the same owner.

### Reseeding after a content change

Idempotency is filename-based, so a renamed taxonomy **adds** files next to
old ones instead of replacing them. To pick up new content start from fresh
volumes (`docker compose ... down -v && make up`) and re-run the generator
with `--register`; the blueprint snapshot bake already starts from `down -v`,
so a rebuild picks the new content up automatically.

## Tests

```bash
pip install -r requirements.txt pytest
python -m pytest tests -q
```

## Seed-loader integration (seeding a live tenant)

`seed-loader.job.tpl.yaml` is a Kubernetes Job that runs this generator against
an in-cluster gateway on demand / after a spin-up, mirroring the golden
reference-data loader. It reads the drive credentials from the
`retail-drive-seed` Secret and passes `--register` so it bootstraps the account
on a fresh environment.

Each demo tenant is its own namespace (`otterworks-<id>`) with its own
api-gateway Service, so the manifest is a **template**: `./render-seed-job.sh`
stamps the namespace and gateway URL (and the scale / departments) for one
tenant and prints the manifest on stdout.

```bash
render-seed-job.sh <tenant-id> [scale] [departments]
```

### Seeding tenant `coggtm`

```bash
# 1. credentials for the drive account, IN THE TENANT NAMESPACE
kubectl -n otterworks-coggtm create secret generic retail-drive-seed \
    --from-literal=DRIVE_EMAIL='<email>' \
    --from-literal=DRIVE_PASSWORD='<password>'

# 2. render the Job for this tenant and apply it
#    -> namespace otterworks-coggtm
#    -> GATEWAY_URL http://api-gateway.otterworks-coggtm.svc.cluster.local:8080
testdata/generated/retail-drive/render-seed-job.sh coggtm 0.1 | kubectl apply -f -

# 3. follow it
kubectl -n otterworks-coggtm logs -f job/retail-drive-seed-loader
```

Any tenant works the same way — `render-seed-job.sh <id>`. For a single-tenant
deploy (namespace `otterworks`, not derived from a tenant id) override the
namespace: `TENANT_NAMESPACE=otterworks render-seed-job.sh otterworks | kubectl apply -f -`.

Notes:

- **Scale.** `1.0` (the default) is the whole drive: ~2,445 files / 15
  departments, tens of minutes of uploads. `0.1` (~110 files) is enough to make
  every screen look real and finishes quickly.
- **Departments.** `all`, or a comma-separated subset of the names in
  `taxonomy.py`, matched exactly — three of them contain an ampersand, so quote
  the argument: `render-seed-job.sh coggtm 1.0 'Supply Chain & Logistics'`.
- **Re-running.** The generator is idempotent, but a Job's pod template is not
  mutable — `kubectl -n otterworks-<id> delete job retail-drive-seed-loader`
  before re-applying at a different scale. Deleting a loader that is still
  uploading throws that run's progress away and starts from the beginning; the
  dashboard path refuses to do so unless the runner is given `SEED_FORCE=true`.
- **A suspended tenant cannot be seeded.** The loader writes through the
  tenant's api-gateway, so wake a scaled-to-zero tenant first
  (`scripts/tenant-scale.sh <id> up`, or check it out from the dashboard).
- **Ephemeral tenants lose the data.** `coggtm` is a TTL'd tenant on
  `demo.otterworks.app`; the reaper deletes its namespace *and its database* at
  expiry, taking the seeded drive with it. Extend it
  (`tenant.sh extend coggtm 8h`) or make it perpetual
  (`tenant.sh persist coggtm true`) if the data has to outlive the demo.
- The loader pod counts against the tenant's `ResourceQuota` (it requests
  250m CPU / 512Mi) and lives in the tenant namespace, so it is visible as an
  extra pod in `tenant.sh status <id>` while it runs.
- **Idle-suspend can interrupt a long seed.** The reaper measures idleness from
  *ingress* requests, and the loader talks to the api-gateway Service directly —
  so on a tenant nobody is browsing, a full-scale run (longer than
  `IDLE_AFTER_SECONDS`, default 1h) can be scaled to zero underneath itself.
  Seed at a smaller scale, or keep a browser on the tenant while it runs.

### Without cluster access: `tenant.sh seed`

The provisioner credential most operators have can read the ops-dashboard
passcode and nothing else — no EKS access, so the `kubectl` commands above are
not available to it. The dashboard does the same work from inside the cluster:

```bash
./demo-platform/scripts/tenant.sh seed coggtm 0.1        # [scale] [departments]
./demo-platform/scripts/tenant.sh status coggtm

# a loader that is still uploading is left alone; restart it from scratch with
SEED_FORCE=true ./demo-platform/scripts/tenant.sh seed coggtm 0.1
```

That posts to `POST /api/tenants/coggtm/seed`, which launches a runner Job
(`OP=seed`) that upserts the `retail-drive-seed` Secret from the dashboard's own
`DRIVE_EMAIL`/`DRIVE_PASSWORD` (falling back to a Secret an operator already
created in the namespace) and applies this template into `otterworks-coggtm`.
Dashboard credentials **win**: when they are configured the runner overwrites a
hand-created Secret in the namespace, so a drive account registered earlier with
a different password stops working. Configure one or the other, not both.

`SEED_FORCE=true` sets `force` on that request, which skips the in-flight check
and lets the runner replace a loader that is still going. It is also the only way
out of a loader that never finishes *and* never fails — one whose pod the
tenant's `ResourceQuota` will not admit, say — which would otherwise leave every
later seed of that tenant refused as "already loading".

Two deployment prerequisites for that path, both one-off:

- the **runner image** must be built from a revision that has `OP=seed` and this
  template (`demo-platform/runner/README.md`), and the dashboard rolled onto it;
- the `demo-ops-dashboard` Secret must carry `DRIVE_EMAIL` / `DRIVE_PASSWORD`
  keys, otherwise every target namespace needs the `retail-drive-seed` Secret
  created by hand first (which needs cluster access).
