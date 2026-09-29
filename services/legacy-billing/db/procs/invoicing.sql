CREATE FUNCTION billing.fn_invoice_preview(
    p_tenant_id uuid,
    p_period_start date,
    p_period_end date
)
RETURNS TABLE (
    line_no integer,
    line_type text,
    description text,
    amount numeric,
    tax_amount numeric,
    credit_applied numeric,
    total numeric
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_plan billing.plans%ROWTYPE;
    v_rating record;
    v_tax numeric;
    v_credit numeric;
BEGIN
    SELECT p.* INTO v_plan
    FROM billing.subscriptions s
    JOIN billing.plans p ON p.id = s.plan_id
    WHERE s.tenant_id = p_tenant_id
      AND s.starts_on <= p_period_end
      AND (s.ends_on IS NULL OR s.ends_on >= p_period_start)
    ORDER BY s.starts_on DESC LIMIT 1;

    SELECT * INTO v_rating
    FROM billing.fn_usage_rating(p_tenant_id, p_period_start, p_period_end);

    SELECT COALESCE(sum(remaining_amount), 0) INTO v_credit
    FROM billing.credit_notes
    WHERE tenant_id = p_tenant_id
      AND remaining_amount > 0;

    v_tax := CASE
        WHEN (SELECT tax_exempt FROM billing.tenants WHERE id = p_tenant_id)
        THEN 0
        ELSE (v_plan.monthly_fee + v_rating.overage_amount) * 0.0825
    END;

    RETURN QUERY
    SELECT 1, 'plan', v_plan.code, round(v_plan.monthly_fee, 2), 0::numeric,
           0::numeric, round(v_plan.monthly_fee, 2)
    UNION ALL
    SELECT 2, 'usage', 'usage overage', round(v_rating.overage_amount, 2), 0::numeric,
           0::numeric, round(v_rating.overage_amount, 2)
    UNION ALL
    SELECT 3, 'tax', 'regional tax', v_tax / 2, 0::numeric, 0::numeric, v_tax / 2
    UNION ALL
    SELECT 4, 'tax', 'local tax', v_tax / 2, 0::numeric, 0::numeric, v_tax / 2
    UNION ALL
    SELECT 5, 'credit', 'credit notes', 0::numeric, 0::numeric,
           LEAST(v_credit, round(v_plan.monthly_fee + v_rating.overage_amount + v_tax, 2)),
           -LEAST(v_credit, round(v_plan.monthly_fee + v_rating.overage_amount + v_tax, 2));
END
$$;

CREATE FUNCTION billing.fn_invoice_lines(p_invoice_id uuid)
RETURNS TABLE (
    line_no integer,
    line_type text,
    description text,
    amount numeric
)
LANGUAGE sql
AS $$
    SELECT line_no, line_type, description, amount
    FROM billing.invoice_lines
    WHERE invoice_id = p_invoice_id
    ORDER BY line_no
$$;

CREATE PROCEDURE billing.sp_issue_invoice(
    p_tenant_id uuid,
    p_period_start date,
    p_period_end date
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_period_id uuid := md5(p_tenant_id::text || p_period_start::text)::uuid;
    v_invoice_id uuid := md5(v_period_id::text || 'invoice')::uuid;
    v_line record;
    v_subtotal numeric := 0;
    v_tax numeric := 0;
    v_total numeric := 0;
    v_credit numeric := 0;
BEGIN
    CALL billing.sp_finalize_rating(p_tenant_id, p_period_start, p_period_end);
    INSERT INTO billing.invoices (
        id, tenant_id, period_id, issued_at, subtotal, tax, total, status
    ) VALUES (
        v_invoice_id, p_tenant_id, v_period_id, p_period_end::timestamptz,
        0, 0, 0, 'issued'
    )
    ON CONFLICT (id) DO UPDATE SET status = 'issued';

    DELETE FROM billing.invoice_lines WHERE invoice_id = v_invoice_id;
    FOR v_line IN
        SELECT * FROM billing.fn_invoice_preview(p_tenant_id, p_period_start, p_period_end)
    LOOP
        INSERT INTO billing.invoice_lines (
            id, invoice_id, line_no, line_type, description, amount
        ) VALUES (
            md5(v_invoice_id::text || v_line.line_no::text)::uuid,
            v_invoice_id, v_line.line_no, v_line.line_type, v_line.description,
            CASE WHEN v_line.line_type = 'credit'
                 THEN v_line.total ELSE v_line.amount END
        );
        IF v_line.line_type IN ('plan', 'usage') THEN
            v_subtotal := v_subtotal + round(v_line.amount, 2);
        ELSIF v_line.line_type = 'tax' THEN
            v_tax := v_tax + round(v_line.amount, 2);
        ELSIF v_line.line_type = 'credit' THEN
            v_credit := v_line.credit_applied;
        END IF;
    END LOOP;
    v_total := round(v_subtotal + v_tax - v_credit, 2);
    UPDATE billing.invoices
       SET subtotal = round(v_subtotal, 2), tax = round(v_tax, 2), total = v_total
     WHERE id = v_invoice_id;

    FOR v_line IN
        SELECT id, remaining_amount
        FROM billing.credit_notes
        WHERE tenant_id = p_tenant_id AND remaining_amount > 0
        ORDER BY issued_on, id
    LOOP
        EXIT WHEN v_credit <= 0;
        UPDATE billing.credit_notes
           SET remaining_amount = GREATEST(remaining_amount - v_credit, 0)
         WHERE id = v_line.id;
        v_credit := GREATEST(v_credit - v_line.remaining_amount, 0);
    END LOOP;
END
$$;
