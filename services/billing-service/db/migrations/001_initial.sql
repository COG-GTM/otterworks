CREATE SCHEMA IF NOT EXISTS billing_svc;

CREATE TABLE IF NOT EXISTS billing_svc.tenants (
    id uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    tax_exempt boolean NOT NULL DEFAULT false,
    status text NOT NULL CHECK (status IN ('active', 'suspended'))
);

CREATE TABLE IF NOT EXISTS billing_svc.plans (
    id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    tier text NOT NULL CHECK (tier IN ('starter', 'growth', 'scale')),
    monthly_fee numeric(12, 2) NOT NULL CHECK (monthly_fee >= 0),
    included_units integer NOT NULL CHECK (included_units >= 0),
    overage_rate numeric(12, 6) NOT NULL CHECK (overage_rate >= 0),
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS billing_svc.subscriptions (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES billing_svc.tenants(id),
    plan_id uuid NOT NULL REFERENCES billing_svc.plans(id),
    starts_on date NOT NULL,
    ends_on date,
    status text NOT NULL CHECK (status IN ('active', 'suspended', 'cancelled')),
    suspended_on date,
    CHECK (ends_on IS NULL OR ends_on >= starts_on),
    CHECK (suspended_on IS NULL OR suspended_on >= starts_on)
);
