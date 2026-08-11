-- The standalone target owns the logical billing_svc schema.
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS plans;
DROP TABLE IF EXISTS tenants;

CREATE TABLE tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    tax_exempt INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('active', 'suspended'))
);

CREATE TABLE plans (
    id TEXT PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    tier TEXT NOT NULL CHECK (tier IN ('starter', 'growth', 'scale')),
    monthly_fee NUMERIC NOT NULL CHECK (monthly_fee >= 0),
    included_units INTEGER NOT NULL CHECK (included_units >= 0),
    overage_rate NUMERIC NOT NULL CHECK (overage_rate >= 0),
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE subscriptions (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL REFERENCES tenants(id),
    plan_id TEXT NOT NULL REFERENCES plans(id),
    starts_on TEXT NOT NULL,
    ends_on TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'cancelled')),
    suspended_on TEXT,
    CHECK (ends_on IS NULL OR ends_on >= starts_on)
);
