# ADR-0008: Keep legacy "before state" fixtures alongside modernized implementations

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

The repo is used to demonstrate modernization. Demos need the original legacy code (report-service
on Java 8, `etl/scripts` + `config.ini` + `crontab`, `services/legacy-*`, `procs/`,
`services/industry-solutions/insurance/db`) to remain runnable as the "before" picture.

## Decision

Legacy fixtures are frozen. Modernized implementations are added alongside them (for example
`services/billing-service` next to `services/legacy-billing` stored procedures) rather than
replacing them in place.

## Consequences

- Some duplication is intentional; reviewers should reject PRs that mutate the fixtures.
- Contracts for legacy services (e.g. `shared/openapi/report-service.yaml`) document behavior
  without implying the implementation is the target state.
