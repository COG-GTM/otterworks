-- OLAP/ETL test suite. Run as COMMISSION_DW against FREEPDB1 AFTER the OLTP
-- suite (it consumes the ledger rows the OLTP tests calculated):
--   sqlplus commission_dw/commission_dw@localhost:1521/FREEPDB1 @run_olap_tests.sql
WHENEVER SQLERROR EXIT SQL.SQLCODE
SET SERVEROUTPUT ON SIZE UNLIMITED
SET FEEDBACK OFF

DECLARE
    g_failures PLS_INTEGER := 0;
    l_merged   PLS_INTEGER;
    l_num      NUMBER;
    l_num2     NUMBER;
    l_name     VARCHAR2(120);
    l_name2    VARCHAR2(120);
    l_code     NUMBER;

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

    PROCEDURE load_autonomous (p_period_month IN VARCHAR2, o_code OUT NUMBER) IS
        PRAGMA AUTONOMOUS_TRANSACTION;
        l_rows PLS_INTEGER;
    BEGIN
        o_code := 0;
        dw_etl_pkg.load_commission_facts(p_period_month, l_rows);
    EXCEPTION
        WHEN OTHERS THEN
            o_code := SQLCODE;
            ROLLBACK;
    END load_autonomous;
BEGIN
    ---------------------------------------------------------------
    -- E1: ETL loads the 2025-06 ledger rows into the star schema
    ---------------------------------------------------------------
    dw_etl_pkg.load_commission_facts('2025-06', l_merged);
    check_case('E1 ETL merges fact rows', l_merged >= 3, 'merged=' || l_merged);
    SELECT COUNT(*) INTO l_num FROM fact_commission;
    check_case('E1a fact rows present', l_num >= 3, 'rows=' || l_num);

    ---------------------------------------------------------------
    -- E2: fact totals reconcile with the OLTP ledger for the period
    ---------------------------------------------------------------
    SELECT NVL(SUM(commission_amt), 0) INTO l_num
      FROM fact_commission f
      JOIN dim_period d ON d.period_key = f.period_key
     WHERE d.period_month = '2025-06';
    SELECT NVL(SUM(commission_amt), 0) INTO l_num2
      FROM commission_pay.commission_ledger
     WHERE period_month = '2025-06';
    check_case('E2 fact totals reconcile with ledger', l_num = l_num2,
               'fact=' || l_num || ' ledger=' || l_num2);

    ---------------------------------------------------------------
    -- E3: re-running the ETL is idempotent
    ---------------------------------------------------------------
    SELECT COUNT(*) INTO l_num FROM fact_commission;
    dw_etl_pkg.load_commission_facts('2025-06', l_merged);
    SELECT COUNT(*) INTO l_num2 FROM fact_commission;
    check_case('E3 ETL rerun does not duplicate facts', l_num = l_num2,
               'before=' || l_num || ' after=' || l_num2);

    ---------------------------------------------------------------
    -- E4: the summary materialized view reflects loaded facts
    ---------------------------------------------------------------
    DBMS_MVIEW.REFRESH('MV_AGENT_COMMISSION_SUMMARY', 'C');
    SELECT COUNT(*) INTO l_num FROM mv_agent_commission_summary WHERE period_month = '2025-06';
    check_case('E4 summary MV populated', l_num >= 3, 'rows=' || l_num);

    ---------------------------------------------------------------
    -- E5: dimensions are refreshed from OLTP when the source differs
    ---------------------------------------------------------------
    UPDATE dim_agent SET full_name = 'STALE', status = 'TERMINATED' WHERE agent_id = 4;
    UPDATE dim_product SET product_name = 'STALE' WHERE product_code = 'AUTO-STD';
    COMMIT;
    dw_etl_pkg.load_commission_facts(NULL, l_merged);
    SELECT d.full_name || '/' || d.status, s.full_name || '/' || s.status INTO l_name, l_name2
      FROM dim_agent d JOIN commission_pay.agents s ON s.agent_id = d.agent_id
     WHERE d.agent_id = 4;
    check_case('E5 dim_agent row updated from source', l_name = l_name2,
               'dim=' || l_name || ' src=' || l_name2);
    SELECT d.product_name, s.product_name INTO l_name, l_name2
      FROM dim_product d JOIN commission_pay.products s ON s.product_code = d.product_code
     WHERE d.product_code = 'AUTO-STD';
    check_case('E5b dim_product row updated from source', l_name = l_name2,
               'dim=' || l_name || ' src=' || l_name2);

    ---------------------------------------------------------------
    -- E6: a NULL period loads every ledger period
    ---------------------------------------------------------------
    SELECT COUNT(DISTINCT period_month) INTO l_num FROM commission_pay.commission_ledger;
    SELECT COUNT(*) INTO l_num2 FROM dim_period
     WHERE period_month IN (SELECT period_month FROM commission_pay.commission_ledger);
    check_case('E6 all ledger periods present in dim_period', l_num = l_num2 AND l_num > 0,
               'ledger=' || l_num || ' dim=' || l_num2);
    SELECT COUNT(*), NVL(SUM(commission_amt), 0) INTO l_num, l_num2 FROM fact_commission;
    SELECT COUNT(*), NVL(SUM(commission_amt), 0) INTO l_merged, l_code
      FROM commission_pay.commission_ledger;
    check_case('E6b full load reconciles with the whole ledger',
               l_num = l_merged AND l_num2 = l_code,
               'fact rows=' || l_num || ' sum=' || l_num2
               || ' ledger rows=' || l_merged || ' sum=' || l_code);

    ---------------------------------------------------------------
    -- E7: a failing load rolls back and re-raises. The caller holds a
    -- lock on a fact row the autonomous ETL must update (ORA-00060).
    ---------------------------------------------------------------
    UPDATE dim_agent SET full_name = 'STALE' WHERE agent_id = 4;
    COMMIT;
    SELECT COUNT(*), NVL(SUM(commission_amt), 0) INTO l_num, l_num2 FROM fact_commission;
    UPDATE fact_commission SET loaded_at = loaded_at
     WHERE period_key = (SELECT period_key FROM dim_period WHERE period_month = '2025-06')
       AND ROWNUM = 1;
    load_autonomous('2025-06', l_code);
    ROLLBACK;
    check_case('E7 ETL error is re-raised', l_code = -60, 'sqlcode=' || l_code);
    SELECT full_name INTO l_name FROM dim_agent WHERE agent_id = 4;
    check_case('E7b failed load rolled back dimension changes', l_name = 'STALE', 'dim=' || l_name);
    SELECT COUNT(*), NVL(SUM(commission_amt), 0) INTO l_merged, l_code FROM fact_commission;
    check_case('E7c failed load left facts unchanged', l_num = l_merged AND l_num2 = l_code,
               'before=' || l_num || ' after=' || l_merged);
    dw_etl_pkg.load_commission_facts(NULL, l_merged);
    SELECT full_name INTO l_name FROM dim_agent WHERE agent_id = 4;
    check_case('E7d next load repairs the dimension', l_name <> 'STALE', 'dim=' || l_name);

    DBMS_OUTPUT.PUT_LINE('----');
    IF g_failures = 0 THEN
        DBMS_OUTPUT.PUT_LINE('OLAP TESTS: ALL PASS');
    ELSE
        DBMS_OUTPUT.PUT_LINE('OLAP TESTS: ' || g_failures || ' FAILURE(S)');
        RAISE_APPLICATION_ERROR(-20099, g_failures || ' test failure(s)');
    END IF;
END;
/

EXIT;
