#!/usr/bin/env python3
"""Guard against JDK builds affected by Java4Shell (CVE-2026-114938).

The java.util.Base64 decoder in these OpenJDK builds can corrupt memory on
malformed input. Fixed builds, per the public advisory:

    17.0.6 .. 17.0.21  -> 17.0.21.1
    21 < 21.0.13.1     -> 21.0.13.1
    25 < 25.0.5.1      -> 25.0.5.1
    27 < 27.0.1.1      -> 27.0.1.1
    8, 11              -> not affected

Subcommands:
    runtime [JAVA]    check a java binary (default: $JAVA_HOME/bin/java, then PATH)
    image IMAGE...    check the java inside container images (docker run)
    static [ROOT]     check Dockerfile FROM lines and setup-java pins for floating
                      or affected JDK versions
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

CVE = "CVE-2026-114938"
FIXED = {17: (17, 0, 21, 1), 21: (21, 0, 13, 1), 25: (25, 0, 5, 1), 27: (27, 0, 1, 1)}
FIRST_AFFECTED = {17: (17, 0, 6)}
UNAFFECTED_MAJORS = {8, 11}

JDK_IMAGE = re.compile(
    r"(eclipse-temurin|amazoncorretto|openjdk|gradle|maven|sbtscala/scala-sbt)", re.I
)


def parse_version(text: str) -> tuple[int, ...]:
    """'17.0.21.1' / '17.0.21.1+2' / '1.8.0_412' / '21' -> numeric tuple."""
    text = text.strip().strip("'\"")
    if text.startswith("1."):
        text = text[2:]
    text = re.split(r"[+_\-\s]", text, maxsplit=1)[0]
    return tuple(int(p) for p in text.split(".") if p.isdigit())


def pad(v: tuple[int, ...], n: int = 4) -> tuple[int, ...]:
    return tuple(v) + (0,) * (n - len(v))


def verdict(version: tuple[int, ...]) -> str | None:
    """None if the build is safe, else the reason it is not."""
    if not version:
        return "could not determine JDK version"
    major = version[0]
    if major in UNAFFECTED_MAJORS:
        return None
    if major in FIRST_AFFECTED and pad(version) < pad(FIRST_AFFECTED[major]):
        return None
    fixed = FIXED.get(major)
    if fixed is None:
        return f"JDK {major} has no fixed build for {CVE}; use 17, 21, 25 or 27"
    if pad(version) < pad(fixed):
        want = ".".join(map(str, fixed))
        return f"JDK {'.'.join(map(str, version))} is affected by {CVE}; need >= {want}"
    return None


def java_version(cmd: list[str]) -> str:
    out = subprocess.run(
        cmd + ["-XshowSettings:properties", "-version"],
        capture_output=True,
        text=True,
        check=True,
    )
    m = re.search(r"^\s*java\.version = (\S+)", out.stderr + out.stdout, re.M)
    if not m:
        raise RuntimeError(f"no java.version in output of {' '.join(cmd)}")
    return m.group(1)


def report(label: str, version_text: str) -> bool:
    reason = verdict(parse_version(version_text))
    if reason:
        print(f"FAIL {label}: {reason}")
        return False
    print(f"ok   {label}: {version_text}")
    return True


def cmd_runtime(args: list[str]) -> bool:
    java = args[0] if args else None
    if not java and os.environ.get("JAVA_HOME"):
        java = str(Path(os.environ["JAVA_HOME"]) / "bin" / "java")
    java = java or shutil.which("java")
    if not java:
        print("FAIL no java found")
        return False
    return report(java, java_version([java]))


def cmd_image(images: list[str]) -> bool:
    ok = True
    for image in images:
        cmd = ["docker", "run", "--rm", "--entrypoint", "java", image]
        ok &= report(image, java_version(cmd))
    return ok


def check_from(ref: str) -> str | None:
    """Reason a Dockerfile base image is unsafe, or None."""
    name, _, tag = ref.partition(":")
    if not JDK_IMAGE.search(name):
        return None
    # Exact JDK build embedded in the tag, e.g. 17.0.21.1_2-jre-jammy or
    # eclipse-temurin-jammy-17.0.10_7_1.9.9_3.4.1.
    exact = re.search(r"(?<![\d.])(\d{1,2}\.\d+\.\d+(?:\.\d+)?)[_+]", tag)
    if exact:
        return verdict(parse_version(exact.group(1)))
    major = re.search(r"(?:jdk|jre|temurin-|corretto-|^)(\d{1,2})(?![\d.])", tag)
    if not major:
        return f"cannot tell the JDK build of {ref}; pin an exact fixed version"
    if int(major.group(1)) in UNAFFECTED_MAJORS:
        return None
    return f"{ref} floats on JDK {major.group(1)}; pin an exact fixed build"


def check_setup_java(value: str) -> str | None:
    """Reason a setup-java `java-version` entry is unsafe, or None.

    Temurin's semver for a 4-part build such as 17.0.21.1+2 is 17.0.21+100000002
    (patch * 100000000 + build), so an exact pin carries the build metadata.
    """
    value = value.strip().strip("'\"")
    if not value:
        return None
    if not re.fullmatch(r"\d+(\.\d+)*(\+\d+)?", value):
        return f"java-version '{value}' is not an exact version"
    base, _, build = value.partition("+")
    version = parse_version(base)
    if version and version[0] in UNAFFECTED_MAJORS:
        return None
    if len(version) < 3 or not build:
        return f"java-version '{value}' floats; pin an exact fixed build (X.Y.Z+N)"
    patch = int(build) // 100000000
    return verdict(version + ((patch,) if patch else ()))


def cmd_static(args: list[str]) -> bool:
    root = Path(args[0] if args else ".").resolve()
    skip = {"node_modules", ".git", "vendor", "target", "build"}
    problems: list[str] = []

    for path in sorted(root.rglob("Dockerfile*")):
        if skip & set(path.relative_to(root).parts):
            continue
        for n, line in enumerate(path.read_text().splitlines(), 1):
            m = re.match(r"\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line, re.I)
            if m and (reason := check_from(m.group(1))):
                problems.append(f"{path.relative_to(root)}:{n}: {reason}")

    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        lines = path.read_text().splitlines()
        for n, line in enumerate(lines, 1):
            m = re.match(r"(\s*)java-version:\s*(.*)$", line)
            if not m:
                continue
            values = [(n, m.group(2))]
            if m.group(2).strip() in ("|", ">"):
                values = []
                for k in range(n, len(lines)):
                    nxt = lines[k]
                    if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= len(m.group(1)):
                        break
                    values.append((k + 1, nxt.split("#")[0]))
            for ln, value in values:
                value = value.split("#")[0]
                if "${{" in value:
                    continue
                if reason := check_setup_java(value):
                    problems.append(f"{path.relative_to(root)}:{ln}: {reason}")

    for p in problems:
        print(f"FAIL {p}")
    if not problems:
        print(f"ok   no floating or {CVE}-affected JDK pins under {root}")
    return not problems


def main(argv: list[str]) -> int:
    commands = {"runtime": cmd_runtime, "image": cmd_image, "static": cmd_static}
    if not argv or argv[0] not in commands:
        print(__doc__)
        return 2
    return 0 if commands[argv[0]](argv[1:]) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
