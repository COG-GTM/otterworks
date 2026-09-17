#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.2", "tabulate==0.10.0", "cvss==3.4"]
# ///
"""Software-composition gate for the ecosystems the Snyk-backed scan never reached.

One registry (security/sca/projects.yaml), one scanner per ecosystem, one
baseline (security/sca/baseline.yaml). Every scanner here reads a manifest or a
resolved dependency tree locally and queries a public advisory database, so a
full run consumes no Snyk private tests.

    scan      resolve -> scan -> normalise -> diff against the baseline
    baseline  record the current findings as the accepted set
    list      show the registry and which scanners this machine can run

Exit codes match the other security harnesses in this repository:

    0  every registered project in scope was measured and matched the baseline
    1  a finding outside the baseline was measured
    2  at least one project could not be measured, or a manifest on disk is
       neither registered nor exempt -- no verdict, never treated as clean
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from fnmatch import fnmatch
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml
from cvss import CVSS2, CVSS3, CVSS4
from cvss.exceptions import CVSSError
from tabulate import tabulate

REPO_ROOT = Path(__file__).resolve().parents[3]
SCA_DIR = REPO_ROOT / "security" / "sca"
PROJECTS_FILE = SCA_DIR / "projects.yaml"
BASELINE_FILE = SCA_DIR / "baseline.yaml"
REPORT_DIR = SCA_DIR / "reports"

OSV_QUERY_BATCH = "https://api.osv.dev/v1/querybatch"
OSV_VULN = "https://api.osv.dev/v1/vulns/"

MANIFEST_GLOBS = [
    "go.mod",
    "Cargo.toml",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "build.sbt",
    "pyproject.toml",
    "requirements.txt",
    "package-lock.json",
    "Gemfile",
    "*.csproj",
]
SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", ".venv", "vendor", ".gradle"}

# `osv` needs no local binary: the coordinates come from the module's own build tool.
SCANNER_BINARY = {
    "govulncheck": "govulncheck",
    "cargo-audit": "cargo-audit",
    "pip-audit": "pip-audit",
    "npm-audit": "npm",
    "osv": None,
}


@dataclass
class Finding:
    ecosystem: str
    project: str
    package: str
    version: str
    advisory: str
    severity: str = "unknown"
    fixed: str = ""
    summary: str = ""
    called: str = ""

    @property
    def key(self) -> str:
        # Deliberately version-free: a lock-file bump that leaves the advisory
        # applicable must stay recorded, not reappear as a new finding.
        return f"{self.ecosystem}|{self.project}|{self.package}|{self.advisory}"

    def as_dict(self) -> dict[str, str]:
        return {k: v for k, v in self.__dict__.items() if v != ""}


@dataclass
class ProjectResult:
    ecosystem: str
    project: str
    path: str
    scanner: str
    status: str  # measured | unmeasured | skipped
    detail: str = ""
    findings: list[Finding] = field(default_factory=list)


class Unmeasured(Exception):
    """A project could not be scanned, so it has no verdict."""


def run(cmd: list[str], cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
    )


def load_registry() -> dict[str, Any]:
    return yaml.safe_load(PROJECTS_FILE.read_text())


def load_baseline() -> dict[str, Any]:
    if not BASELINE_FILE.exists():
        return {"findings": []}
    return yaml.safe_load(BASELINE_FILE.read_text()) or {"findings": []}


def resolve_candidate(candidates: Iterable[str], cwd: Path) -> str | None:
    """First candidate that exists: an env var, an absolute path, or a PATH entry."""
    for raw in candidates:
        candidate = os.path.expandvars(raw) if raw.startswith("$") else raw
        if not candidate or candidate.startswith("$"):
            continue
        if candidate.startswith("./"):
            if (cwd / candidate).exists():
                return str((cwd / candidate).resolve())
            continue
        if Path(candidate).is_absolute():
            if Path(candidate).exists():
                return candidate
            continue
        found = shutil.which(candidate)
        if found:
            return found
    return None


def jvm_env(project: dict[str, Any], cwd: Path) -> dict[str, str]:
    env = dict(os.environ)
    home = resolve_candidate(project.get("java_home", []), cwd)
    if home:
        env["JAVA_HOME"] = home
        env["PATH"] = f"{home}/bin:{env['PATH']}"
    return env


# --------------------------------------------------------------------------
# scanners
# --------------------------------------------------------------------------


def scan_go(project: dict[str, Any], cwd: Path) -> list[Finding]:
    tool = shutil.which("govulncheck")
    if not tool:
        raise Unmeasured("govulncheck is not installed")
    proc = run([tool, "-format", "json", "./..."], cwd)
    if not proc.stdout.strip():
        raise Unmeasured(f"govulncheck produced no output: {proc.stderr.strip()[:200]}")
    decoder = json.JSONDecoder()
    text, index, messages = proc.stdout, 0, []
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        obj, index = decoder.raw_decode(text, index)
        messages.append(obj)

    advisories = {m["osv"]["id"]: m["osv"] for m in messages if "osv" in m}
    findings: dict[str, Finding] = {}
    for message in messages:
        raw = message.get("finding")
        if not raw:
            continue
        trace = raw.get("trace") or [{}]
        module = trace[0].get("module", "unknown")
        called = "yes" if any(entry.get("function") for entry in trace) else "no"
        osv = advisories.get(raw["osv"], {})
        finding = Finding(
            ecosystem="go",
            project=project["id"],
            package=module,
            version=trace[0].get("version", ""),
            advisory=raw["osv"],
            severity=osv_severity(osv),
            fixed=raw.get("fixed_version", ""),
            summary=(osv.get("summary") or "").strip(),
            called=called,
        )
        existing = findings.get(finding.key)
        if existing is None or (called == "yes" and existing.called != "yes"):
            findings[finding.key] = finding
    return list(findings.values())


def scan_rust(project: dict[str, Any], cwd: Path) -> list[Finding]:
    if not shutil.which("cargo-audit") and not shutil.which("cargo"):
        raise Unmeasured("cargo-audit is not installed")
    # CARGO_AUDIT_DB points at a checkout of the RustSec advisory database. CI
    # sets it so the scan reads a database fetched by a retrying checkout step
    # instead of cargo-audit's own clone, which the runners get rate-limited out
    # of; `-n` then keeps it from fetching again.
    database = os.environ.get("CARGO_AUDIT_DB")
    extra = ["-d", database, "-n"] if database else []
    proc = run(["cargo", "audit", *extra, "--json"], cwd)
    if not proc.stdout.strip():
        raise Unmeasured(f"cargo-audit produced no output: {proc.stderr.strip()[-400:]}")
    report = json.loads(proc.stdout)
    findings = []
    for entry in report.get("vulnerabilities", {}).get("list", []) or []:
        advisory, package = entry["advisory"], entry["package"]
        patched = (entry.get("versions") or {}).get("patched") or []
        findings.append(
            Finding(
                ecosystem="rust",
                project=project["id"],
                package=package["name"],
                version=package.get("version", ""),
                advisory=advisory["id"],
                severity=cvss_severity((advisory.get("cvss") or "")),
                fixed=", ".join(patched),
                summary=advisory.get("title", ""),
            )
        )
    # `unsound` and `yanked` warnings are advisories too: RustSec files them with
    # the same identifiers, and an unsound crate is exactly the kind of thing a
    # regression gate should hold at its recorded set.
    for kind, entries in (report.get("warnings") or {}).items():
        for entry in entries or []:
            advisory = entry.get("advisory") or {}
            package = entry.get("package") or {}
            if not advisory.get("id"):
                continue
            findings.append(
                Finding(
                    ecosystem="rust",
                    project=project["id"],
                    package=package.get("name", advisory.get("package", "unknown")),
                    version=package.get("version", ""),
                    advisory=advisory["id"],
                    severity=kind,
                    fixed=", ".join((entry.get("versions") or {}).get("patched") or []),
                    summary=advisory.get("title", ""),
                )
            )
    return findings


def python_requirements(project: dict[str, Any], cwd: Path) -> list[Path]:
    """Requirements files to audit, resolving from a lock file when one is used."""
    lockfile = project.get("lockfile")
    if lockfile:
        # Read the lock directly rather than shelling out to the package manager:
        # `poetry export` lives in a plugin that is not installed everywhere, and the
        # lock already holds the resolved tree this service ships.
        locked = cwd / lockfile
        if not locked.exists():
            raise Unmeasured(f"missing lock file: {locked.relative_to(REPO_ROOT)}")
        packages = tomllib.loads(locked.read_text()).get("package", [])
        if not packages:
            raise Unmeasured(f"{lockfile} pins no packages")
        resolved = REPORT_DIR / f"requirements-{project['id']}.txt"
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(
            "".join(f"{package['name']}=={package['version']}\n" for package in packages)
        )
        return [resolved]
    export = project.get("export")
    if export:
        argv = shlex.split(export)
        tool = shutil.which(argv[0])
        if not tool:
            raise Unmeasured(f"{argv[0]} is not installed, cannot export the locked tree")
        proc = run([tool, *argv[1:]], cwd)
        if proc.returncode != 0:
            raise Unmeasured(f"{argv[0]} export failed: {proc.stderr.strip()[:200]}")
        exported = REPORT_DIR / f"requirements-{project['id']}.txt"
        exported.parent.mkdir(parents=True, exist_ok=True)
        exported.write_text(proc.stdout)
        return [exported]
    files = [cwd / name for name in project.get("requirements", ["requirements.txt"])]
    missing = [f for f in files if not f.exists()]
    if missing:
        raise Unmeasured(f"missing requirements file: {missing[0].relative_to(REPO_ROOT)}")
    return files


def scan_python_osv(project: dict[str, Any], cwd: Path) -> list[Finding]:
    """Query the pinned requirements against OSV, without resolving the tree."""
    pins = []
    for requirements in python_requirements(project, cwd):
        for line in requirements.read_text().splitlines():
            entry = line.split("#")[0].strip()
            if "==" not in entry:
                continue
            name, _, version = entry.partition("==")
            pins.append((name.strip().split("[")[0], version.strip().split(" ")[0]))
    if not pins:
        raise Unmeasured("no pinned requirements to query")
    findings = []
    for (name, version), advisories in osv_query(sorted(set(pins)), "PyPI").items():
        for advisory in advisories:
            details = osv_details(advisory)
            findings.append(
                Finding(
                    ecosystem="python",
                    project=project["id"],
                    package=name,
                    version=version,
                    advisory=advisory,
                    severity=osv_severity(details),
                    summary=(details.get("summary") or "").strip()[:160],
                )
            )
    return findings


def scan_python(project: dict[str, Any], cwd: Path) -> list[Finding]:
    if project.get("resolver") == "osv":
        return scan_python_osv(project, cwd)
    tool = shutil.which("pip-audit")
    if not tool:
        raise Unmeasured("pip-audit is not installed")
    findings = []
    extra = shlex.split(project.get("args", ""))
    for requirements in python_requirements(project, cwd):
        proc = run(
            [tool, "--format", "json", "--progress-spinner", "off", *extra, "-r",
             str(requirements)],
            cwd,
        )
        if not proc.stdout.strip():
            raise Unmeasured(f"pip-audit produced no output: {proc.stderr.strip()[:200]}")
        report = json.loads(proc.stdout)
        for dependency in report.get("dependencies", []):
            for vulnerability in dependency.get("vulns", []) or []:
                findings.append(
                    Finding(
                        ecosystem="python",
                        project=project["id"],
                        package=dependency["name"],
                        version=dependency.get("version", ""),
                        advisory=vulnerability["id"],
                        fixed=", ".join(vulnerability.get("fix_versions") or []),
                        summary=(vulnerability.get("description") or "").split("\n")[0][:160],
                    )
                )
    return findings


def scan_npm(project: dict[str, Any], cwd: Path) -> list[Finding]:
    tool = shutil.which("npm")
    if not tool:
        raise Unmeasured("npm is not installed")
    if not (cwd / "package-lock.json").exists():
        raise Unmeasured("no package-lock.json to audit")
    proc = run([tool, "audit", "--json"], cwd)
    if not proc.stdout.strip():
        raise Unmeasured(f"npm audit produced no output: {proc.stderr.strip()[:200]}")
    report = json.loads(proc.stdout)
    # npm exits nonzero both for advisories and for operational failures, and in
    # JSON mode the latter arrive as a top-level `error`. Without this, a lock
    # file npm cannot read reads as a project with no advisories.
    if report.get("error"):
        raise Unmeasured(f"npm audit failed: {str(report['error'])[:200]}")
    findings = {}
    for name, entry in (report.get("vulnerabilities") or {}).items():
        for via in entry.get("via", []):
            if not isinstance(via, dict):
                continue  # a string `via` is a transitive pointer to another entry
            advisory = (via.get("url") or "").rsplit("/", 1)[-1] or str(via.get("source", ""))
            finding = Finding(
                ecosystem="npm",
                project=project["id"],
                package=via.get("name", name),
                version=via.get("range", ""),
                advisory=advisory,
                severity=via.get("severity", "unknown"),
                summary=via.get("title", ""),
            )
            findings[finding.key] = finding
    return list(findings.values())


def jvm_coordinates(project: dict[str, Any], cwd: Path) -> list[tuple[str, str]]:
    build = project["build"]
    env = jvm_env(project, cwd)
    if build == "maven":
        tool = resolve_candidate(project.get("tool", ["mvn"]), cwd)
        if not tool:
            raise Unmeasured("no maven available")
        proc = subprocess.run(
            [tool, "-B", "-q", "dependency:list", "-DincludeScope=runtime", "-DoutputFile=/dev/stdout"],
            cwd=cwd, env=env, capture_output=True, text=True, timeout=1800, check=False,
        )
        if proc.returncode != 0:
            raise Unmeasured(f"dependency:list failed: {tail(proc)}")
        coordinates = []
        for line in proc.stdout.splitlines():
            parts = line.strip().split(":")
            if len(parts) >= 5 and parts[2] in {"jar", "war", "pom"}:
                coordinates.append((f"{parts[0]}:{parts[1]}", parts[3]))
        return coordinates
    if build == "gradle":
        tool = resolve_candidate(project.get("tool", ["gradle"]), cwd)
        if not tool:
            raise Unmeasured("no gradle available")
        proc = subprocess.run(
            [tool, "-q", "--console=plain", "--no-daemon", "dependencies",
             "--configuration", "runtimeClasspath"],
            cwd=cwd, env=env, capture_output=True, text=True, timeout=1800, check=False,
        )
        if proc.returncode != 0:
            raise Unmeasured(f"gradle dependencies failed: {tail(proc)}")
        coordinates = []
        for line in proc.stdout.splitlines():
            if "(c)" in line:
                continue  # a constraint, not a dependency: it is listed elsewhere
            token = line.split("--- ")[-1].strip()
            if "->" in token:  # resolved version wins over the requested one
                token = f"{token.split('->')[0].rsplit(':', 1)[0]}:{token.split('->')[-1].strip()}"
            parts = token.split(":")
            if len(parts) == 3 and all(parts):
                coordinates.append((f"{parts[0]}:{parts[1]}", parts[2].split(" ")[0]))
        return coordinates
    if build == "sbt":
        tool = resolve_candidate(project.get("tool", ["sbt"]), cwd)
        if not tool:
            raise Unmeasured("no sbt available")
        # -Dsbt.ci, not -batch: the flag spelling differs between the packaged
        # launcher and the coursier one, and both honour the property.
        proc = subprocess.run(
            [tool, "-Dsbt.ci=true", "-Dsbt.log.noformat=true", "dependencyTree"],
            cwd=cwd, env=env, capture_output=True, text=True, timeout=1800, check=False,
        )
        if proc.returncode != 0:
            raise Unmeasured(f"sbt dependencyTree failed: {tail(proc)}")
        coordinates = []
        for line in proc.stdout.splitlines():
            if "(evicted by" in line:  # the evicted version is not on the classpath
                continue
            token = line.replace("[info]", "").strip().lstrip("+-| ")
            parts = token.split(":")
            if len(parts) == 3 and all(parts) and " " not in token:
                coordinates.append((f"{parts[0]}:{parts[1]}", parts[2]))
        return coordinates
    raise Unmeasured(f"unknown build system {build!r}")


def scan_jvm(project: dict[str, Any], cwd: Path) -> list[Finding]:
    coordinates = sorted(set(jvm_coordinates(project, cwd)))
    if not coordinates:
        raise Unmeasured("the build tool resolved no dependencies")
    findings = []
    for (name, version), advisories in osv_query(coordinates, "Maven").items():
        for advisory in advisories:
            details = osv_details(advisory)
            findings.append(
                Finding(
                    ecosystem="jvm",
                    project=project["id"],
                    package=name,
                    version=version,
                    advisory=advisory,
                    severity=osv_severity(details),
                    summary=(details.get("summary") or "").strip()[:160],
                )
            )
    return findings


def tail(proc: subprocess.CompletedProcess[str]) -> str:
    return ((proc.stderr or proc.stdout).strip().splitlines() or ["no output"])[-1][:200]


# --------------------------------------------------------------------------
# OSV
# --------------------------------------------------------------------------

_OSV_CACHE: dict[str, dict[str, Any]] = {}


def osv_query(
    coordinates: list[tuple[str, str]], ecosystem: str
) -> dict[tuple[str, str], list[str]]:
    """Batch-query OSV for a resolved dependency set."""
    results: dict[tuple[str, str], list[str]] = {}
    for start in range(0, len(coordinates), 500):
        chunk = coordinates[start : start + 500]
        payload = {
            "queries": [
                {"package": {"name": name, "ecosystem": ecosystem}, "version": version}
                for name, version in chunk
            ]
        }
        request = urllib.request.Request(
            OSV_QUERY_BATCH,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = json.load(response)
        except (urllib.error.URLError, TimeoutError) as exc:
            raise Unmeasured(f"OSV query failed: {exc}") from exc
        for coordinate, result in zip(chunk, body.get("results", [])):
            ids = [vuln["id"] for vuln in result.get("vulns", []) or []]
            if ids:
                results[coordinate] = ids
    return results


def osv_details(advisory: str) -> dict[str, Any]:
    if advisory not in _OSV_CACHE:
        try:
            with urllib.request.urlopen(OSV_VULN + advisory, timeout=60) as response:
                _OSV_CACHE[advisory] = json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            _OSV_CACHE[advisory] = {}
    return _OSV_CACHE[advisory]


def osv_severity(osv: dict[str, Any]) -> str:
    specific = (osv.get("database_specific") or {}).get("severity")
    if specific:
        return str(specific).lower()
    for severity in osv.get("severity") or []:
        if severity.get("type", "").startswith("CVSS"):
            return cvss_severity(severity.get("score", ""))
    return "unknown"


def cvss_severity(vector_or_score: str) -> str:
    """Map a CVSS vector or score to a coarse band; the exact number is in the advisory.

    OSV and RustSec publish a vector far more often than a number, so a vector is
    scored here rather than reported as `unknown`.
    """
    if not vector_or_score:
        return "unknown"
    try:
        score = float(vector_or_score)
    except ValueError:
        scored = cvss_base_score(vector_or_score)
        if scored is None:
            return "unknown"
        score = scored
    if score >= 9.0:
        return "critical"
    if score >= 7.0:
        return "high"
    if score >= 4.0:
        return "moderate"
    return "low"


def cvss_base_score(vector: str) -> float | None:
    """Base score of a CVSS v2 / v3.x / v4.0 vector, or None if it cannot be scored."""
    try:
        if vector.startswith("CVSS:4"):
            return float(CVSS4(vector).base_score)
        if vector.startswith("CVSS:3"):
            return float(CVSS3(vector).base_score)
        if vector.startswith("AV:"):  # a v2 vector carries no prefix
            return float(CVSS2(vector).base_score)
    except (CVSSError, ValueError):
        return None
    return None


SCANNERS = {
    "go": scan_go,
    "rust": scan_rust,
    "python": scan_python,
    "jvm": scan_jvm,
    "npm": scan_npm,
}


# --------------------------------------------------------------------------
# registry discovery
# --------------------------------------------------------------------------


def discover_manifests() -> list[Path]:
    found = []
    for path in REPO_ROOT.rglob("*"):
        if path.is_dir():
            continue
        if SKIP_DIRS & set(path.relative_to(REPO_ROOT).parts):
            continue
        if path.is_relative_to(REPORT_DIR):  # this harness's own output
            continue
        name = path.name
        if name in MANIFEST_GLOBS or (name.endswith(".csproj")) or (
            name.startswith("requirements") and name.endswith(".txt")
        ):
            found.append(path)
    return sorted(found)


def unregistered_manifests(registry: dict[str, Any]) -> list[str]:
    """Manifests on disk that no scanner owns.

    A registered project covers the manifests of its *own* ecosystem only: a
    Cargo.toml dropped inside an npm project is scanned by nobody, so it has to
    surface here instead of inheriting that project's registration. Exemptions
    stay prefix-wide, because an exemption is a deliberate claim about a subtree.
    """
    owned: list[tuple[str, set[str]]] = []
    for ecosystem in registry["ecosystems"].values():
        names = set(ecosystem["manifest"].split("|"))
        for project in ecosystem["projects"]:
            owned.append((project["path"], names))
    exempt = [entry["path"] for entry in registry.get("exempt", [])]

    orphans = []
    for manifest in discover_manifests():
        relative = manifest.relative_to(REPO_ROOT).as_posix()
        if any(under(relative, path) for path in exempt):
            continue
        if any(
            under(relative, path) and any(fnmatch(manifest.name, p) for p in names)
            for path, names in owned
        ):
            continue
        orphans.append(relative)
    return orphans


def under(relative: str, path: str) -> bool:
    return relative == path or relative.startswith(f"{path}/")


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------


def selected_projects(
    registry: dict[str, Any], ecosystems: list[str], only: str | None
) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    selection = []
    for name, ecosystem in registry["ecosystems"].items():
        if ecosystems and name not in ecosystems:
            continue
        for project in ecosystem["projects"]:
            if only and project["id"] != only:
                continue
            selection.append((name, ecosystem, project))
    return selection


def scan(args: argparse.Namespace) -> int:
    registry = load_registry()
    ecosystems = [] if args.ecosystem == "all" else [args.ecosystem]
    selection = selected_projects(registry, ecosystems, args.project)
    if not selection:
        print("no project matched the selection", file=sys.stderr)
        return 2

    results = []
    for name, ecosystem, project in selection:
        cwd = REPO_ROOT / project["path"]
        result = ProjectResult(
            ecosystem=name,
            project=project["id"],
            path=project["path"],
            scanner=ecosystem["scanner"],
            status="measured",
        )
        if not cwd.exists():
            result.status, result.detail = "unmeasured", "path does not exist"
        else:
            try:
                measured = {f.key: f for f in SCANNERS[name](project, cwd)}
                result.findings = sorted(measured.values(), key=lambda f: f.key)
            except Unmeasured as exc:
                result.status, result.detail = "unmeasured", str(exc)
            except Exception as exc:  # a broken scanner is unmeasured, never clean
                result.status, result.detail = "unmeasured", f"{type(exc).__name__}: {exc}"
        results.append(result)

    orphans = unregistered_manifests(registry) if args.ecosystem == "all" else []
    baseline = {entry["key"] for entry in load_baseline().get("findings", [])}
    new = [
        finding
        for result in results
        for finding in result.findings
        if finding.key not in baseline
    ]
    unmeasured = [result for result in results if result.status == "unmeasured"]

    write_reports(results, new, orphans, args)
    print(render(results, new, orphans))

    if orphans:
        print(
            "\nVERDICT: inconclusive -- dependency manifests are neither registered in "
            f"{PROJECTS_FILE.relative_to(REPO_ROOT)} nor exempt."
        )
        return 2
    if unmeasured and not args.allow_unmeasured:
        print(
            "\nVERDICT: inconclusive -- "
            f"{len(unmeasured)} project(s) were not measured; an unmeasured project is not clean."
        )
        return 2
    if new:
        print(f"\nVERDICT: fail -- {len(new)} finding(s) outside the recorded baseline.")
        return 1
    print("\nVERDICT: pass -- every measured project matches the recorded baseline.")
    return 0


def render(results: list[ProjectResult], new: list[Finding], orphans: list[str]) -> str:
    rows = [
        [
            result.ecosystem,
            result.project,
            result.scanner,
            result.status,
            len(result.findings) if result.status == "measured" else "-",
            # the table is a summary; sca-report.json carries the full detail
            result.detail.replace("\n", " ")[:60],
        ]
        for result in results
    ]
    out = [
        tabulate(
            rows,
            headers=["ecosystem", "project", "scanner", "status", "findings", "detail"],
            tablefmt="github",
        )
    ]
    if new:
        out.append("\nFindings outside the baseline:\n")
        out.append(
            tabulate(
                [
                    [f.ecosystem, f.project, f.package, f.version, f.advisory, f.severity,
                     f.fixed, f.called]
                    for f in sorted(new, key=lambda f: f.key)
                ],
                headers=["ecosystem", "project", "package", "version", "advisory", "severity",
                         "fixed in", "called"],
                tablefmt="github",
            )
        )
    if orphans:
        out.append("\nUnregistered dependency manifests:\n  " + "\n  ".join(orphans))
    return "\n".join(out)


def write_reports(
    results: list[ProjectResult], new: list[Finding], orphans: list[str], args: argparse.Namespace
) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "selection": {"ecosystem": args.ecosystem, "project": args.project},
        "projects": [
            {
                "ecosystem": r.ecosystem,
                "project": r.project,
                "path": r.path,
                "scanner": r.scanner,
                "status": r.status,
                "detail": r.detail,
                "findings": [f.as_dict() for f in r.findings],
            }
            for r in results
        ],
        "new_findings": [f.as_dict() for f in new],
        "unregistered_manifests": orphans,
    }
    (REPORT_DIR / "sca-report.json").write_text(json.dumps(payload, indent=2) + "\n")
    (REPORT_DIR / "sca-report.md").write_text(
        f"# Dependency scan ({args.ecosystem})\n\n{render(results, new, orphans)}\n"
    )


def baseline(args: argparse.Namespace) -> int:
    report_file = REPORT_DIR / "sca-report.json"
    if not report_file.exists():
        print("run `make sca-scan` first: there is no report to record", file=sys.stderr)
        return 2
    report = json.loads(report_file.read_text())
    if report["selection"]["ecosystem"] != "all" or report["selection"]["project"]:
        print("record the baseline from a full run: `make sca-scan`", file=sys.stderr)
        return 2
    unmeasured = [p["project"] for p in report["projects"] if p["status"] == "unmeasured"]
    if unmeasured and not args.allow_unmeasured:
        print(
            "refusing to record a baseline while these projects are unmeasured: "
            f"{', '.join(unmeasured)} (pass --allow-unmeasured to record the rest, which"
            " leaves them baseline-less and therefore ungated)",
            file=sys.stderr,
        )
        return 2

    findings = []
    for project in report["projects"]:
        for finding in project["findings"]:
            findings.append(
                {
                    "key": "|".join(
                        [
                            finding["ecosystem"],
                            finding["project"],
                            finding["package"],
                            finding["advisory"],
                        ]
                    ),
                    **{k: finding[k] for k in ("ecosystem", "project", "package", "advisory")},
                    "severity": finding.get("severity", "unknown"),
                    "summary": finding.get("summary", ""),
                }
            )
    BASELINE_FILE.write_text(
        yaml.safe_dump(
            {
                "recorded_at": report["generated_at"],
                "reason": args.reason,
                "unmeasured_when_recorded": unmeasured,
                "findings": sorted(findings, key=lambda f: f["key"]),
            },
            sort_keys=False,
            width=100,
        )
    )
    print(f"recorded {len(findings)} finding(s) in {BASELINE_FILE.relative_to(REPO_ROOT)}")
    return 0


def list_registry(_: argparse.Namespace) -> int:
    registry = load_registry()
    rows = []
    for name, ecosystem in registry["ecosystems"].items():
        for project in ecosystem["projects"]:
            scanner = ecosystem["scanner"]
            binary = SCANNER_BINARY.get(scanner)
            available = "yes" if binary is None or shutil.which(binary) else "no"
            rows.append([name, project["id"], project["path"], scanner, available])
    print(
        tabulate(
            rows,
            headers=["ecosystem", "project", "path", "scanner", "runnable here"],
            tablefmt="github",
        )
    )
    orphans = unregistered_manifests(registry)
    print("\nUnregistered manifests: " + (", ".join(orphans) if orphans else "none"))
    # 2, the same "no verdict" code scan uses: a manifest nobody registered is a
    # service whose dependencies are unmeasured, which is the one thing this
    # registry exists to make impossible to land quietly.
    return 2 if orphans else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="scan and grade against the baseline")
    scan_parser.add_argument(
        "--ecosystem", default="all", choices=["all", *SCANNERS], help="limit to one ecosystem"
    )
    scan_parser.add_argument("--project", help="limit to one registered project id")
    scan_parser.add_argument(
        "--allow-unmeasured",
        action="store_true",
        help="report unmeasured projects without withholding the verdict",
    )
    scan_parser.set_defaults(func=scan)

    baseline_parser = sub.add_parser("baseline", help="record the last full scan as accepted")
    baseline_parser.add_argument("--reason", required=True, help="why these findings are accepted")
    baseline_parser.add_argument(
        "--allow-unmeasured",
        action="store_true",
        help="record the measured projects even though others have no verdict",
    )
    baseline_parser.set_defaults(func=baseline)

    list_parser = sub.add_parser("list", help="show the registry and scanner availability")
    list_parser.set_defaults(func=list_registry)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
