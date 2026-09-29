CREATE FUNCTION billing.fn_overdue_accounts(p_as_of date)
RETURNS TABLE (
    tenant_id uuid,
    invoice_id uuid,
    total numeric,
    days_overdue integer,
    tenant_status text
)
LANGUAGE sql
AS $$
    SELECT i.tenant_id, i.id, i.total, (p_as_of - i.issued_at::date)::integer,
           t.status
    FROM billing.invoices i
    JOIN billing.tenants t ON t.id = i.tenant_id
    WHERE i.status = 'overdue'
      AND i.issued_at::date < p_as_of
    ORDER BY i.issued_at, i.id
$$;

CREATE PROCEDURE billing.sp_schedule_dunning(p_as_of date)
LANGUAGE plpgsql
AS $$
DECLARE
    v_invoice record;
    v_next date;
    v_attempt integer;
BEGIN
    FOR v_invoice IN
        SELECT i.*
        FROM billing.invoices i
        WHERE i.status = 'overdue'
        ORDER BY i.issued_at, i.id
    LOOP
        SELECT COALESCE(max(attempt_no), 0) + 1 INTO v_attempt
        FROM billing.dunning_attempts
        WHERE invoice_id = v_invoice.id;
        v_next := p_as_of;
        IF extract(isodow FROM v_next) = 6 THEN
            v_next := v_next + 2;
        ELSIF extract(isodow FROM v_next) = 7 THEN
            v_next := v_next + 1;
        END IF;
        INSERT INTO billing.dunning_attempts (
            id, tenant_id, invoice_id, attempt_no, scheduled_for, status
        ) VALUES (
            md5(v_invoice.id::text || v_attempt::text)::uuid,
            v_invoice.tenant_id, v_invoice.id, v_attempt, v_next, 'scheduled'
        ) ON CONFLICT (invoice_id, attempt_no) DO NOTHING;
    END LOOP;
END
$$;

CREATE PROCEDURE billing.sp_suspend_overdue(p_as_of date)
LANGUAGE plpgsql
AS $$
DECLARE
    v_tenant record;
BEGIN
    FOR v_tenant IN
        SELECT DISTINCT i.tenant_id
        FROM billing.invoices i
        WHERE i.status = 'overdue'
          AND i.issued_at::date <= p_as_of - 14
    LOOP
        IF EXISTS (
            SELECT 1 FROM billing.tenants
            WHERE id = v_tenant.tenant_id AND status = 'active'
        ) THEN
            UPDATE billing.tenants
               SET status = 'suspended'
             WHERE id = v_tenant.tenant_id;
            UPDATE billing.subscriptions
               SET status = 'suspended', suspended_on = p_as_of
             WHERE tenant_id = v_tenant.tenant_id
               AND status = 'active';
            INSERT INTO billing.notifications (id, tenant_id, kind, sent_at)
            SELECT md5(v_tenant.tenant_id::text || 'suspension' || p_as_of::text)::uuid,
                   v_tenant.tenant_id, 'suspension', p_as_of::timestamptz
            WHERE NOT EXISTS (
                SELECT 1 FROM billing.notifications
                WHERE tenant_id = v_tenant.tenant_id
                  AND kind = 'suspension'
                  AND sent_at = p_as_of::timestamptz
            );
        END IF;
    END LOOP;
END
$$;
