CREATE FUNCTION billing.fn_usage_rating(
    p_tenant_id uuid,
    p_period_start date,
    p_period_end date
)
RETURNS TABLE (
    tenant_id uuid,
    period_start date,
    period_end date,
    used_units integer,
    quota_units integer,
    rollover_units integer,
    billable_units integer,
    first_tier_units integer,
    second_tier_units integer,
    overage_amount numeric
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_plan billing.plans%ROWTYPE;
    v_sub billing.subscriptions%ROWTYPE;
    v_used integer;
    v_prior integer;
    v_rollover integer;
    v_billable integer;
    v_first integer;
    v_second integer;
    v_amount numeric;
BEGIN
    SELECT s.* INTO v_sub
    FROM billing.subscriptions s
    WHERE s.tenant_id = p_tenant_id
      AND s.starts_on <= p_period_end
      AND (s.ends_on IS NULL OR s.ends_on >= p_period_start)
    ORDER BY s.starts_on DESC
    LIMIT 1;

    SELECT p.* INTO v_plan
    FROM billing.plans p
    WHERE p.id = v_sub.plan_id;

    SELECT COALESCE(sum(u.units), 0)::integer INTO v_used
    FROM billing.usage_events u
    WHERE u.tenant_id = p_tenant_id
      AND u.occurred_at::date BETWEEN p_period_start AND p_period_end;

    SELECT LEAST(2 * v_plan.included_units, COALESCE(sum(rr.rollover_units), 0))::integer
      INTO v_prior
    FROM billing.rating_results rr
    JOIN billing.rating_periods rp ON rp.id = rr.period_id
    WHERE rp.tenant_id = p_tenant_id
      AND rp.period_start < p_period_start
      AND rp.period_start >= p_period_start - interval '3 months';

    v_rollover := LEAST(v_prior, v_plan.included_units * 2);
    v_billable := GREATEST(v_used - v_rollover - v_plan.included_units, 0);
    v_first := LEAST(v_billable, 101);
    v_second := GREATEST(v_billable - 101, 0);
    v_amount := round(v_first * v_plan.overage_rate + v_second * v_plan.overage_rate * 1.5, 2);

    IF v_sub.status = 'suspended' AND v_sub.suspended_on IS NOT NULL
       AND v_sub.suspended_on BETWEEN p_period_start AND p_period_end THEN
        v_billable := round(v_billable * (
            (p_period_end - v_sub.suspended_on + 1)::numeric
            / (p_period_end - p_period_start + 1)
        ))::integer;
        v_amount := round(v_amount * (
            (p_period_end - v_sub.suspended_on + 1)::numeric
            / (p_period_end - p_period_start + 1)
        ), 2);
    END IF;

    RETURN QUERY SELECT p_tenant_id, p_period_start, p_period_end, v_used,
        v_plan.included_units, v_rollover, v_billable, v_first, v_second, v_amount;
END
$$;

CREATE FUNCTION billing.fn_usage_summary(
    p_tenant_id uuid,
    p_period_start date,
    p_period_end date
)
RETURNS TABLE (kind text, event_count bigint, units bigint)
LANGUAGE sql
AS $$
    SELECT u.kind, count(*), COALESCE(sum(u.units), 0)
    FROM billing.usage_events u
    WHERE u.tenant_id = p_tenant_id
      AND u.occurred_at::date BETWEEN p_period_start AND p_period_end
    GROUP BY u.kind
    ORDER BY u.kind
$$;

CREATE PROCEDURE billing.sp_finalize_rating(
    p_tenant_id uuid,
    p_period_start date,
    p_period_end date
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_period_id uuid := md5(p_tenant_id::text || p_period_start::text)::uuid;
    v_subscription_id uuid;
    v_rating record;
BEGIN
    SELECT id INTO v_subscription_id
    FROM billing.subscriptions
    WHERE tenant_id = p_tenant_id
      AND starts_on <= p_period_end
      AND (ends_on IS NULL OR ends_on >= p_period_start)
    ORDER BY starts_on DESC
    LIMIT 1;

    INSERT INTO billing.rating_periods (id, tenant_id, period_start, period_end)
    VALUES (v_period_id, p_tenant_id, p_period_start, p_period_end)
    ON CONFLICT (tenant_id, period_start) DO UPDATE
      SET period_end = EXCLUDED.period_end;

    SELECT * INTO v_rating
    FROM billing.fn_usage_rating(p_tenant_id, p_period_start, p_period_end);

    INSERT INTO billing.rating_results (
        id, period_id, subscription_id, used_units, quota_units, rollover_units,
        billable_units, overage_amount, created_at
    ) VALUES (
        md5(v_period_id::text)::uuid, v_period_id, v_subscription_id,
        v_rating.used_units, v_rating.quota_units,
        GREATEST(v_rating.quota_units - v_rating.used_units, 0),
        v_rating.billable_units, v_rating.overage_amount,
        p_period_end::timestamptz
    )
    ON CONFLICT (id) DO UPDATE SET
        used_units = EXCLUDED.used_units,
        rollover_units = EXCLUDED.rollover_units,
        billable_units = EXCLUDED.billable_units,
        overage_amount = EXCLUDED.overage_amount;
END
$$;
