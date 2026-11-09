CREATE TABLE IF NOT EXISTS billing_svc.usage_events (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES billing_svc.tenants(id),
    occurred_at timestamptz NOT NULL,
    units integer NOT NULL CHECK (units > 0),
    kind text NOT NULL CHECK (kind IN ('api', 'storage', 'compute'))
);

CREATE TABLE IF NOT EXISTS billing_svc.rating_periods (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES billing_svc.tenants(id),
    period_start date NOT NULL,
    period_end date NOT NULL,
    UNIQUE (tenant_id, period_start),
    CHECK (period_end >= period_start)
);

CREATE TABLE IF NOT EXISTS billing_svc.rating_results (
    id uuid PRIMARY KEY,
    period_id uuid NOT NULL REFERENCES billing_svc.rating_periods(id),
    subscription_id uuid NOT NULL REFERENCES billing_svc.subscriptions(id),
    used_units integer NOT NULL CHECK (used_units >= 0),
    quota_units integer NOT NULL CHECK (quota_units >= 0),
    rollover_units integer NOT NULL CHECK (rollover_units >= 0),
    billable_units integer NOT NULL CHECK (billable_units >= 0),
    overage_amount numeric(12, 2) NOT NULL CHECK (overage_amount >= 0),
    created_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS billing_svc.invoices (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES billing_svc.tenants(id),
    period_id uuid NOT NULL REFERENCES billing_svc.rating_periods(id),
    issued_at timestamptz NOT NULL,
    subtotal numeric(12, 2) NOT NULL CHECK (subtotal >= 0),
    tax numeric(12, 2) NOT NULL CHECK (tax >= 0),
    total numeric(12, 2) NOT NULL CHECK (total >= 0),
    status text NOT NULL CHECK (status IN ('draft', 'issued', 'paid', 'overdue'))
);

CREATE TABLE IF NOT EXISTS billing_svc.invoice_lines (
    id uuid PRIMARY KEY,
    invoice_id uuid NOT NULL REFERENCES billing_svc.invoices(id) ON DELETE CASCADE,
    line_no integer NOT NULL CHECK (line_no > 0),
    line_type text NOT NULL CHECK (line_type IN ('plan', 'usage', 'tax', 'credit')),
    description text NOT NULL,
    amount numeric(12, 2) NOT NULL,
    UNIQUE (invoice_id, line_no)
);

CREATE TABLE IF NOT EXISTS billing_svc.credit_notes (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES billing_svc.tenants(id),
    issued_on date NOT NULL,
    amount numeric(12, 2) NOT NULL CHECK (amount > 0),
    remaining_amount numeric(12, 2) NOT NULL CHECK (remaining_amount >= 0),
    CHECK (remaining_amount <= amount)
);

CREATE TABLE IF NOT EXISTS billing_svc.dunning_attempts (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES billing_svc.tenants(id),
    invoice_id uuid NOT NULL REFERENCES billing_svc.invoices(id),
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    scheduled_for date NOT NULL,
    status text NOT NULL CHECK (status IN ('scheduled', 'sent', 'skipped')),
    UNIQUE (invoice_id, attempt_no)
);

CREATE TABLE IF NOT EXISTS billing_svc.notifications (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES billing_svc.tenants(id),
    kind text NOT NULL CHECK (kind IN ('invoice', 'dunning', 'suspension')),
    sent_at timestamptz NOT NULL,
    UNIQUE (tenant_id, kind, sent_at)
);
