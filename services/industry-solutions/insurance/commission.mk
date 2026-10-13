# --- Industry Solutions: insurance Commission Pay modernization (commission-service + parity) ---
# Included from the root Makefile. Targets reuse procs-validate (NS required).

COMMISSION_DIR = services/industry-solutions/insurance
COMMISSION_ENV_FILE = $(COMMISSION_DIR)/parity/.local.env
COMMISSION_COMPOSE = docker compose --env-file $(COMMISSION_ENV_FILE) -f docker-compose.commission.yml -p otterworks-commission-$(NS)
COMMISSION_PY = cd $(COMMISSION_DIR)/parity && uv run --with-requirements harness/requirements.txt python -m
COMMISSION_LOAD_ENV = set -a && . ./$(COMMISSION_ENV_FILE) && set +a
INSURANCE_ORACLE_CONTAINER = otterworks-insurance-$(NS)-insurance-oracle-1

$(COMMISSION_ENV_FILE):
	@umask 077 && { \
	  echo "COMMISSION_DB_ADMIN_PASSWORD=$$(openssl rand -hex 24)"; \
	  echo "COMMISSION_SVC_DB_PASSWORD=$$(openssl rand -hex 24)"; \
	  echo "JWT_SECRET=$$(openssl rand -hex 32)"; \
	  echo "COMMISSION_SVC_ENABLE_RESET=true"; \
	} > $@ && echo "generated throwaway local secrets in $@"

commission-up: procs-validate $(COMMISSION_ENV_FILE) ## Start commission-service + its Postgres (NS=<namespace>)
	NS=$(NS) $(COMMISSION_COMPOSE) up -d --build --wait --wait-timeout 300

commission-down: procs-validate ## Stop commission-service and drop its data (NS=<namespace>)
	NS=$(NS) $(COMMISSION_COMPOSE) down -v

commission-test: ## Unit tests, lint and types for commission-service
	cd $(COMMISSION_DIR)/commission-service && uv sync --locked && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -m "not integration"

commission-integration: procs-validate $(COMMISSION_ENV_FILE) ## HTTP/RLS tests against the composed Postgres (NS=<namespace>)
	$(COMMISSION_LOAD_ENV) && cd $(COMMISSION_DIR)/commission-service && \
	  COMMISSION_TEST_DATABASE_URL=postgresql://commission_svc:$$COMMISSION_SVC_DB_PASSWORD@127.0.0.1:$${COMMISSION_DB_PORT:-56544}/commission_$(NS) \
	  uv run pytest -m integration -v

commission-rules-gate: ## Validate the Commission Pay rule ledger and transcripts
	$(COMMISSION_PY) harness.rules_gate
	$(COMMISSION_PY) harness.verify

commission-record: procs-validate ## Record Oracle PL/SQL transcripts (needs make insurance-up NS=<ns>; ALLOW_RERECORD=1 RERECORD_REASON=...)
	INSURANCE_ORACLE_DSN=localhost:$$(docker port $(INSURANCE_ORACLE_CONTAINER) 1521 | head -1 | sed 's/.*://')/FREEPDB1 \
	INSURANCE_OLTP_PASSWORD=$${INSURANCE_OLTP_PASSWORD:-commission_pay} INSURANCE_DW_PASSWORD=$${INSURANCE_DW_PASSWORD:-commission_dw} \
	  $(COMMISSION_PY) harness.record $(if $(MODULE),--module $(MODULE),) $(if $(SCENARIO),--scenario $(SCENARIO),)

commission-parity: procs-validate $(COMMISSION_ENV_FILE) ## Replay transcripts against commission-service (NS=<namespace>)
	$(COMMISSION_LOAD_ENV) && COMMISSION_SVC_URL=$${COMMISSION_SVC_URL:-http://127.0.0.1:$${COMMISSION_SVC_PORT:-8098}} \
	  $(COMMISSION_PY) harness.replay $(if $(MODULE),--module $(MODULE),)
