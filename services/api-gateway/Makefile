.PHONY: test test-coverage

test: ## Run tests
	go test ./...

test-coverage: ## Run tests with coverage report
	go test -covermode=atomic -coverpkg=./... -coverprofile=coverage.out ./...
	go tool cover -func=coverage.out
