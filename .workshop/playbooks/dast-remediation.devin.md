# Playbook: Remediate a DAST finding and prove it is closed

> **Facilitator / author:** this file is the source for a **Devin Playbook**.
> Copy its contents into your Devin organization (Settings → Playbooks → *Create
> a new Playbook*) so sessions can invoke it as `!dast-remediation`. See
> [Creating Playbooks](https://docs.devin.ai/product-guides/creating-playbooks).

## Overview

Use this playbook when a **dynamic application security test** — a DAST suite, an
OWASP ZAP sweep, a pen-test ticket, a bug-bounty report — says a running
application is exploitable, and someone has to fix it. Devin reproduces the
attack against a deployed target, fixes the control in the service that owns it,
and then **re-runs the same attack to prove the finding is closed**.

The guiding principle: **a finding is closed only when the attack that
reproduced it fails against a target running the new code.** A code review, a
green unit test, and a plausible-looking diff are not evidence. Re-running the
exploit is.

This is what separates DAST from static analysis. SAST tells you a line of code
looks dangerous; DAST tells you an attacker can actually do it — and therefore
gives you a repeatable, adversarial check that the fix works.

## Required from user

- **The finding** — a finding ID from the DAST suite, or a report describing the
  attack. If you have only prose, your first job is to turn it into a probe that
  reproduces it programmatically.
- **The target** — a URL for a **disposable** environment running the code: a
  local stack, a preview deploy, an isolated tenant namespace. Never a shared
  environment someone else is using, and never production. Scans create accounts
  and write data.
- **The redeploy path** — how a code change reaches that target
  (`docker compose up --build <service>`, a tenant deploy script, a preview
  deployment). Without it you cannot prove anything; if it is unclear, ask.

## Procedure

1. **Orient before touching code.** Identify which service terminates the
   request, which one owns the data, and where the control that failed is
   supposed to live. Read the repo's Skill or security docs for the
   command-and-file map; use DeepWiki or repo search for an unfamiliar estate.
   Coverage depends on repo structure, so confirm what you find against the code.

2. **Reproduce the attack first.** Run the DAST suite against the target and
   confirm the finding fires *before* changing anything. Capture the request and
   response that prove the attack works — that pair is your before-state and the
   evidence in the PR. If it does not reproduce, stop and find out why: a
   finding you cannot reproduce is one you cannot prove you fixed.

3. **Classify the finding, then place the fix.**
   - *Edge control* (security headers, CORS, TLS policy, rate limiting, identity
     header hygiene, exposed operational endpoints) → the gateway or reverse
     proxy, once, for every backend behind it.
   - *Object-level control* (who may read or write this row) → the service that
     owns the data. A gateway cannot know which records belong to whom.
   - *Input handling* (injection, unsafe deserialization, mass assignment) → the
     boundary of the service that parses the input, usually its request schema.
   Fixing at the wrong layer produces a patch that passes the probe and leaves
   the vulnerability reachable by another route.

4. **Fix the control, not the symptom.** Deny by default; derive identity from
   validated credentials rather than client-supplied values; reject unknown
   request fields instead of filtering known-bad ones. If the probe passes but an
   attacker could reach the same outcome by changing a header, a field name, or a
   route, you have not fixed it.

5. **Redeploy the target.** The probe attacks a running system; unless the new
   code is running, a green result is meaningless. Rebuild and redeploy, then
   confirm the new build is actually live (health endpoint, image tag, version).

6. **Re-run the same probe.** Run the single finding first for a fast signal,
   with baseline suppression off so an accepted finding cannot mask its own
   check. Then run the **full** suite: fixes at the edge routinely change
   behavior for every route behind it.

7. **Prove you did not break the application.** Run the service's tests and the
   API flow tests. Access-control fixes are exactly the kind that pass the
   security check by refusing everyone. A control request — *can the legitimate
   owner still do this?* — belongs in the probe itself, not in your judgment.

8. **Open a PR with the evidence.** Include the before (attack succeeded, with
   the captured request/response), the after (same attack, now refused), and the
   full-suite result. Describe the vulnerability class and the control you added,
   not the diff. Do not include real credentials, tokens, or customer data in the
   evidence — redact them.

9. **Ask what the scan never touched.** A report only ever describes requests
   that were made. Derive the reachable surface from the source instead — the
   gateway's route table plus each service's own route definitions — and diff it
   against the paths the run actually requested. A route nobody attacked is not
   a passing route, and the difference is invisible in a green report. Sweep the
   whole inventory unauthenticated so a newly added endpoint is attacked the day
   it lands, and record a deliberate gap as an exemption with a reason rather
   than leaving it silent.

10. **Read the deployment config as attack surface.** Published container ports,
    per-service ingress hosts and network policies decide which origins exist,
    and a scanner aimed at the public URL cannot crawl to an origin nothing
    links to. Where the perimeter is what authenticates the request — a gateway
    that validates a token and forwards an identity header — any origin that
    reaches a backend directly is an unauthenticated impersonation endpoint.
    Attack the origins the repository declares, and grade them by blast radius:
    a developer's published port is not the public internet.

11. **Fan out the rest.** When a scan returns several unrelated findings, spawn a
    **child session per finding**, each on its own branch and its own disposable
    target, each running this playbook to a green verification and its own PR.
    They are independent fixes in different services; serializing them wastes the
    parallelism, and one session juggling five exploits loses the thread.

12. **Leave it running.** A one-off scan dates immediately. Land the suite in CI
    on pull requests (gated against a baseline of accepted findings, so it fails
    only on newly introduced ones) and on a schedule against a deployed
    environment. Pair the schedule with an automation that starts a session when
    the scan goes red, so the next finding arrives as a PR rather than a ticket.

## Specifications

The work is done when all of these hold:

- The probe that reproduced the finding reports **secure** against a target
  running the new code, with baseline suppression disabled.
- The **full** suite shows no new findings versus the pre-fix run.
- The application's own tests and API flow tests pass.
- The probe contains a **control request** proving the legitimate caller still
  succeeds — a route that refuses everyone is not fixed.
- Any finding that cannot be verified is reported as **inconclusive**, never as
  passing. A backend that is down does not make an attack fail.
- The PR carries the before/after evidence and names the vulnerability class.
- Every route reachable at the edge was sent at least one request, or is
  recorded as a deliberate exemption with a reason.
- The target environment is disposable and was left clean, or is scheduled for
  teardown.

## Advice and pointers

- **Attack through the front door.** Scanning a backend port directly bypasses
  the authentication, rate limiting and header middleware that stand between an
  attacker and that service, and produces findings that do not exist at the
  deployed edge — and misses the ones that do. The single exception is a probe
  whose question *is* whether a direct origin exists, which must then say which
  configuration declared it.
- **Distinguish "secure" from "broken".** `401` for the attacker looks identical
  to `401` for everybody. Always pair the attack with a control request.
- **Namespace everything a scan creates.** Identities, documents and payloads
  should carry a per-run id so concurrent scans — CI, several sessions, several
  tenants — never collide or read each other's fixtures.
- **A stable finding ID is the contract.** It is the gate key, the baseline key
  and the handle you re-verify with. Never renumber one.
- **Baselines are debt, not a filing cabinet.** An accepted finding needs a
  reason and an owner. Never let the remediation check consult the baseline.
- **Coverage is a claim, so make it checkable.** "The scan passed" and "the scan
  attacked this" are different statements; only the second survives someone
  adding an endpoint. Read the routes from the code and gate on the diff.
- **Prefer schema-level fixes to validation-level ones.** Forbidding an unknown
  field in the request model kills a whole class of mass-assignment bugs; adding
  a check to one endpoint kills one.

### Worked example: a real finding this loop caught

Scanning an OtterWorks tenant produced a `secure` verdict for cross-tenant
document reads — the attacker's token got `401` on the victim's document. Read
alone, that looks like working authorization.

The suite also ran a probe the report authors had not thought to look for:
`DAST-MASS-ASSIGNMENT-OWNER`. It had the attacker create a document with
`owner_id` set to the **victim's** user id, using nothing but the attacker's own
token:

```http
POST /api/v1/documents/   Authorization: Bearer <attacker token>
{"title": "planted-by-attacker", "content": "...", "owner_id": "<victim id>"}
-> 201 {"id": "ae2524f6-…", "owner_id": "<victim id>", …}
```

The API echoed the victim as owner. An attacker could plant arbitrary content
into any account — and because `owner_id` was accepted from the request body,
the read-side check was enforcing an ownership field the caller controlled.

Two things made this catchable. The probe used **two real identities**, so it
could express "as A, act on B" — an unauthenticated crawler cannot. And the
BOLA probe's **control request** revealed that the `401` on read was not
authorization at work: the owner was refused too. The suite reported that as
`inconclusive` rather than `secure`, which is what sent us looking at the write
path in the first place. A scanner without a control request would have
recorded a pass on a route that was refusing everyone.

## Forbidden actions

- Do **not** scan production, a shared environment, or any target you were not
  given. Probes register accounts, write data and attempt exploits.
- Do **not** close a finding on a code change alone. Re-run the probe against
  the running fix.
- Do **not** weaken or delete a probe, raise its severity threshold, or add a
  baseline entry to get a green result. If a probe is wrong, fix the probe and
  say so.
- Do **not** report `inconclusive` as a pass, and do **not** accept a `secure`
  verdict from a route that refuses the legitimate owner too.
- Do **not** paste real credentials, tokens, session cookies or customer data
  into reports, PRs or commits — redact them.
- Do **not** commit exploit payloads or scan output as application code, or
  leave scan artifacts in the repository.
