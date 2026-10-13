-- Commission Pay target schema (PostgreSQL). Every table carries tenant_id and
-- row-level security is FORCED so even the owning role only sees the tenant
-- bound to the transaction via SET LOCAL app.tenant_id.
CREATE SCHEMA IF NOT EXISTS commission;

CREATE TABLE IF NOT EXISTS commission.tenants (
    tenant_id  text PRIMARY KEY,
    name       text NOT NULL
);

CREATE TABLE IF NOT EXISTS commission.agents (
    tenant_id   text    NOT NULL REFERENCES commission.tenants (tenant_id),
    agent_id    bigint  NOT NULL,
    agent_code  text    NOT NULL,
    full_name   text    NOT NULL,
    license_no  text    NOT NULL,
    status      text    NOT NULL DEFAULT 'ACTIVE'
                CHECK (status IN ('ACTIVE', 'SUSPENDED', 'TERMINATED')),
    hired_date  date    NOT NULL,
    PRIMARY KEY (tenant_id, agent_id),
    UNIQUE (tenant_id, agent_code),
    UNIQUE (tenant_id, license_no)
);

CREATE TABLE IF NOT EXISTS commission.products (
    tenant_id        text NOT NULL REFERENCES commission.tenants (tenant_id),
    product_code     text NOT NULL,
    product_name     text NOT NULL,
    line_of_business text NOT NULL
                     CHECK (line_of_business IN ('AUTO', 'HOME', 'LIFE', 'COMMERCIAL')),
    PRIMARY KEY (tenant_id, product_code)
);

CREATE TABLE IF NOT EXISTS commission.commission_rates (
    tenant_id      text          NOT NULL,
    rate_id        bigint        NOT NULL,
    product_code   text          NOT NULL,
    agent_id       bigint,
    rate_pct       numeric(5, 2) NOT NULL CHECK (rate_pct > 0 AND rate_pct <= 50),
    effective_from date          NOT NULL,
    effective_to   date,
    created_by     text          NOT NULL,
    created_at     timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, rate_id),
    FOREIGN KEY (tenant_id, product_code) REFERENCES commission.products (tenant_id, product_code),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES commission.agents (tenant_id, agent_id),
    CHECK (effective_to IS NULL OR effective_to >= effective_from)
);
-- One open rate per (product, agent|default). Unlike Oracle's UX_RATES_OPEN this
-- does not also forbid a second closed row (rule INS-RATE-009).
CREATE UNIQUE INDEX IF NOT EXISTS ux_rates_open
    ON commission.commission_rates (tenant_id, product_code, COALESCE(agent_id, -1))
    WHERE effective_to IS NULL;

CREATE TABLE IF NOT EXISTS commission.policies (
    tenant_id      text           NOT NULL,
    policy_id      bigint         NOT NULL,
    policy_no      text           NOT NULL,
    product_code   text           NOT NULL,
    holder_name    text           NOT NULL,
    annual_premium numeric(12, 2) NOT NULL CHECK (annual_premium > 0),
    issued_date    date           NOT NULL,
    status         text           NOT NULL DEFAULT 'IN_FORCE'
                   CHECK (status IN ('IN_FORCE', 'LAPSED', 'CANCELLED')),
    PRIMARY KEY (tenant_id, policy_id),
    UNIQUE (tenant_id, policy_no),
    FOREIGN KEY (tenant_id, product_code) REFERENCES commission.products (tenant_id, product_code)
);

CREATE TABLE IF NOT EXISTS commission.commission_splits (
    tenant_id  text          NOT NULL,
    policy_id  bigint        NOT NULL,
    agent_id   bigint        NOT NULL,
    split_pct  numeric(5, 2) NOT NULL CHECK (split_pct > 0 AND split_pct <= 100),
    PRIMARY KEY (tenant_id, policy_id, agent_id),
    FOREIGN KEY (tenant_id, policy_id) REFERENCES commission.policies (tenant_id, policy_id),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES commission.agents (tenant_id, agent_id)
);

CREATE TABLE IF NOT EXISTS commission.commission_ledger (
    tenant_id      text           NOT NULL,
    policy_id      bigint         NOT NULL,
    agent_id       bigint         NOT NULL,
    period_month   char(7)        NOT NULL CHECK (period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    rate_id        bigint         NOT NULL,
    split_pct      numeric(5, 2)  NOT NULL,
    base_premium   numeric(12, 2) NOT NULL,
    commission_amt numeric(12, 2) NOT NULL,
    calculated_at  timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, policy_id, agent_id, period_month),
    FOREIGN KEY (tenant_id, policy_id) REFERENCES commission.policies (tenant_id, policy_id),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES commission.agents (tenant_id, agent_id),
    FOREIGN KEY (tenant_id, rate_id) REFERENCES commission.commission_rates (tenant_id, rate_id)
);

CREATE TABLE IF NOT EXISTS commission.rate_audit_log (
    audit_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id    text        NOT NULL REFERENCES commission.tenants (tenant_id),
    action       text        NOT NULL,
    product_code text,
    agent_id     bigint,
    policy_id    bigint,
    detail       text,
    actor        text        NOT NULL,
    logged_at    timestamptz NOT NULL DEFAULT now()
);

-- Warehouse (DW_ETL_PKG target). Natural keys replace Oracle surrogate keys.
CREATE TABLE IF NOT EXISTS commission.dim_agent (
    tenant_id  text   NOT NULL,
    agent_id   bigint NOT NULL,
    agent_code text   NOT NULL,
    full_name  text   NOT NULL,
    status     text   NOT NULL,
    PRIMARY KEY (tenant_id, agent_id)
);

CREATE TABLE IF NOT EXISTS commission.dim_product (
    tenant_id        text NOT NULL,
    product_code     text NOT NULL,
    product_name     text NOT NULL,
    line_of_business text NOT NULL,
    PRIMARY KEY (tenant_id, product_code)
);

CREATE TABLE IF NOT EXISTS commission.dim_period (
    tenant_id    text     NOT NULL,
    period_month char(7)  NOT NULL,
    year_num     smallint NOT NULL,
    month_num    smallint NOT NULL,
    quarter_num  smallint NOT NULL,
    PRIMARY KEY (tenant_id, period_month)
);

CREATE TABLE IF NOT EXISTS commission.fact_commission (
    tenant_id      text           NOT NULL,
    policy_id      bigint         NOT NULL,
    agent_id       bigint         NOT NULL,
    period_month   char(7)        NOT NULL,
    product_code   text           NOT NULL,
    split_pct      numeric(5, 2)  NOT NULL,
    base_premium   numeric(12, 2) NOT NULL,
    commission_amt numeric(12, 2) NOT NULL,
    loaded_at      timestamptz    NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, policy_id, agent_id, period_month),
    FOREIGN KEY (tenant_id, agent_id) REFERENCES commission.dim_agent (tenant_id, agent_id),
    FOREIGN KEY (tenant_id, product_code) REFERENCES commission.dim_product (tenant_id, product_code),
    FOREIGN KEY (tenant_id, period_month) REFERENCES commission.dim_period (tenant_id, period_month)
);

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'tenants', 'agents', 'products', 'commission_rates', 'policies',
        'commission_splits', 'commission_ledger', 'rate_audit_log',
        'dim_agent', 'dim_product', 'dim_period', 'fact_commission'
    ] LOOP
        EXECUTE format('ALTER TABLE commission.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE commission.%I FORCE ROW LEVEL SECURITY', t);
        IF NOT EXISTS (
            SELECT 1 FROM pg_policies
             WHERE schemaname = 'commission' AND tablename = t AND policyname = 'tenant_isolation'
        ) THEN
            EXECUTE format(
                'CREATE POLICY tenant_isolation ON commission.%I '
                'USING (tenant_id = current_setting(''app.tenant_id'', true)) '
                'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))',
                t
            );
        END IF;
    END LOOP;
END
$$;
