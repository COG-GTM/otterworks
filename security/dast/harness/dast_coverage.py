# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "tabulate"]
# ///
"""Gate on DAST *coverage*: which edge-reachable routes the last scan attacked.

A green scan says nothing about a route the suite never sent a request to, and
that is exactly what happens as an application grows: someone adds an endpoint,
the probes still pass, and the new surface ships untested. Nothing in a scanner
report distinguishes "attacked and held" from "never attacked".

This compares two facts:

* the route inventory read from the services' source (`route_inventory`), and
* the paths the last scan actually requested, recorded by the harness in
  ``dast-report.json``.

Coverage has three depths, because they fail differently:

* **reached** — some probe sent this route a request. Within one full scan the
  anonymous sweep enumerates the same inventory this gate reads, so a route it
  managed to send is reached by construction; what the gate catches is the
  remainder, which is not empty: routes excluded from the sweep because sending
  them would carry out a tenant-wide operation, routes the sweep could not
  deliver, and — grading an earlier report, as `make dast-coverage` does after a
  scan of a previous revision — routes added since. A route nothing reached
  fails the gate unless ``security/dast/attack-surface.yaml`` accepts it under
  ``coverage_exemptions`` with a reason, the same debt-with-an-owner rule the
  finding baseline uses.
* **attacked by a written probe** — a request from something other than the
  sweep, i.e. an attack somebody designed for that route rather than a bare
  method call.
* **attacked as a caller** — a request carrying a seeded identity, which is what
  authorization, tenant-isolation and mass-assignment findings need. Both of
  these are hand-written per route, so they are reported rather than gated: the
  numbers are the honest measure of how deep the suite actually goes, and the
  reason a green scan is not the same as a tested surface.

Usage:
    uv run security/dast/harness/dast_coverage.py
    uv run security/dast/harness/dast_coverage.py --report path/to/dast-report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from tabulate import tabulate

sys.path.insert(0, str(Path(__file__).resolve().parent))

from route_inventory import Route, edge_routes, sweep_exclusions

SWEEP = "DAST-ANONYMOUS-ROUTE-SWEEP"

DAST_DIR = Path(__file__).resolve().parents[1]
DEFAULT_REPORT = DAST_DIR / "reports" / "dast-report.json"
ATTACK_SURFACE = DAST_DIR / "attack-surface.yaml"


def load_exemptions(path: Path = ATTACK_SURFACE) -> dict[str, str]:
    """`METHOD /path` -> reason, from the attack surface spec."""
    if not path.exists():
        return {}
    spec = yaml.safe_load(path.read_text()) or {}
    entries = spec.get("coverage_exemptions") or []
    return {
        f"{entry['method'].upper()} {entry['path']}": entry.get("reason", "")
        for entry in entries
        if entry.get("method") and entry.get("path")
    }


def matches(route: Route, method: str, path: str) -> bool:
    """Whether a request the scan issued lands on this declared route.

    The scan requests concrete ids (`/api/v1/documents/ae25…`); the inventory
    holds templates (`/api/v1/documents/{}`), so comparison is per segment.
    """
    if route.method != method:
        return False
    declared = route.path.strip("/").split("/")
    requested = path.strip("/").split("/")
    if len(declared) != len(requested):
        return False
    return all(part in ("{}", other) for part, other in zip(declared, requested, strict=True))


def coverage(
    routes: list[Route], exercised: list[dict[str, str | bool]]
) -> tuple[list[Route], list[Route], list[Route], list[Route]]:
    """(reached, attacked by a written probe, attacked as a caller, missed)."""
    reached, attacked, authenticated, missed = [], [], [], []
    for route in routes:
        hits = [
            request
            for request in exercised
            if matches(route, str(request.get("method", "")), str(request.get("path", "")))
        ]
        if not hits:
            missed.append(route)
            continue
        reached.append(route)
        # A report from before requests carried a probe id cannot tell the sweep
        # from a written probe; counting it as written would overstate the depth.
        if any(request.get("probe") not in (SWEEP, None, "") for request in hits):
            attacked.append(route)
        if any(request.get("authenticated") for request in hits):
            authenticated.append(route)
    return reached, attacked, authenticated, missed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report DAST route coverage.")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="report uncovered routes without failing (exit 0)",
    )
    args = parser.parse_args(argv)

    if not args.report.exists():
        print(
            f"no scan report at {args.report}: run `make dast-scan` first — coverage is "
            "measured from the requests a scan actually issued",
            file=sys.stderr,
        )
        return 2
    report = json.loads(args.report.read_text())
    exercised = report.get("exercised")
    if exercised is None:
        print(
            f"{args.report} predates request recording; re-run `make dast-scan`",
            file=sys.stderr,
        )
        return 2
    if report.get("partial"):
        # `make dast-verify` runs one probe and writes this same report. Grading it
        # would report the whole surface as unattacked, which says nothing about
        # coverage and everything about which probe was asked to run.
        print(
            f"{args.report} is from a single-probe run (`--only`), which requests a "
            "fraction of the surface: coverage cannot be graded from it. Re-run "
            "`make dast-scan` first.",
            file=sys.stderr,
        )
        return 2

    routes, unknown = edge_routes()
    if not routes:
        print("no routes could be read from the services' source", file=sys.stderr)
        return 2

    # A route the sweep is forbidden to send is uncovered for a recorded reason,
    # which is what an exemption is; keeping the reason where the operator wrote it
    # beats making them write it twice.
    exemptions = load_exemptions() | {
        key: f"not swept: {reason}" for key, reason in sweep_exclusions().items()
    }
    reached, attacked, authenticated, uncovered = coverage(routes, exercised)
    gating = [route for route in uncovered if route.key not in exemptions]

    print(
        f"Coverage of the edge-reachable surface, from the last scan of "
        f"{report.get('target', 'unknown target')}:\n"
        f"  reached by a probe:              {len(reached)}/{len(routes)}\n"
        f"  attacked by a written probe:     {len(attacked)}/{len(routes)}\n"
        f"  attacked as a logged-in caller:  {len(authenticated)}/{len(routes)}\n\n"
        "The first number is produced by the anonymous sweep walking this same\n"
        "inventory, so read it as 'the sweep got there', not as 'this is tested'.\n"
        "The lower two are the depth an attacker's questions actually get asked at.\n"
    )
    shallow = [route for route in reached if route not in authenticated]
    if shallow:
        print(
            f"{len(shallow)} route(s) are only swept anonymously — no probe attacks them as "
            "an authenticated caller, so authorization and tenant isolation are unmeasured "
            "there:\n  " + "\n  ".join(route.key for route in shallow) + "\n"
        )
    if uncovered:
        print(
            tabulate(
                [
                    [
                        "EXEMPT" if route.key in exemptions else "UNCOVERED",
                        route.key,
                        route.service,
                        exemptions.get(route.key, ""),
                    ]
                    for route in uncovered
                ],
                headers=["", "route", "service", "reason"],
                tablefmt="simple",
            )
        )
    if unknown:
        # Guessing would be worse than saying so: an unverifiable coverage claim is
        # the exact failure this gate exists to prevent.
        print(
            "\nUnknown coverage — these proxied prefixes belong to services whose routes "
            "are not extractable, so nothing here is being measured:\n  "
            + "\n  ".join(f"{prefix} ({service})" for prefix, service in sorted(unknown.items()))
        )

    if gating:
        verdict = (
            f"{len(gating)} edge-reachable route(s) were never attacked. Add a probe, or "
            "record the route under coverage_exemptions in "
            f"{ATTACK_SURFACE.relative_to(DAST_DIR.parents[1])} with a reason."
        )
        if args.warn_only:
            print(f"\nDAST coverage gate WARNING (--warn-only): {verdict}")
            return 0
        print(f"\nDAST coverage gate FAILED: {verdict}", file=sys.stderr)
        return 1
    print("\nDAST coverage gate PASSED: every edge-reachable route is attacked or exempted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
