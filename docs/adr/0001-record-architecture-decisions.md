# ADR-0001: Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-13

## Context

`ARCHITECTURE.md` describes the system but not why it is shaped that way, and
`docs/SDLC-COVERAGE.md` flagged the absence of ADRs. Many decisions (gateway identity handling,
tenant isolation, IRSA) are load-bearing for security and for the shared demo platform, and are
easy to undo accidentally.

## Decision

We will record significant architecture decisions as numbered Markdown ADRs in `docs/adr/`, using
`0000-template.md`, and reference them from the PRs that implement or change them.

## Consequences

- New contributors (human or agent) can find the rationale next to the code.
- Reversing a decision requires a superseding ADR, which makes the change visible in review.
