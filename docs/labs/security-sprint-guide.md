# Security Sprint Guide

This guide covers how to run security scans across OtterWorks services, interpret the results, triage findings, and verify that suppressions in `.trivyignore` are appropriate.

## Running Scans

From the repository root:

```bash
make security-scan
```

This runs four scan types in sequence:

| Scanner | Service | What It Checks |
|---------|---------|---------------|
| Trivy | All services | Known CVEs in OS packages and language-specific libraries |
| npm audit | collab-service | Node.js dependency advisories |
| pip-audit | search-service | Python dependency advisories |
| bundle-audit | admin-service | Ruby gem advisories |

**Note:** report-service is intentionally excluded from scans. It was excluded as a legacy Java 8 service; it now runs on Java 17 / Spring Boot 3.2 but remains out of scope for this sprint.

## Understanding Trivy Output

Trivy reports vulnerabilities with a severity rating:

| Severity | Meaning | Action |
|----------|---------|--------|
| CRITICAL | Actively exploited or trivially exploitable. Typically remote code execution, authentication bypass, or command injection. | Fix immediately or document a concrete mitigation plan. |
| HIGH | Significant risk but may require specific conditions to exploit (e.g., attacker-controlled input reaching a vulnerable code path). | Fix within the current sprint. |
| MEDIUM | Moderate risk, often requiring local access or unusual configurations. | Evaluate and schedule for a future sprint if not immediately exploitable. |
| LOW | Minimal practical risk. | Acknowledge and revisit periodically. |

The `--config security/scanning/trivy-config.yaml` flag limits output to CRITICAL and HIGH findings only. To see the full picture, run Trivy without the config:

```bash
trivy fs .
```

Each finding includes:

- **Library** -- the affected package name and installed version
- **Vulnerability ID** -- the CVE or GHSA identifier
- **Fixed Version** -- the minimum version that resolves the issue (if available)
- **Title** -- a short description of the vulnerability

## Triaging Findings

When you encounter a vulnerability, work through these questions:

1. **Is the vulnerable code reachable?** Check whether the affected function or module is actually imported and used in the service. A transitive dependency that is never called may still warrant an upgrade but is lower priority.

2. **Is there a fixed version available?** If the "Fixed Version" column shows a version, try upgrading to it. If not, check the CVE details for workarounds.

3. **What breaks if you upgrade?** Review the changelog between the current and fixed versions. Look for breaking changes that would require code modifications.

4. **Is the finding already suppressed?** Check `.trivyignore` to see if the CVE is listed there. If it is, evaluate whether the suppression is still justified (see below).

## Auditing `.trivyignore`

The `.trivyignore` file tells Trivy to skip specific CVEs. This is legitimate for findings that have been evaluated and accepted, but it can mask real problems when entries are too broad or stale.

When reviewing `.trivyignore`, look for:

- **Glob patterns** (e.g., `CVE-2021-*`) that suppress entire ranges of CVEs rather than individual findings. These can silently hide new vulnerabilities that match the pattern.
- **Dismissive comments** (e.g., "bulk ignore", "revisit later") without a concrete remediation date or tracking ticket.
- **Entries that suppress CRITICAL or HIGH CVEs** with command injection, RCE, or authentication bypass impact. These should have strong justification.
- **Stale entries** for CVEs that now have available fixes. If a fixed version exists and the upgrade is straightforward, the suppression should be removed and the dependency updated.

A well-maintained `.trivyignore` entry looks like:

```
# CVE-YYYY-NNNNN — <package>: <brief description>
# Impact: <severity>. Tracked in JIRA-123. Blocked on <reason>. Revisit by <date>.
CVE-YYYY-NNNNN
```

An entry that deserves scrutiny:

```
# Bulk ignore — revisit in Q4
CVE-2021-*
```

## What "Done" Looks Like

The sprint is complete when:

- All CRITICAL and HIGH CVEs reported by `make security-scan` are either resolved (dependency upgraded, vulnerability patched) or properly acknowledged with a documented justification and tracking ticket.
- Overly broad `.trivyignore` entries have been replaced with specific, well-documented suppressions or removed entirely after fixing the underlying issue.
- No glob patterns remain in `.trivyignore`.
- Each remaining suppression has a clear comment explaining why it is necessary, what blocks remediation, and when it will be revisited.
- `make security-scan` runs cleanly with only acknowledged and justified suppressions remaining.
