CREATE FUNCTION billing.fn_list_plans()
RETURNS TABLE (
    plan_id uuid,
    code text,
    tier text,
    monthly_fee numeric,
    included_units integer,
    overage_rate numeric
)
LANGUAGE sql
AS $$
    SELECT id, code, tier, monthly_fee, included_units, overage_rate
    FROM billing.plans
    WHERE active
    ORDER BY monthly_fee, code
$$;

CREATE FUNCTION billing.fn_entitlement(p_tenant_id uuid, p_on date)
RETURNS TABLE (
    tenant_id uuid,
    plan_code text,
    tier text,
    monthly_fee numeric,
    included_units integer,
    subscription_status text,
    effective_on date
)
LANGUAGE sql
AS $$
    SELECT t.id, p.code, p.tier, p.monthly_fee, p.included_units,
           s.status, GREATEST(s.starts_on, p_on)
    FROM billing.tenants t
    JOIN billing.subscriptions s ON s.tenant_id = t.id
    JOIN billing.plans p ON p.id = s.plan_id
    WHERE t.id = p_tenant_id
      AND s.starts_on <= p_on
      AND (s.ends_on IS NULL OR s.ends_on >= p_on)
    ORDER BY s.starts_on DESC
    LIMIT 1
$$;

CREATE PROCEDURE billing.sp_change_plan(
    p_tenant_id uuid,
    p_plan_id uuid,
    p_effective_on date
)
LANGUAGE plpgsql
AS $$
BEGIN
    UPDATE billing.subscriptions
       SET ends_on = p_effective_on - 1,
           status = CASE WHEN status = 'cancelled' THEN status ELSE 'active' END
     WHERE tenant_id = p_tenant_id
       AND ends_on IS NULL
       AND starts_on < p_effective_on;

    INSERT INTO billing.subscriptions (
        id, tenant_id, plan_id, starts_on, status
    ) VALUES (
        md5(p_tenant_id::text || p_plan_id::text || p_effective_on::text)::uuid,
        p_tenant_id, p_plan_id, p_effective_on, 'active'
    );
END
$$;
