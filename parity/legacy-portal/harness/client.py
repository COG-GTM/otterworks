"""Minimal HTTP client (stdlib only) that never raises on 4xx/5xx."""

from __future__ import annotations

import http.client
import json
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any


@dataclass
class Response:
    status: int
    content_type: str | None
    body: bytes
    elapsed_ms: float


def send(base_url: str, request: dict[str, Any], timeout: float = 15.0) -> Response:
    url = urllib.parse.urlsplit(base_url)
    conn_cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
    conn = conn_cls(url.hostname, url.port, timeout=timeout)
    headers = {"Accept": "application/json"}
    payload: bytes | None = None
    if "json" in request:
        payload = json.dumps(request["json"]).encode("utf-8")
        headers["Content-Type"] = "application/json"
    elif "raw" in request:
        payload = str(request["raw"]).encode("utf-8")
        headers["Content-Type"] = request.get("content_type", "text/plain")
    path = url.path.rstrip("/") + request["path"]
    started = time.perf_counter()
    try:
        conn.request(request["method"], path, body=payload, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        return Response(resp.status, resp.getheader("Content-Type"), body, (time.perf_counter() - started) * 1000)
    finally:
        conn.close()


def wait_healthy(base_url: str, timeout_s: float = 120.0, path: str = "/actuator/health/readiness") -> None:
    deadline = time.monotonic() + timeout_s
    last: str = "no response"
    while time.monotonic() < deadline:
        try:
            r = send(base_url, {"method": "GET", "path": path}, timeout=2.0)
            if r.status == 200:
                return
            last = f"HTTP {r.status}"
        except OSError as exc:
            last = str(exc)
        time.sleep(0.5)
    raise TimeoutError(f"{base_url}{path} not healthy after {timeout_s:.0f}s ({last})")
