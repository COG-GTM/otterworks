---
name: oracle-billing-estate
description: How to run, seed, and query the legacy Oracle billing fixture (services/legacy-billing/db/oracle/) for the TP demo runbooks and migration work.
---

# Oracle billing estate (services/legacy-billing/db/oracle/)

- `make oracle-billing-up` starts Oracle Free on host port 52521. First boot pulls a
  multi-GB image (10–20 min) — never tear it down mid-session just to restart; reuse the
  container (`otterworks-oracle-billing-oracle-billing-1`). `make oracle-billing-seed NS=<ns>`
  is deterministic (seed derived from NS) and safe to re-run; ~2–4 min.
- No sqlplus client on the host. Run queries inside the container, using the container's
  internal port 1521 (NOT 52521, which is only the host mapping):
  `docker exec -i otterworks-oracle-billing-oracle-billing-1 bash -c "sqlplus -s ow_billing/ow_billing@localhost:1521/FREEPDB1" <<'EOF' ... EOF`
  The runbooks' literal `sqlplus ...@localhost:52521/FREEPDB1` only works if a host sqlplus
  client is installed.
- Expected NS=demo (SCALE=demo, seed 714559852): CUSTOMER_MASTER 25000 (155 columns),
  INVOICE_HEADER 18750, INVOICE_LINE 150000 (37 orphans), ENTITY_ATTR_VALUE 8333.
- TENANTS is shared across namespaces: 9 static baseline rows ("Tenant One".."Nine") plus
  60 per demo namespace named `<ns>::tenant-*`. A raw `SELECT COUNT(*) FROM tenants` after
  one demo seed shows 69, not 60 — filter `WHERE name LIKE '<ns>::%'` for the per-ns count.
- Companion stores (Postgres/DynamoDB/S3 via `make seed-legacy NS=<ns>`) validate with
  `make seed-legacy-validate NS=<ns>` (15/15 at demo scale). S3 bucket is
  `otterworks-data-lake` (no env suffix), LocalStack :4566, dummy creds
  (`AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1`).
