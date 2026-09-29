"""Boots the monolith and/or extracted services as local JVM processes.

By default every boot gets a fresh in-memory H2 database, which is what makes
identity values and ordering in the transcripts reproducible. The postgres stage
passes Spring datasource overrides through ``extra_args`` instead (see pg.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import client
from .scenario import REPO_ROOT, ROOT

LOG_DIR = ROOT / "reports" / "logs"

JDK_CANDIDATES = {
    "11": ["JAVA_HOME_11", "/usr/lib/jvm/java-11-openjdk-amd64", "/usr/lib/jvm/temurin-11-jdk-amd64"],
    "17": ["JAVA_HOME_17", "/usr/lib/jvm/java-17-openjdk-amd64", "/usr/lib/jvm/temurin-17-jdk-amd64"],
}


def java_binary(version: str) -> str:
    for cand in JDK_CANDIDATES.get(version, []):
        home = os.environ.get(cand, "") if cand.startswith("JAVA_HOME") else cand
        if home and Path(home, "bin", "java").exists():
            return str(Path(home, "bin", "java"))
    found = shutil.which("java")
    if not found:
        raise RuntimeError(f"no java runtime for Java {version}; set JAVA_HOME_{version}")
    return found


@dataclass
class Process:
    name: str
    base_url: str
    proc: subprocess.Popen
    log: Path


def start(name: str, jar: str, java: str, port: int, extra_args: list[str] | None = None) -> Process:
    jar_path = REPO_ROOT / jar
    if not jar_path.exists():
        raise FileNotFoundError(f"{jar_path} missing -- build it first (see parity/legacy-portal/README.md)")
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log = LOG_DIR / f"{name}.log"
    cmd = [java_binary(java), "-Xmx256m", "-jar", str(jar_path), f"--server.port={port}", *(extra_args or [])]
    fh = open(log, "wb")
    proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=REPO_ROOT)
    return Process(name, f"http://127.0.0.1:{port}", proc, log)


def stop(p: Process) -> None:
    if p.proc.poll() is None:
        p.proc.terminate()
        try:
            p.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            p.proc.kill()


@contextmanager
def running(
    specs: list[tuple[str, str, str, int]], extra_args: dict[str, list[str]] | None = None
) -> Iterator[dict[str, Process]]:
    procs: dict[str, Process] = {}
    try:
        for name, jar, java, port in specs:
            procs[name] = start(name, jar, java, port, (extra_args or {}).get(name))
        for p in procs.values():
            try:
                client.wait_healthy(p.base_url)
            except TimeoutError:
                tail = p.log.read_text(errors="replace")[-4000:]
                raise RuntimeError(f"{p.name} failed to become ready; log tail:\n{tail}") from None
        yield procs
    finally:
        for p in procs.values():
            stop(p)
