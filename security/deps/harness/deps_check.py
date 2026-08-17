# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml", "tabulate"]
# ///
"""
OtterWorks dependency remediation harness.

Three gates, one advisory (security/deps/advisory.yaml):

  inventory   Resolve every registered JVM module's dependency tree and report the
              blast radius of the advisory's artifact: which module pulls it, at
              which version, directly or through which parent, and where the
              version is declared.
  gate        Fail if the vulnerable version is still reachable from any module's
              dependency tree, or if any module could not be measured.
  transcript  Replay the recorded interpolation transcripts through each module's
              own code and grade them:
                policy=contract  the value must be identical to the recording
                policy=attack    the lookup must no longer resolve, leaving the
                                 template text literal in the output
              --stage baseline grades every case against the recording (proving the
              before-state reproduces); --stage remediated applies the policies.

Usage:
    uv run security/deps/harness/deps_check.py inventory
    uv run security/deps/harness/deps_check.py gate
    uv run security/deps/harness/deps_check.py transcript --stage baseline
    uv run security/deps/harness/deps_check.py transcript --stage remediated
    uv run security/deps/harness/deps_check.py transcript --record --reason "..."

Exit codes:
    0 = gate passed
    1 = gate failed (vulnerable version present, or a graded case diverged)
    2 = could not reach a verdict: a module failed to resolve or build, a module on
        disk is not registered, or a recording is stale. Ambiguity fails closed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from tabulate import tabulate

DEPS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = DEPS_DIR.parents[1]
REPORT_DIR = DEPS_DIR / "reports"
EXPECTED_DIR = DEPS_DIR / "expected"
EMITTER_TEST = "DependencyTranscriptEmitterTest"

# Status values are a closed set: a typo becomes a KeyError here rather than a
# module that quietly skips its gate.
PASS, FAIL, MISSING, STALE, UNMEASURED, UNRECORDED = (
    "pass",
    "fail",
    "missing",
    "stale",
    "unmeasured",
    "unrecorded",
)
# MISSING is a mismatch between the recording and the cases it claims to cover (a
# count or ordering divergence) and is a real failure; UNRECORDED means there is no
# recording to compare against at all, which cannot support any verdict.
BLOCKING = {FAIL, MISSING}
INCONCLUSIVE = {STALE, UNMEASURED, UNRECORDED}


class ConfigError(RuntimeError):
    """The harness cannot be trusted to reach a verdict."""


# --------------------------------------------------------------------------- model


@dataclass(frozen=True)
class Advisory:
    id: str
    artifact: str
    title: str
    introduced: str
    fixed: str
    candidates: list[dict[str, str]]

    @property
    def group(self) -> str:
        return self.artifact.split(":")[0]

    @property
    def name(self) -> str:
        return self.artifact.split(":")[1]

    def is_vulnerable(self, version: str) -> bool:
        return version_key(self.introduced) <= version_key(version) < version_key(self.fixed)


@dataclass(frozen=True)
class Module:
    id: str
    path: Path
    build: str
    test: str
    cases: Path | None
    java_home: str | None


@dataclass
class Occurrence:
    version: str
    depth: int
    parent: str | None
    vulnerable: bool


@dataclass
class ModuleTree:
    module: Module
    status: str
    occurrences: list[Occurrence] = field(default_factory=list)
    declarations: list[str] = field(default_factory=list)
    detail: str = ""


def version_key(version: str) -> tuple[Any, ...]:
    """Order Maven-ish versions numerically, with any qualifier sorting first."""
    core, _, qualifier = version.partition("-")
    parts: list[Any] = []
    for piece in core.split("."):
        parts.append(int(piece) if piece.isdigit() else piece)
    while len(parts) < 4:
        parts.append(0)
    return (*parts, qualifier or "~")


# --------------------------------------------------------------------------- config


def load_advisory() -> Advisory:
    raw = yaml.safe_load((DEPS_DIR / "advisory.yaml").read_text())
    vulnerable = raw["vulnerable"]
    return Advisory(
        id=raw["id"],
        artifact=raw["artifact"],
        title=raw["title"],
        introduced=str(vulnerable["introduced"]),
        fixed=str(vulnerable["fixed"]),
        candidates=raw.get("secure_candidates", []),
    )


def resolve_java_home(candidates: list[str] | None) -> str | None:
    """First candidate JDK that exists on this machine, after env expansion."""
    for candidate in candidates or []:
        expanded = os.path.expandvars(candidate)
        if "$" not in expanded and Path(expanded).is_dir():
            return expanded
    return None


def load_modules() -> list[Module]:
    raw = yaml.safe_load((DEPS_DIR / "modules.yaml").read_text())
    modules = []
    for entry in raw["modules"]:
        cases = entry.get("cases")
        candidates = entry.get("java_home")
        java_home = resolve_java_home(candidates)
        if candidates and java_home is None:
            raise ConfigError(
                f"{entry['id']}: none of its JDK candidates exist ({', '.join(candidates)}). "
                "Install one or add a candidate rather than measuring it on the wrong JDK."
            )
        modules.append(
            Module(
                id=entry["id"],
                path=REPO_ROOT / entry["path"],
                build=entry["build"],
                test=entry["test"],
                cases=(DEPS_DIR / cases) if cases else None,
                java_home=java_home,
            )
        )
    discovery_check(modules, raw.get("exempt", []))
    return modules


def discovery_check(modules: list[Module], exempt: list[dict[str, str]]) -> None:
    """A JVM build file that is neither registered nor exempt fails the run."""
    registered = {module.path.resolve() for module in modules}
    exempt_paths = [(REPO_ROOT / item["path"]).resolve() for item in exempt]
    unregistered = []
    for pattern in ("**/pom.xml", "**/build.gradle", "**/build.gradle.kts"):
        for build_file in REPO_ROOT.glob(pattern):
            parts = set(build_file.parts)
            if parts & {"target", "build", "node_modules", ".git"}:
                continue
            module_dir = build_file.parent.resolve()
            if module_dir in registered:
                continue
            if any(module_dir == item or item in module_dir.parents for item in exempt_paths):
                continue
            unregistered.append(str(build_file.relative_to(REPO_ROOT)))
    if unregistered:
        raise ConfigError(
            "JVM build files are neither registered in modules.yaml nor exempt, so the "
            "blast radius would be incomplete: " + ", ".join(sorted(unregistered))
        )


# --------------------------------------------------------------------------- trees


def run(command: str, cwd: Path, module: Module) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if module.java_home:
        env["JAVA_HOME"] = module.java_home
    return subprocess.run(
        shlex.split(command),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


# Maven indents 3 characters per level ("+- ", "|  "), Gradle 5 ("+--- ", "|    ").
MAVEN_LINE = re.compile(r"^([| +\\-]*)([\w.\-]+):([\w.\-]+):(\w+):([\w.\-]+)")
GRADLE_LINE = re.compile(r"^([| +\\-]*)([\w.\-]+):([\w.\-]+):([\w.\-]+(?: -> [\w.\-]+)?)")
INDENT_WIDTH = {"maven": 3, "gradle": 5}


def maven_tree(module: Module) -> tuple[str, list[str], str]:
    with tempfile.NamedTemporaryFile("r+", suffix=".txt") as handle:
        result = run(
            f"mvn -B -q dependency:tree -DoutputType=text -DoutputFile={handle.name}",
            module.path,
            module,
        )
        text = Path(handle.name).read_text()
    if result.returncode != 0 or not text.strip():
        return UNMEASURED, [], (result.stderr or result.stdout)[-2000:]
    return PASS, text.splitlines(), ""


def gradle_tree(module: Module) -> tuple[str, list[str], str]:
    result = run(
        "gradle dependencies --configuration runtimeClasspath --no-daemon --console=plain",
        module.path,
        module,
    )
    if result.returncode != 0:
        return UNMEASURED, [], (result.stderr or result.stdout)[-2000:]
    return PASS, result.stdout.splitlines(), ""


def parse_tree(lines: list[str], advisory: Advisory, build: str) -> list[Occurrence]:
    """Walk the printed tree, tracking the ancestor stack to name the parent.

    `depth` is the tree level: 1 is a dependency the module declares itself, 2+
    arrives through the parent recorded at the level above.
    """
    occurrences: list[Occurrence] = []
    pattern = MAVEN_LINE if build == "maven" else GRADLE_LINE
    width = INDENT_WIDTH[build]
    stack: dict[int, str] = {}
    for line in lines:
        match = pattern.match(line.replace("[INFO] ", ""))
        if not match:
            continue
        depth = len(match.group(1)) // width
        if build == "maven":
            group, name, version = match.group(2), match.group(3), match.group(5)
        else:
            group, name, raw_version = match.group(2), match.group(3), match.group(4)
            # "1.9 -> 1.10.0" means Gradle resolved the conflict to the right-hand side.
            version = raw_version.split("->")[-1].strip()
        stack[depth] = f"{group}:{name}:{version}"
        if group == advisory.group and name == advisory.name:
            occurrences.append(
                Occurrence(
                    version=version,
                    depth=depth,
                    parent=stack.get(depth - 1),
                    vulnerable=advisory.is_vulnerable(version),
                )
            )
    return occurrences


def find_declarations(module: Module, advisory: Advisory) -> list[str]:
    """Where a human has to edit: build files naming the artifact or its version property."""
    hits = []
    for name in ("pom.xml", "build.gradle", "build.gradle.kts", "gradle.properties"):
        build_file = module.path / name
        if not build_file.exists():
            continue
        for number, line in enumerate(build_file.read_text().splitlines(), start=1):
            if advisory.name in line or f"{advisory.group}:{advisory.name}" in line:
                hits.append(f"{build_file.relative_to(REPO_ROOT)}:{number}")
    return hits


def collect_trees(advisory: Advisory, modules: list[Module]) -> list[ModuleTree]:
    trees = []
    for module in modules:
        reader = maven_tree if module.build == "maven" else gradle_tree
        status, lines, detail = reader(module)
        tree = ModuleTree(module=module, status=status, detail=detail)
        if status == PASS:
            tree.occurrences = parse_tree(lines, advisory, module.build)
            tree.declarations = find_declarations(module, advisory)
        trees.append(tree)
    return trees


# ----------------------------------------------------------------------- reporting


def write_report(name: str, payload: dict[str, Any]) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / name
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return path


def inventory_rows(advisory: Advisory, trees: list[ModuleTree]) -> list[list[str]]:
    rows = []
    for tree in trees:
        if tree.status != PASS:
            rows.append([tree.module.id, tree.module.build, UNMEASURED, "-", "-", "-"])
            continue
        if not tree.occurrences:
            rows.append([tree.module.id, tree.module.build, "clean", "-", "-", "-"])
            continue
        for occurrence in tree.occurrences:
            rows.append(
                [
                    tree.module.id,
                    tree.module.build,
                    "VULNERABLE" if occurrence.vulnerable else "ok",
                    occurrence.version,
                    "direct" if occurrence.depth == 1 else f"via {occurrence.parent}",
                    ", ".join(tree.declarations) or "(not declared here)",
                ]
            )
    return rows


def print_inventory(advisory: Advisory, trees: list[ModuleTree]) -> None:
    print(f"{advisory.id}: {advisory.artifact} vulnerable in "
          f"[{advisory.introduced}, {advisory.fixed}) — {advisory.title}")
    print()
    print(
        tabulate(
            inventory_rows(advisory, trees),
            headers=["module", "build", "status", "version", "path", "declared at"],
            tablefmt="github",
        )
    )


def inventory_payload(advisory: Advisory, trees: list[ModuleTree]) -> dict[str, Any]:
    return {
        "advisory": advisory.id,
        "artifact": advisory.artifact,
        "vulnerable_range": {"introduced": advisory.introduced, "fixed": advisory.fixed},
        "generated_at": datetime.now(UTC).isoformat(),
        "modules": [
            {
                "id": tree.module.id,
                "build": tree.module.build,
                "status": tree.status,
                "detail": tree.detail,
                "declarations": tree.declarations,
                "occurrences": [
                    {
                        "version": occurrence.version,
                        "scope": "direct" if occurrence.depth == 1 else "transitive",
                        "parent": occurrence.parent,
                        "vulnerable": occurrence.vulnerable,
                    }
                    for occurrence in tree.occurrences
                ],
            }
            for tree in trees
        ],
    }


# --------------------------------------------------------------------------- gates


def command_inventory(advisory: Advisory, modules: list[Module]) -> int:
    trees = collect_trees(advisory, modules)
    print_inventory(advisory, trees)
    path = write_report("inventory.json", inventory_payload(advisory, trees))
    print(f"\nreport: {path.relative_to(REPO_ROOT)}")
    return 2 if any(tree.status != PASS for tree in trees) else 0


def command_gate(advisory: Advisory, modules: list[Module]) -> int:
    trees = collect_trees(advisory, modules)
    print_inventory(advisory, trees)
    payload = inventory_payload(advisory, trees)
    unmeasured = [tree.module.id for tree in trees if tree.status != PASS]
    vulnerable = [
        f"{tree.module.id} -> {advisory.artifact}:{occurrence.version}"
        + ("" if occurrence.depth == 1 else f" (via {occurrence.parent})")
        for tree in trees
        for occurrence in tree.occurrences
        if occurrence.vulnerable
    ]
    payload["verdict"] = {"vulnerable": vulnerable, "unmeasured": unmeasured}
    path = write_report("gate.json", payload)
    print(f"\nreport: {path.relative_to(REPO_ROOT)}")

    if unmeasured:
        for tree in trees:
            if tree.status != PASS:
                print(f"\n{tree.module.id}: could not resolve its dependency tree\n{tree.detail}",
                      file=sys.stderr)
        print(f"\nGATE INCONCLUSIVE: {len(unmeasured)} module(s) unmeasured: "
              f"{', '.join(unmeasured)}", file=sys.stderr)
        return 2
    if vulnerable:
        print(f"\nGATE FAILED: {advisory.id} still reachable:", file=sys.stderr)
        for item in vulnerable:
            print(f"  - {item}", file=sys.stderr)
        return 1
    print(f"\nGATE PASSED: no {advisory.artifact} version in "
          f"[{advisory.introduced}, {advisory.fixed}) in any measured tree "
          f"({len(trees)} modules).")
    return 0


def command_tests(modules: list[Module], only: str | None) -> int:
    """Build and run each module's own suite, so pre/post regression evidence is one command."""
    targets = [module for module in modules if not only or module.id == only]
    if not targets:
        raise ConfigError(f"no registered module matches {only!r}")
    results = []
    for module in targets:
        started = datetime.now(UTC)
        result = run(module.test, module.path, module)
        output = result.stdout + result.stderr
        results.append(
            {
                "module": module.id,
                "command": module.test,
                "status": PASS if result.returncode == 0 else FAIL,
                "exit_code": result.returncode,
                "seconds": round((datetime.now(UTC) - started).total_seconds(), 1),
                "summary": test_summary(module, output),
                "tail": output[-4000:],
            }
        )
    print(
        tabulate(
            [[r["module"], r["status"], r["seconds"], r["summary"]] for r in results],
            headers=["module", "status", "seconds", "suite"],
            tablefmt="github",
        )
    )
    path = write_report(
        "tests.json",
        {"generated_at": datetime.now(UTC).isoformat(), "modules": results},
    )
    print(f"\nreport: {path.relative_to(REPO_ROOT)}")
    failed = [result for result in results if result["status"] == FAIL]
    for result in failed:
        print(f"\n{result['module']}: `{result['command']}` exited {result['exit_code']}\n"
              f"{result['tail']}", file=sys.stderr)
    if failed:
        print(f"\nTESTS FAILED: {', '.join(result['module'] for result in failed)}",
              file=sys.stderr)
        return 1
    print(f"\nTESTS PASSED: {len(results)} modules.")
    return 0


TEST_COUNTS = (
    re.compile(r"Tests run: \d+, Failures: \d+, Errors: \d+, Skipped: \d+"),  # surefire
    re.compile(r"\d+ tests? completed(?:, \d+ failed)?(?:, \d+ skipped)?"),  # gradle
)
TESTSUITE_ATTRS = re.compile(r"<testsuite\s([^>]*)>")


def test_summary(module: Module, output: str) -> str:
    """The suite's own counts — the number that goes in the PR as pre/post evidence."""
    for pattern in TEST_COUNTS:
        matches = pattern.findall(output)
        if matches:
            return matches[-1]
    # Gradle only prints counts when a test fails, so read the counts off its JUnit XML
    # instead. Attributes are pulled with a regex rather than an XML parser: this is our
    # own build output, and the harness stays dependency-free.
    reports = sorted(module.path.glob("build/test-results/test/TEST-*.xml"))
    if reports:
        totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for report in reports:
            found = TESTSUITE_ATTRS.search(report.read_text())
            attrs = found.group(1) if found else ""
            for key in totals:
                count = re.search(rf'{key}="(\d+)"', attrs)
                totals[key] += int(count.group(1)) if count else 0
        return (
            f"Tests run: {totals['tests']}, Failures: {totals['failures']}, "
            f"Errors: {totals['errors']}, Skipped: {totals['skipped']}"
        )
    return "(no count line in the build log)"


# ---------------------------------------------------------------------- transcripts


def cases_digest(module: Module) -> str:
    return hashlib.sha256(module.cases.read_bytes()).hexdigest()


def emit_transcript(module: Module) -> dict[str, Any]:
    """Run the module's own emitter test and read back the observed transcript."""
    observed = Path(tempfile.mkdtemp(prefix="ow-deps-")) / f"{module.id}.json"
    properties = f"-Dow.deps.cases={module.cases} -Dow.deps.observed={observed}"
    if module.build == "maven":
        command = (
            f"mvn -B test -Dtest={EMITTER_TEST} -DfailIfNoTests=false "
            f"-Dsurefire.failIfNoSpecifiedTests=false {properties}"
        )
    else:
        command = f"gradle test --no-daemon --console=plain --tests '*{EMITTER_TEST}' {properties}"
    result = run(command, module.path, module)
    if not observed.exists():
        raise ConfigError(
            f"{module.id}: the transcript emitter produced no output. Command:\n  {command}\n"
            + (result.stderr or result.stdout)[-2000:]
        )
    payload = json.loads(observed.read_text())
    shutil.rmtree(observed.parent, ignore_errors=True)
    return payload


def case_specs(module: Module) -> list[dict[str, Any]]:
    return json.loads(module.cases.read_text())["cases"]


def same_outcome(recorded: dict[str, Any], observed: dict[str, Any]) -> bool:
    """Compare outcome and value; error messages are diagnostics, types are the contract."""
    if recorded["outcome"] != observed["outcome"]:
        return False
    if recorded["outcome"] == "ok":
        return recorded.get("value") == observed.get("value")
    return recorded.get("error_type") == observed.get("error_type")


def grade_module(module: Module, stage: str) -> dict[str, Any]:
    expected_path = EXPECTED_DIR / f"{module.id}.json"
    if not expected_path.exists():
        return {"module": module.id, "status": UNRECORDED,
                "detail": f"no recorded transcript at {expected_path.relative_to(REPO_ROOT)}"}
    recorded = json.loads(expected_path.read_text())
    if recorded.get("cases_sha256") != cases_digest(module):
        return {
            "module": module.id,
            "status": STALE,
            "detail": (
                f"{module.cases.relative_to(REPO_ROOT)} changed since it was recorded; "
                "re-record with --record --reason '<why>' --allow-rerecord"
            ),
        }

    observed = emit_transcript(module)
    specs = case_specs(module)
    recorded_cases = recorded["cases"]
    observed_cases = observed["cases"]
    if len(observed_cases) != len(specs) or len(recorded_cases) != len(specs):
        return {"module": module.id, "status": MISSING,
                "detail": f"expected {len(specs)} cases, recorded {len(recorded_cases)}, "
                          f"observed {len(observed_cases)}"}

    results = []
    # Order is compared as recorded: neither side is sorted or canonicalised.
    for spec, want, got in zip(specs, recorded_cases, observed_cases, strict=True):
        if not (spec["id"] == want["id"] == got["id"]):
            return {"module": module.id, "status": MISSING,
                    "detail": f"case order diverged at {spec['id']}: "
                              f"recorded {want['id']}, observed {got['id']}"}
        policy = spec["policy"]
        if policy == "contract" or stage == "baseline":
            ok = same_outcome(want, got)
            why = "" if ok else f"recorded {summarise(want)}, observed {summarise(got)}"
        elif policy == "attack":
            marker = spec["attack_marker"]
            ok = (
                got["outcome"] == "ok"
                and marker in got.get("value", "")
                and not same_outcome(want, got)
            )
            why = "" if ok else (
                f"lookup not neutralized: recorded {summarise(want)}, observed "
                f"{summarise(got)}, expected the literal {marker!r} to survive"
            )
        else:
            raise ConfigError(f"{module.id}/{spec['id']}: unknown policy {policy!r}")
        results.append({"id": spec["id"], "policy": policy,
                        "status": PASS if ok else FAIL, "detail": why,
                        "recorded": want, "observed": got})

    failed = [case for case in results if case["status"] == FAIL]
    return {
        "module": module.id,
        "status": FAIL if failed else PASS,
        "cases": results,
        "failed": [case["id"] for case in failed],
    }


def summarise(case: dict[str, Any]) -> str:
    if case["outcome"] == "ok":
        return f"ok {case.get('value')!r}"
    return f"error {case.get('error_type')} ({case.get('error_message')})"


def command_transcript(modules: list[Module], stage: str, only: str | None) -> int:
    graded = [module for module in modules if module.cases and (not only or module.id == only)]
    if not graded:
        raise ConfigError(f"no module with recorded cases matches {only!r}")

    results = [grade_module(module, stage) for module in graded]
    rows = [
        [
            result["module"],
            result["status"],
            len(result.get("cases", [])),
            ", ".join(result.get("failed", [])) or result.get("detail", ""),
        ]
        for result in results
    ]
    print(f"transcript stage: {stage}")
    print(tabulate(rows, headers=["module", "status", "cases", "detail"], tablefmt="github"))

    for result in results:
        for case in result.get("cases", []):
            if case["status"] == FAIL:
                print(f"\n{result['module']}/{case['id']} ({case['policy']}): {case['detail']}",
                      file=sys.stderr)

    path = write_report(
        f"transcript-{stage}.json",
        {"stage": stage, "generated_at": datetime.now(UTC).isoformat(), "modules": results},
    )
    print(f"\nreport: {path.relative_to(REPO_ROOT)}")

    statuses = {result["status"] for result in results}
    if statuses & INCONCLUSIVE:
        print("\nTRANSCRIPT INCONCLUSIVE: recorded evidence is stale or absent.",
              file=sys.stderr)
        return 2
    if statuses & BLOCKING:
        print("\nTRANSCRIPT FAILED: behavior diverged from the recording.", file=sys.stderr)
        return 1
    print(f"\nTRANSCRIPT PASSED: {sum(len(r['cases']) for r in results)} cases across "
          f"{len(results)} modules.")
    return 0


def command_record(advisory: Advisory, modules: list[Module], reason: str,
                   allow_rerecord: bool, only: str | None) -> int:
    targets = [module for module in modules if module.cases and (not only or module.id == only)]
    if not targets:
        raise ConfigError(f"no module with cases matches {only!r}")
    EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
    for module in targets:
        path = EXPECTED_DIR / f"{module.id}.json"
        if path.exists() and not allow_rerecord:
            raise ConfigError(
                f"{path.relative_to(REPO_ROOT)} already exists. Re-recording overwrites the "
                "evidence the gate compares against; pass --allow-rerecord with a reason that "
                "says why the old recording is wrong."
            )
        observed = emit_transcript(module)
        specs = case_specs(module)
        if len(observed["cases"]) != len(specs):
            raise ConfigError(
                f"{module.id}: emitter returned {len(observed['cases'])} cases for "
                f"{len(specs)} specs"
            )
        payload = {
            "module": module.id,
            "advisory": advisory.id,
            "artifact": advisory.artifact,
            "cases_sha256": cases_digest(module),
            "recorded_at": datetime.now(UTC).isoformat(),
            "reason": reason,
            "cases": observed["cases"],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"recorded {len(observed['cases'])} cases -> {path.relative_to(REPO_ROOT)}")
    return 0


# ---------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inventory", help="report the blast radius of the advisory")
    sub.add_parser("gate", help="fail if the vulnerable version is still reachable")
    tests = sub.add_parser("tests", help="build and run every registered module's suite")
    tests.add_argument("--module")

    transcript = sub.add_parser("transcript", help="grade recorded interpolation transcripts")
    transcript.add_argument("--stage", choices=["baseline", "remediated"], default="remediated")
    transcript.add_argument("--module")
    transcript.add_argument("--record", action="store_true",
                            help="write the observed transcripts as the recording")
    transcript.add_argument("--reason", help="why this recording is the truth (required)")
    transcript.add_argument("--allow-rerecord", action="store_true",
                            help="overwrite an existing recording")

    args = parser.parse_args(argv)
    try:
        advisory = load_advisory()
        modules = load_modules()
        if args.command == "inventory":
            return command_inventory(advisory, modules)
        if args.command == "gate":
            return command_gate(advisory, modules)
        if args.command == "tests":
            return command_tests(modules, args.module)
        if args.record:
            if not args.reason:
                raise ConfigError("--record requires --reason: recordings are audited evidence")
            return command_record(advisory, modules, args.reason, args.allow_rerecord, args.module)
        return command_transcript(modules, args.stage, args.module)
    except ConfigError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
