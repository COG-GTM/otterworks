.PHONY: test test-coverage coverage-gate

# Coverage ratchet: raise this when coverage rises, never lower it.
COVERAGE_MIN ?= 95.0
COVERAGE_PROFILE ?= coverage.out

test: ## Run tests
	go test ./...

test-coverage: ## Run tests with coverage report
	# -coverpkg=./... instruments every package for every test binary, so a
	# package with no test file of its own counts as 0% instead of being
	# omitted from the report.
	go test -coverpkg=./... -coverprofile=$(COVERAGE_PROFILE) ./...
	go tool cover -func=$(COVERAGE_PROFILE)

coverage-gate: test-coverage ## Fail if total coverage drops below COVERAGE_MIN
	sh scripts/coverage-gate.sh $(COVERAGE_PROFILE) $(COVERAGE_MIN)
