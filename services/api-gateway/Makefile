.PHONY: test test-coverage coverage coverage-gate coverage-html

# Statement-coverage ratchet. Raise it to the newly measured total in every PR
# that improves coverage; never lower it.
COVERAGE_MIN ?= 95.0

# -coverpkg=./... instruments every package for every test binary. Without it,
# each package is only measured against its own tests and packages with no test
# file are omitted from the report entirely instead of counting as 0%.
COVER_FLAGS := -race -coverpkg=./... -coverprofile=coverage.out

test: ## Run tests
	go test ./...

test-coverage: ## Run tests with coverage report
	go test -cover -coverprofile=coverage.out ./...
	go tool cover -func=coverage.out

coverage: ## Run tests with whole-module coverage (the number the gate uses)
	go test $(COVER_FLAGS) ./...
	go tool cover -func=coverage.out

coverage-html: coverage ## Write an HTML coverage report for eyeballing gaps
	go tool cover -html=coverage.out -o coverage.html

# Fails closed: a missing or unparseable total: line is a gate failure, not a pass.
coverage-gate: coverage ## Fail if statement coverage drops below COVERAGE_MIN
	@go tool cover -func=coverage.out | awk -v min=$(COVERAGE_MIN) '\
	  /^total:/ { \
	    seen=1; c=$$NF; sub(/%/,"",c); \
	    if (c+0 < min) { printf "FAIL coverage %.1f%% < %.1f%%\n", c, min; exit 1 } \
	    printf "OK coverage %.1f%% >= %.1f%%\n", c, min \
	  } \
	  END { if (!seen) { print "FAIL no total: line in the coverage profile"; exit 1 } }'
