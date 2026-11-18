-- Commission Pay test suite. Run as COMMISSION_PAY against FREEPDB1:
--   sqlplus commission_pay/commission_pay@localhost:1521/FREEPDB1 @run_tests.sql
-- Prints PASS/FAIL per case and exits non-zero if any case fails.
WHENEVER SQLERROR EXIT SQL.SQLCODE
SET SERVEROUTPUT ON SIZE UNLIMITED
SET FEEDBACK OFF

DECLARE
    g_failures  PLS_INTEGER := 0;
    l_rate_id   NUMBER;
    l_prev_to   DATE;
    l_num       NUMBER;
    l_num2      NUMBER;
    l_rows      PLS_INTEGER;
    l_rate_a    NUMBER;
    l_rate_b    NUMBER;
    l_policy_id NUMBER;

    PROCEDURE check_case (p_name IN VARCHAR2, p_ok IN BOOLEAN, p_detail IN VARCHAR2 DEFAULT NULL) IS
    BEGIN
        IF p_ok THEN
            DBMS_OUTPUT.PUT_LINE('PASS ' || p_name);
        ELSE
            g_failures := g_failures + 1;
            DBMS_OUTPUT.PUT_LINE('FAIL ' || p_name
                || CASE WHEN p_detail IS NOT NULL THEN ' -- ' || p_detail END);
        END IF;
    END check_case;

    PROCEDURE expect_error (p_name IN VARCHAR2, p_expected_code IN NUMBER) IS
    BEGIN
        check_case(p_name, FALSE, 'expected ORA' || p_expected_code || ' but no error raised');
    END expect_error;

    PROCEDURE check_raised (p_name IN VARCHAR2, p_expected_code IN NUMBER,
                            p_code IN NUMBER, p_errm IN VARCHAR2) IS
    BEGIN
        check_case(p_name, p_code = p_expected_code,
                   'expected ORA' || p_expected_code || ' got ' || p_errm);
    END check_raised;

    PROCEDURE expect_rate_rejected (p_name IN VARCHAR2, p_pct IN NUMBER) IS
        l_id NUMBER;
    BEGIN
        commission_pkg.upsert_commission_rate('AUTO-STD', NULL, p_pct, DATE '2026-02-01', 'tester', l_id);
        expect_error(p_name, -20001);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised(p_name, -20001, SQLCODE, SQLERRM);
    END expect_rate_rejected;

    PROCEDURE expect_split_rejected (p_name IN VARCHAR2, p_splits IN split_alloc_tab,
                                     p_expected_code IN NUMBER) IS
    BEGIN
        commission_pkg.set_commission_splits(3, p_splits, 'tester');
        expect_error(p_name, p_expected_code);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised(p_name, p_expected_code, SQLCODE, SQLERRM);
    END expect_split_rejected;

    FUNCTION audit_count (p_action IN VARCHAR2) RETURN NUMBER IS
        l_n NUMBER;
    BEGIN
        SELECT COUNT(*) INTO l_n FROM rate_audit_log WHERE action = p_action AND actor = 'tester';
        RETURN l_n;
    END audit_count;
BEGIN
    ---------------------------------------------------------------
    -- T1: upserting a rate closes the previous open rate for the scope
    ---------------------------------------------------------------
    commission_pkg.upsert_commission_rate('AUTO-STD', NULL, 8.50, DATE '2026-01-01', 'tester', l_rate_id);
    SELECT effective_to INTO l_prev_to
      FROM commission_rates
     WHERE product_code = 'AUTO-STD' AND agent_id IS NULL AND rate_id <> l_rate_id
       AND effective_from = DATE '2024-01-01';
    check_case('T1 rate upsert supersedes prior open rate',
               l_prev_to = DATE '2025-12-31',
               'prior effective_to=' || TO_CHAR(l_prev_to, 'YYYY-MM-DD'));

    ---------------------------------------------------------------
    -- T1b: same-day upsert amends the open rate in place (idempotent)
    ---------------------------------------------------------------
    commission_pkg.upsert_commission_rate('AUTO-STD', NULL, 8.75, DATE '2026-01-01', 'tester', l_rate_id);
    SELECT COUNT(*), MAX(rate_pct) INTO l_num, l_num2
      FROM commission_rates
     WHERE product_code = 'AUTO-STD' AND agent_id IS NULL AND effective_to IS NULL;
    check_case('T1b same-day upsert amends in place',
               l_num = 1 AND l_num2 = 8.75,
               'open rows=' || l_num || ' pct=' || l_num2);

    ---------------------------------------------------------------
    -- T2: rate outside (0, 50] is rejected
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.upsert_commission_rate('AUTO-STD', NULL, 55, DATE '2026-02-01', 'tester', l_rate_id);
        expect_error('T2 invalid rate rejected', -20001);
    EXCEPTION
        WHEN commission_pkg.e_invalid_rate THEN
            check_case('T2 invalid rate rejected', TRUE);
    END;

    ---------------------------------------------------------------
    -- T3: rate for an inactive agent is rejected
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.upsert_commission_rate('AUTO-STD', 4, 9, DATE '2026-02-01', 'tester', l_rate_id);
        expect_error('T3 suspended agent rate rejected', -20003);
    EXCEPTION
        WHEN commission_pkg.e_inactive_agent THEN
            check_case('T3 suspended agent rate rejected', TRUE);
    END;

    ---------------------------------------------------------------
    -- T4: splits must total exactly 100
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.set_commission_splits(3,
            split_alloc_tab(split_alloc_t(1, 70), split_alloc_t(2, 40)), 'tester');
        expect_error('T4 splits over 100 rejected', -20006);
    EXCEPTION
        WHEN commission_pkg.e_bad_split THEN
            check_case('T4 splits over 100 rejected', TRUE);
    END;

    ---------------------------------------------------------------
    -- T5: duplicate agents in a split are rejected
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.set_commission_splits(3,
            split_alloc_tab(split_alloc_t(1, 50), split_alloc_t(1, 50)), 'tester');
        expect_error('T5 duplicate split agent rejected', -20006);
    EXCEPTION
        WHEN commission_pkg.e_bad_split THEN
            check_case('T5 duplicate split agent rejected', TRUE);
    END;

    ---------------------------------------------------------------
    -- T6: valid two-way split replaces the allocation
    ---------------------------------------------------------------
    commission_pkg.set_commission_splits(3,
        split_alloc_tab(split_alloc_t(2, 65), split_alloc_t(3, 35)), 'tester');
    SELECT COUNT(*), SUM(split_pct) INTO l_num, l_num2
      FROM commission_splits WHERE policy_id = 3;
    check_case('T6 two-way split stored', l_num = 2 AND l_num2 = 100,
               'rows=' || l_num || ' total=' || l_num2);

    ---------------------------------------------------------------
    -- T7: agent-specific rate wins over product default
    ---------------------------------------------------------------
    SELECT rate_pct INTO l_num
      FROM commission_rates
     WHERE rate_id = commission_pkg.resolve_rate('AUTO-STD', 1, DATE '2025-06-15');
    check_case('T7 agent override beats default', l_num = 9.50, 'pct=' || l_num);
    SELECT rate_pct INTO l_num
      FROM commission_rates
     WHERE rate_id = commission_pkg.resolve_rate('AUTO-STD', 2, DATE '2025-06-15');
    check_case('T7b default used when no override', l_num = 8.00, 'pct=' || l_num);

    ---------------------------------------------------------------
    -- T8: three-way split commission math (policy 4, 2025-06)
    -- premium 9600/12 = 800. Agent 1: 800*9.5%*50% = 38.00
    -- Agent 2: 800*8%*30% = 19.20. Agent 3: 800*8%*20% = 12.80
    ---------------------------------------------------------------
    commission_pkg.calculate_policy_commission(4, '2025-06', 'tester');
    SELECT COUNT(*) INTO l_rows FROM commission_ledger WHERE policy_id = 4 AND period_month = '2025-06';
    check_case('T8 three-way split writes 3 ledger rows', l_rows = 3, 'rows=' || l_rows);
    SELECT commission_amt INTO l_num FROM commission_ledger
     WHERE policy_id = 4 AND agent_id = 1 AND period_month = '2025-06';
    check_case('T8a agent 1 amount', l_num = 38.00, 'amt=' || l_num);
    SELECT commission_amt INTO l_num FROM commission_ledger
     WHERE policy_id = 4 AND agent_id = 2 AND period_month = '2025-06';
    check_case('T8b agent 2 amount', l_num = 19.20, 'amt=' || l_num);
    SELECT commission_amt INTO l_num FROM commission_ledger
     WHERE policy_id = 4 AND agent_id = 3 AND period_month = '2025-06';
    check_case('T8c agent 3 amount', l_num = 12.80, 'amt=' || l_num);

    ---------------------------------------------------------------
    -- T9: recalculating a period replaces rows, not duplicates
    ---------------------------------------------------------------
    commission_pkg.calculate_policy_commission(4, '2025-06', 'tester');
    SELECT COUNT(*) INTO l_rows FROM commission_ledger WHERE policy_id = 4 AND period_month = '2025-06';
    check_case('T9 recalculation is idempotent', l_rows = 3, 'rows=' || l_rows);

    ---------------------------------------------------------------
    -- T10: lapsed policy cannot be calculated
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.calculate_policy_commission(5, '2025-06', 'tester');
        expect_error('T10 lapsed policy rejected', -20008);
    EXCEPTION
        WHEN commission_pkg.e_policy_not_active THEN
            check_case('T10 lapsed policy rejected', TRUE);
    END;

    ---------------------------------------------------------------
    -- T11: an empty split allocation is rejected
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.set_commission_splits(3, split_alloc_tab(), 'tester');
        expect_error('T11 empty split rejected', -20006);
    EXCEPTION
        WHEN commission_pkg.e_bad_split THEN
            check_case('T11 empty split rejected', TRUE);
    END;

    ---------------------------------------------------------------
    -- T12: audit trail rows were written
    ---------------------------------------------------------------
    SELECT COUNT(*) INTO l_num FROM rate_audit_log WHERE actor = 'tester';
    check_case('T12 audit trail written', l_num >= 4, 'rows=' || l_num);

    ---------------------------------------------------------------
    -- T13: unknown product / unknown agent are rejected on upsert
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.upsert_commission_rate('NO-SUCH', NULL, 5, DATE '2026-02-01', 'tester', l_rate_id);
        expect_error('T13 unknown product rejected', -20004);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised('T13 unknown product rejected', -20004, SQLCODE, SQLERRM);
    END;
    BEGIN
        commission_pkg.upsert_commission_rate('AUTO-STD', 999999, 5, DATE '2026-02-01', 'tester', l_rate_id);
        expect_error('T13b unknown agent rejected', -20002);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised('T13b unknown agent rejected', -20002, SQLCODE, SQLERRM);
    END;

    ---------------------------------------------------------------
    -- T14: rate bounds are (0, 50]: NULL, 0 and negative are rejected
    -- and leave the open default rate untouched
    ---------------------------------------------------------------
    expect_rate_rejected('T14 NULL rate rejected', NULL);
    expect_rate_rejected('T14b zero rate rejected', 0);
    expect_rate_rejected('T14c negative rate rejected', -1);
    expect_rate_rejected('T14d rate just above 50 rejected', 50.01);
    SELECT COUNT(*), MAX(rate_pct) INTO l_num, l_num2
      FROM commission_rates
     WHERE product_code = 'AUTO-STD' AND agent_id IS NULL AND effective_to IS NULL;
    check_case('T14e rejected rates leave open rate unchanged',
               l_num = 1 AND l_num2 = 8.75, 'open rows=' || l_num || ' pct=' || l_num2);

    ---------------------------------------------------------------
    -- T15: agent-specific rate lifecycle: create, supersede, then (on
    -- another scope) accept the 50 boundary, end, fall back to default.
    -- Each scope closes at most one rate: see the ux_rates_open note in
    -- cov90-industry-solutions.md.
    ---------------------------------------------------------------
    commission_pkg.upsert_commission_rate('HOME-PLUS', 3, 12, DATE '2026-03-01', 'tester', l_rate_a);
    SELECT rate_pct INTO l_num FROM commission_rates WHERE rate_id = l_rate_a;
    check_case('T15 agent-specific rate created', l_num = 12, 'pct=' || l_num);

    commission_pkg.upsert_commission_rate('HOME-PLUS', 3, 14, DATE '2026-04-01', 'tester', l_rate_b);
    SELECT effective_to INTO l_prev_to FROM commission_rates WHERE rate_id = l_rate_a;
    SELECT rate_pct INTO l_num FROM commission_rates WHERE rate_id = l_rate_b;
    check_case('T15a agent-specific rate supersedes prior override',
               l_num = 14 AND l_prev_to = DATE '2026-03-31',
               'pct=' || l_num || ' prior effective_to=' || TO_CHAR(l_prev_to, 'YYYY-MM-DD'));

    SELECT rate_pct INTO l_num FROM commission_rates
     WHERE rate_id = commission_pkg.resolve_rate('HOME-PLUS', 3, DATE '2026-03-15');
    SELECT rate_pct INTO l_num2 FROM commission_rates
     WHERE rate_id = commission_pkg.resolve_rate('HOME-PLUS', 3, DATE '2026-04-15');
    check_case('T15b resolve_rate honours effective dates', l_num = 12 AND l_num2 = 14,
               'mar=' || l_num || ' apr=' || l_num2);

    commission_pkg.upsert_commission_rate('TERM-20', 2, 50, DATE '2026-03-01', 'tester', l_rate_b);
    SELECT rate_pct INTO l_num FROM commission_rates
     WHERE rate_id = commission_pkg.resolve_rate('TERM-20', 2, DATE '2026-03-15');
    check_case('T15c boundary rate 50 accepted and in force', l_num = 50, 'pct=' || l_num);

    l_rows := audit_count('RATE_END');
    commission_pkg.end_commission_rate('TERM-20', 2, DATE '2026-06-30', 'tester');
    SELECT effective_to INTO l_prev_to FROM commission_rates WHERE rate_id = l_rate_b;
    SELECT COUNT(*) INTO l_num FROM commission_rates
     WHERE product_code = 'TERM-20' AND agent_id = 2 AND effective_to IS NULL;
    check_case('T15d end_commission_rate closes the open rate',
               l_prev_to = DATE '2026-06-30' AND l_num = 0,
               'effective_to=' || TO_CHAR(l_prev_to, 'YYYY-MM-DD') || ' open=' || l_num);
    check_case('T15e end_commission_rate is audited', audit_count('RATE_END') = l_rows + 1,
               'before=' || l_rows || ' after=' || audit_count('RATE_END'));

    SELECT rate_pct INTO l_num FROM commission_rates
     WHERE rate_id = commission_pkg.resolve_rate('TERM-20', 2, DATE '2026-07-15');
    check_case('T15f ended override falls back to product default', l_num = 15, 'pct=' || l_num);

    BEGIN
        commission_pkg.end_commission_rate('TERM-20', 2, DATE '2026-07-31', 'tester');
        expect_error('T15g ending a scope with no open rate rejected', -20007);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised('T15g ending a scope with no open rate rejected', -20007, SQLCODE, SQLERRM);
    END;
    check_case('T15h failed end writes no audit row', audit_count('RATE_END') = l_rows + 1,
               'before=' || (l_rows + 1) || ' after=' || audit_count('RATE_END'));

    ---------------------------------------------------------------
    -- T16: no rate in force is rejected, directly and via calculation
    ---------------------------------------------------------------
    BEGIN
        l_rate_id := commission_pkg.resolve_rate('TERM-20', 1, DATE '2023-06-15');
        expect_error('T16 resolve_rate with no rate in force', -20007);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised('T16 resolve_rate with no rate in force', -20007, SQLCODE, SQLERRM);
    END;
    BEGIN
        commission_pkg.calculate_policy_commission(1, '2023-06', 'tester');
        expect_error('T16b calculation with no rate in force rejected', -20007);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised('T16b calculation with no rate in force rejected', -20007, SQLCODE, SQLERRM);
    END;
    SELECT COUNT(*) INTO l_rows FROM commission_ledger WHERE policy_id = 1 AND period_month = '2023-06';
    check_case('T16c failed calculation leaves no ledger rows', l_rows = 0, 'rows=' || l_rows);

    ---------------------------------------------------------------
    -- T17: unknown policy is rejected by splits and by calculation
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.set_commission_splits(999999,
            split_alloc_tab(split_alloc_t(1, 100)), 'tester');
        expect_error('T17 splits for unknown policy rejected', -20005);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised('T17 splits for unknown policy rejected', -20005, SQLCODE, SQLERRM);
    END;
    BEGIN
        commission_pkg.calculate_policy_commission(999999, '2025-06', 'tester');
        expect_error('T17b calculation for unknown policy rejected', -20005);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised('T17b calculation for unknown policy rejected', -20005, SQLCODE, SQLERRM);
    END;

    ---------------------------------------------------------------
    -- T18: split validation (policy 3 keeps its T6 allocation)
    ---------------------------------------------------------------
    expect_split_rejected('T18 NULL split collection rejected', NULL, -20006);
    expect_split_rejected('T18b zero split pct rejected',
        split_alloc_tab(split_alloc_t(1, 0), split_alloc_t(2, 100)), -20006);
    expect_split_rejected('T18c split pct over 100 rejected',
        split_alloc_tab(split_alloc_t(1, 150), split_alloc_t(2, -50)), -20006);
    expect_split_rejected('T18d negative split pct rejected',
        split_alloc_tab(split_alloc_t(1, -10), split_alloc_t(2, 110)), -20006);
    expect_split_rejected('T18e NULL split pct rejected',
        split_alloc_tab(split_alloc_t(1, NULL), split_alloc_t(2, 100)), -20006);
    expect_split_rejected('T18f splits under 100 rejected',
        split_alloc_tab(split_alloc_t(1, 60), split_alloc_t(2, 30)), -20006);
    expect_split_rejected('T18g suspended agent in split rejected',
        split_alloc_tab(split_alloc_t(1, 50), split_alloc_t(4, 50)), -20003);
    expect_split_rejected('T18h unknown agent in split rejected',
        split_alloc_tab(split_alloc_t(1, 50), split_alloc_t(999999, 50)), -20002);
    SELECT COUNT(*), SUM(split_pct), SUM(CASE WHEN agent_id = 2 THEN split_pct END)
      INTO l_rows, l_num, l_num2
      FROM commission_splits WHERE policy_id = 3;
    check_case('T18i rejected splits leave allocation unchanged',
               l_rows = 2 AND l_num = 100 AND l_num2 = 65,
               'rows=' || l_rows || ' total=' || l_num || ' agent2=' || l_num2);

    ---------------------------------------------------------------
    -- T19: a failure after the old allocation was deleted rolls back
    -- (0.001 passes validation but cannot be stored in NUMBER(5,2))
    ---------------------------------------------------------------
    BEGIN
        commission_pkg.set_commission_splits(3,
            split_alloc_tab(split_alloc_t(1, 0.001), split_alloc_t(2, 99.999)), 'tester');
        check_case('T19 unstorable split pct rejected', FALSE, 'no error raised');
    EXCEPTION
        WHEN OTHERS THEN
            check_case('T19 unstorable split pct rejected', TRUE);
    END;
    SELECT COUNT(*), SUM(split_pct), SUM(CASE WHEN agent_id = 2 THEN split_pct END)
      INTO l_rows, l_num, l_num2
      FROM commission_splits WHERE policy_id = 3;
    check_case('T19b partial split replacement rolled back',
               l_rows = 2 AND l_num = 100 AND l_num2 = 65,
               'rows=' || l_rows || ' total=' || l_num || ' agent2=' || l_num2);

    ---------------------------------------------------------------
    -- T20: policy without a split allocation cannot be calculated;
    -- per-agent amounts round half-up to cents (HOME-PLUS 10%,
    -- premium 999.60: 999.60/12*10% = 8.33, 50% each = 4.165 -> 4.17)
    ---------------------------------------------------------------
    MERGE INTO policies p
    USING (SELECT 'POL-TEST-0901' AS policy_no FROM dual) s
       ON (p.policy_no = s.policy_no)
     WHEN NOT MATCHED THEN
          INSERT (policy_no, product_code, holder_name, annual_premium, issued_date, status)
          VALUES (s.policy_no, 'HOME-PLUS', 'Rounding Test', 999.60, DATE '2025-05-01', 'IN_FORCE');
    SELECT policy_id INTO l_policy_id FROM policies WHERE policy_no = 'POL-TEST-0901';
    DELETE FROM commission_ledger WHERE policy_id = l_policy_id;
    DELETE FROM commission_splits WHERE policy_id = l_policy_id;
    COMMIT;

    BEGIN
        commission_pkg.calculate_policy_commission(l_policy_id, '2025-06', 'tester');
        expect_error('T20 policy without splits cannot be calculated', -20006);
    EXCEPTION
        WHEN OTHERS THEN
            check_raised('T20 policy without splits cannot be calculated', -20006, SQLCODE, SQLERRM);
    END;
    SELECT COUNT(*) INTO l_rows FROM commission_ledger WHERE policy_id = l_policy_id;
    check_case('T20b no ledger rows for unsplit policy', l_rows = 0, 'rows=' || l_rows);

    commission_pkg.set_commission_splits(l_policy_id,
        split_alloc_tab(split_alloc_t(2, 50), split_alloc_t(3, 50)), 'tester');
    commission_pkg.calculate_policy_commission(l_policy_id, '2025-06', 'tester');
    SELECT COUNT(*), MIN(commission_amt), MAX(commission_amt) INTO l_rows, l_num, l_num2
      FROM commission_ledger WHERE policy_id = l_policy_id AND period_month = '2025-06';
    check_case('T20c per-agent amounts round half-up to cents',
               l_rows = 2 AND l_num = 4.17 AND l_num2 = 4.17,
               'rows=' || l_rows || ' min=' || l_num || ' max=' || l_num2);
    SELECT COUNT(*) INTO l_rows FROM rate_audit_log
     WHERE action = 'COMMISSION_CALC' AND policy_id = l_policy_id AND actor = 'tester';
    check_case('T20d calculation is audited', l_rows >= 1, 'rows=' || l_rows);

    DBMS_OUTPUT.PUT_LINE('----');
    IF g_failures = 0 THEN
        DBMS_OUTPUT.PUT_LINE('OLTP TESTS: ALL PASS');
    ELSE
        DBMS_OUTPUT.PUT_LINE('OLTP TESTS: ' || g_failures || ' FAILURE(S)');
        RAISE_APPLICATION_ERROR(-20099, g_failures || ' test failure(s)');
    END IF;
END;
/

EXIT;
