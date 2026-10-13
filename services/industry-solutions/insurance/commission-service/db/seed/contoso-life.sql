-- Isolation tenant: same natural ids as northwind-mutual, different data.
SELECT set_config('app.tenant_id', 'contoso-life', false);
INSERT INTO commission.tenants (tenant_id, name) VALUES ('contoso-life', 'Contoso Life');
INSERT INTO commission.agents (tenant_id, agent_id, agent_code, full_name, license_no, status, hired_date) VALUES ('contoso-life', 1, 'CL-900', 'Ines Duarte', 'LIC-NY-90001', 'ACTIVE', DATE '2016-05-02');
INSERT INTO commission.agents (tenant_id, agent_id, agent_code, full_name, license_no, status, hired_date) VALUES ('contoso-life', 2, 'CL-901', 'Tom Brandt', 'LIC-NY-90002', 'SUSPENDED', DATE '2021-09-09');
INSERT INTO commission.products (tenant_id, product_code, product_name, line_of_business) VALUES ('contoso-life', 'AUTO-STD', 'Standard Auto', 'AUTO');
INSERT INTO commission.products (tenant_id, product_code, product_name, line_of_business) VALUES ('contoso-life', 'HOME-PLUS', 'HomeOwners Plus', 'HOME');
INSERT INTO commission.products (tenant_id, product_code, product_name, line_of_business) VALUES ('contoso-life', 'TERM-20', '20-Year Term Life', 'LIFE');
INSERT INTO commission.commission_rates (tenant_id, rate_id, product_code, agent_id, rate_pct, effective_from, effective_to, created_by) VALUES ('contoso-life', 1, 'AUTO-STD', NULL, 12.00, DATE '2024-01-01', NULL, 'seed');
INSERT INTO commission.commission_rates (tenant_id, rate_id, product_code, agent_id, rate_pct, effective_from, effective_to, created_by) VALUES ('contoso-life', 2, 'HOME-PLUS', NULL, 11.00, DATE '2024-01-01', NULL, 'seed');
INSERT INTO commission.commission_rates (tenant_id, rate_id, product_code, agent_id, rate_pct, effective_from, effective_to, created_by) VALUES ('contoso-life', 3, 'TERM-20', NULL, 20.00, DATE '2024-01-01', NULL, 'seed');
INSERT INTO commission.policies (tenant_id, policy_id, policy_no, product_code, holder_name, annual_premium, issued_date, status) VALUES ('contoso-life', 1, 'CL-2025-0001', 'AUTO-STD', 'Contoso Fleet', 50000.00, DATE '2025-01-01', 'IN_FORCE');
INSERT INTO commission.policies (tenant_id, policy_id, policy_no, product_code, holder_name, annual_premium, issued_date, status) VALUES ('contoso-life', 4, 'CL-2025-0004', 'TERM-20', 'Hidden Holder', 7200.00, DATE '2025-02-01', 'IN_FORCE');
INSERT INTO commission.commission_splits (tenant_id, policy_id, agent_id, split_pct) VALUES ('contoso-life', 1, 1, 100.00);
INSERT INTO commission.commission_splits (tenant_id, policy_id, agent_id, split_pct) VALUES ('contoso-life', 4, 1, 100.00);
