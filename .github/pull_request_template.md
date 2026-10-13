## Summary

<!-- What changed and why. Link the issue/ticket. -->

## Services / areas touched

- [ ] api-gateway  - [ ] auth  - [ ] file  - [ ] document  - [ ] collab  - [ ] notification
- [ ] search  - [ ] analytics  - [ ] admin  - [ ] audit  - [ ] report  - [ ] billing
- [ ] frontend  - [ ] infrastructure / Helm / Terraform  - [ ] CI / workflows  - [ ] docs only

## Testing

<!-- Paste real output: unit tests, `make test-api-flows`, k6, helm/terraform validate, screenshots. -->

- [ ] Unit tests pass for every touched service (coverage did not drop below the gate)
- [ ] `make test-api-flows` against a local stack (if routes or cross-service behavior changed)
- [ ] OpenAPI spec in `shared/openapi/` updated for any route/payload change
- [ ] Protobuf / event contract changes pass `buf lint` and `buf breaking`

## Risk & rollout

- [ ] No live infrastructure mutation (no `terraform apply` / `helm upgrade` / `kubectl apply` against shared AWS / `otterworks-dev`)
- [ ] Does not modify legacy "before state" fixtures (`services/legacy-*`, report-service Java 8, `etl/scripts`, `procs/`, insurance `db/`)
- [ ] Does not need changes to upstream-deployed infra (Helm charts, deploy scripts, `demo-platform/`) — see AGENTS.md
- [ ] Architecture decision recorded in `docs/adr/` (if this introduces or reverses one)

## Notes for reviewers

