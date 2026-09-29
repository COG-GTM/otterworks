# Playbook: Refactor a class to close a security finding and prove behavior is unchanged

> **Facilitator / author:** this file is the source for a **Devin Playbook**.
> Copy its contents into your Devin organization (Settings → Playbooks → *Create
> a new Playbook*) so sessions can invoke it as `!secure-refactor-equivalence`.
> See [Creating Playbooks](https://docs.devin.ai/product-guides/creating-playbooks).

## Overview

Use this playbook when a security finding cannot be closed by a version bump —
the flaw is in **your** code. SQL assembled by string concatenation, a file path
built from a caller-supplied name, a token that is an unkeyed digest, an
authorization check that trusts a request header. Closing it means rewriting a
class or a method, and the risk is not the security pattern (those are well
known) but everything else the method does: the ordering, the pagination, the
error type a caller catches, the exact bytes a downstream consumer parses.

The guiding principle: **the refactor is done when the exploit no longer
reproduces and every other externally observable behavior of the affected class
is byte-identical to what it was before — both proven by a command, not by
reading the diff.** A parameterized query is a claim; a green test file you wrote
after the change proves only that the new code agrees with itself.

Two failure modes this exists to prevent: the *silent behavior change* (the
injection is gone, and so is case-insensitive matching, or the sort order, or the
`FileNotFoundError` a caller depended on) and the *cosmetic fix* (the payload is
escaped on one path while another still concatenates, so the probe stops firing
without the vulnerability being closed).

## Required from user

- **The finding** — the file, the class, and the method, plus the vulnerability
  class (CWE) and, if one exists, the runtime probe or scanner rule that fires.
  If you are given only a scanner ID, resolve it to the source location before
  touching anything.
- **The affected service** and how to run its suite.
- **What is allowed to change.** The public interface normally is not. Say
  explicitly whether callers may be edited, whether an error type may change, and
  whether any behavior is *intended* to change (rejecting input that used to be
  accepted is a behavior change — usually the point, and it must be declared).

## Procedure

1. **Read the subject before writing anything.** Identify every externally
   observable behavior of the class: return shapes, ordering, pagination,
   filtering semantics, side effects, error types and error messages, and the
   HTTP surface that reaches it. Enumerate its callers. Report the file, class and
   methods you are going to change, and what the flaw actually allows.

2. **Characterize the current behavior as data, not prose.** Write cases that
   pin the observable behavior of the *before* state, split into two kinds and
   labelled as such:
   - **contract cases** — behaviors that must be byte-identical afterwards.
   - **attack cases** — the exploit, which *must* change, and only in the
     security direction.
   Every case must be reproducible from the fixture's setup and seed alone. If a
   case only passes because of a step the replay does not perform, the recording
   is a story. Two cases with identical inputs and different expected outputs is
   proof the fixture is broken.

3. **Reproduce the exploit against the unmodified code.** A finding you cannot
   reproduce is a finding you cannot prove you closed. Record the attack cases
   firing *before* the change, and make the detector mechanical (a signature in
   the response, a row that belongs to another owner, a file served from outside
   the root) — never "the output looks wrong".

4. **Record the before-state and run the suite.** Save the characterization
   evidence and the module's full pass list. A recording is only evidence if it
   is fingerprinted against everything that can change it: the subject source,
   the seed, the cases, the harness that emits them, and the schema. Anything
   else lets a later run grade itself against a moved goalpost.

5. **Refactor with the secure pattern, keeping the public interface.** Bind
   caller values as query parameters and allow-list identifiers that cannot be
   bound (sort columns, directions, table names). Resolve paths and require
   containment inside the resolved root. Mint tokens as a keyed HMAC and compare
   in constant time. Derive identity from validated claims, never from a header.
   Change the method body, not its name, parameters, defaults or return type —
   and stop generic scanner remediations from creeping into unrelated code in the
   same PR.

6. **Grade equivalence and closure in one command.** Re-run the cases against
   the refactored subject: contract cases must be byte-identical, attack cases
   must stop firing, and the recorded evidence must be the one taken before the
   change. Then run the affected service's **full** suite against the recorded
   pass list, so a test that used to pass cannot be deleted on the way to green.
   Treat missing, stale or unmeasured evidence as **inconclusive** — never as a
   pass.

7. **Prove it on the running application.** Redeploy the service locally and
   re-run the *original* runtime probe against it, not a new one you wrote. A
   unit-level fix that the deployed edge still exposes (a second route, a cached
   view, a gateway that rewrites the request) is not closed. Attach the
   before/after verdicts.

8. **Open a PR with the evidence.** It must state: the finding (file, class,
   method, CWE); the secure pattern applied and why that one; the before/after
   exploit verdicts; the equivalence result with the case counts; the suite
   result; the runtime probe verdicts; and an explicit statement of what behavior
   was preserved — and of any behavior that intentionally changed, with the
   reason. If the harness's reports are git-ignored generated output, paste the
   summary lines and attach the reports as CI artifacts rather than committing
   them.

9. **Fan out the remaining findings.** Each finding is an independent unit of
   work: spawn a **child session per finding**, each on its own branch, each
   running this playbook to a green verification and its own PR in the same
   evidence format. Findings that share a subject file belong in one session
   instead — the unit is the change, not the ticket. Monitor the children to
   green and reconcile their evidence into a single auditor-facing report:
   finding, fix, evidence, residual risk.

10. **Leave it running.** Put the equivalence gate in CI so a later edit to the
    subject must re-prove equivalence, and put the runtime probe suite on a
    schedule so a regression arrives as a red gate rather than as an incident.
    Pair the schedule with an automation that opens a session when it goes red.

## Specifications

The work is done when all of these hold:

- The finding is stated as file → class → method, with the CWE and the
  vulnerability's actual capability described.
- The exploit was **reproduced before the change** and no longer reproduces
  after it, judged by the same mechanical detector both times.
- Every contract case is byte-identical to the recording, ordering included.
- The public interface is unchanged: names, parameters, defaults, return types
  and raised error types, unless a change was declared and justified.
- The affected service's full suite passes, compared against the pass list
  recorded before the change.
- The runtime probe that originally fired now reports the finding closed against
  a redeployed instance.
- Anything that could not be measured is reported as **inconclusive**, never as
  passing; the gate fails closed on missing or stale evidence.
- The PR carries the evidence and an explicit preserved-behavior statement.
- Remaining findings are either fixed, delegated to a child session, or listed as
  residual risk with an owner.

## Advice and pointers

- **Characterize before you refactor, or you are just hoping.** Tests written
  after the change encode the new behavior. The whole value of this loop is that
  the evidence predates the fix.
- **Split "must not change" from "must change" explicitly.** Without that split
  the gate is either too strict to ever pass (the exploit path *has* to change)
  or too loose to notice that pagination broke.
- **Ordering is usually a business rule.** Compare ordered results in order.
  Sorting both sides before comparing is the most common way an equivalence
  harness lies.
- **Error messages are part of the observable surface, but absolute paths and
  timestamps are not.** Redact the non-deterministic parts at capture time rather
  than loosening the comparison — a substring match is a gate you can drive a
  regression through.
- **The identifier you cannot bind needs an allow-list.** Placeholders work for
  values, never for column or table names; mapping the caller's `sort` through a
  dictionary of permitted columns is the fix, and rejecting the rest is a declared
  behavior change.
- **A fix on one route is not a closure.** Grep for every caller of the subject
  and for sibling routes with the same pattern before claiming the class is safe.
- **Never re-record to get green.** A red gate is either a real divergence or a
  defective fixture; both are fixed at the root. If a recording genuinely must
  change, it needs an audited reason attached to it.

### Worked example: a real bug this loop caught

The refactor was the textbook one. A `WHERE` clause that interpolated the
caller's search term became a bound parameter:

```diff
-clauses.append(f"lower(title) LIKE lower('%{title_contains}%')")
+clauses.append("lower(title) LIKE lower(:title_contains)")
+params["title_contains"] = title_contains
```

The injection was closed, every attack case flipped to neutralised, and the
service's own suite passed. The gate failed anyway, on five contract cases:

```
contract-title-fragment-is-case-insensitive  fail  behaviour changed
  recorded: [{"title": "Quarterly Revenue Report", ...}]
  observed: []
contract-count-matches-filter                fail  behaviour changed
  recorded: 1
  observed: 0
```

The `%` wildcards had lived in the *statement*, so moving the value into a
parameter turned a substring search into an exact match: document search returned
nothing for every partial term. A complete outage of the feature, shipped by a
change that genuinely fixed a real SQL injection and passed its tests. The fix
was one line — `params["title_contains"] = f"%{title_contains}%"` — and nothing
except a recorded before-state would have found it, because there is nothing
wrong with the code you are reading.

Two more examples, both fixture defects the same gate refused to grade around.
The subject was `DocumentQueryRepository` in an OtterWorks document service,
which built its `WHERE` clause by interpolating caller values, and the
characterization run looked perfectly healthy: twelve contract cases recorded,
attack cases firing, suite green.

Every owner-scoped case had recorded an empty list.

```
contract-owner-scoped-default-order   []
contract-content-type-filter          []
attack-content-type-tautology         []   ← the exploit "did not reproduce"
```

The fixture ran on SQLite while production runs on PostgreSQL. SQLAlchemy stores
a `uuid` as bare hex on SQLite, and the vulnerable SQL compares the caller's
uuid *as text* — so `owner_id = 'aaaaaaaa-0000-...'` never matched a stored
`aaaaaaaa00004000...`, and every owner-scoped case quietly degraded to "no rows".
A refactor graded against that recording would have proven nothing at all: an
empty list is byte-identical to an empty list no matter what the new code does.
The gate refused to record the before-state because the attack case did not
reproduce, which is what surfaced it. The fix was in the fixture — store the
uuid the way PostgreSQL renders one — after which the same cases recorded real
rows and the tautology returned six documents across two owners.

The same gate then caught a second, subtler fixture defect. One contract case
pinned the error a missing export raises:

```
recorded: FileNotFoundError: ... '/tmp/ow-equivalence-zfirg7xn/archive/absent.md'
observed: FileNotFoundError: ... '/tmp/ow-equivalence-pv6vr242/archive/absent.md'
```

The error message — genuinely part of the observable behavior — embedded the
fixture's temporary directory, so the recording could never reproduce, not even
against unchanged code. The tempting fix is to compare loosely; the correct one
is to make the observation deterministic by redacting the fixture root at capture
time, keeping the *shape* of the error under contract. A gate that fails on its
own before-state is telling you the evidence is not evidence yet.

## Forbidden actions

- Do **not** write the characterization cases after the refactor, or grade a
  refactor against evidence recorded from the refactored code.
- Do **not** edit recorded evidence, seeds, fixtures, cases or detectors to turn
  a gate green, and do not re-record without an audited reason.
- Do **not** change the public interface — names, parameters, defaults, return
  types, raised error types — as a side effect of the fix.
- Do **not** widen the fix into an unrelated refactor. A security PR must stay
  reviewable line by line and back-portable.
- Do **not** suppress or weaken a control to finish: no baseline/allowlist entry
  for the finding, no lowered severity threshold, no deleted test, no skipped
  probe.
- Do **not** claim closure from the unit tests alone when a runtime probe exists,
  and do not claim closure while any check is inconclusive.
- Do **not** commit generated reports or scan output, and do not put customer
  data, credentials or a real exploit payload against a third-party target in the
  evidence.
