"""Transcript recording and normalisation for the legacy-portal parity suite.

A scenario is an ordered list of HTTP steps against one bounded context. Running it
produces a transcript: for every step the request as written in the scenario and the
response status, content type and normalised JSON body. Transcripts are compared as
whole structures against ``golden/<scenario>.json``.

Normalisation is deliberately narrow:

- every integer under an ``id`` key becomes ``<id#n>``, numbered by first appearance
  within the scenario, so identity relations (the id a POST returned is the id a later
  GET shows, newest-first order) survive while the database-generated values do not;
- ``createdAt`` / ``timestamp`` strings become ``<instant:Z>`` or ``<instant:+00:00>``
  after checking they are ISO-8601 in UTC, so the value is masked but the format is not;
- key order is ignored (the transcript is a dict); list order is kept unless a step
  declares the list as database-ordered (``unordered_by``).

Nothing else is rewritten: status codes, error strings, messages, booleans, floats and
the ``service`` literal on ``/health`` are compared exactly.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import httpx

ID_KEYS = frozenset({"id"})
TIMESTAMP_KEYS = frozenset({"createdAt", "timestamp"})
# /health's "service" is a per-deployable literal that every extracted service replaces.
SERVICE_NAME_KEYS = frozenset({"service"})

_INSTANT_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?Z$")
_INSTANT_OFFSET = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?\+00:00$"
)

CONTEXTS = ("announcements", "preferences", "feedback")


@dataclass(frozen=True)
class Step:
    """One HTTP exchange. ``path`` may reference captured ids as ``{name}``."""

    name: str
    method: str
    path: str
    json_body: Any = None
    raw_body: str | None = None
    content_type: str | None = None
    capture: Mapping[str, str] = field(default_factory=dict)
    unordered_by: str | None = None

    def request_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {"method": self.method, "path": self.path}
        if self.json_body is not None:
            record["json"] = self.json_body
        if self.raw_body is not None:
            record["raw"] = self.raw_body
        if self.content_type is not None:
            record["content_type"] = self.content_type
        return record


@dataclass(frozen=True)
class Scenario:
    name: str
    context: str
    description: str
    steps: tuple[Step, ...]


class IdMasker:
    """Maps generated ids to stable aliases in order of first appearance."""

    def __init__(self) -> None:
        self._aliases: dict[int, str] = {}

    def alias(self, value: int) -> str:
        if value not in self._aliases:
            self._aliases[value] = f"<id#{len(self._aliases) + 1}>"
        return self._aliases[value]


class TranscriptError(AssertionError):
    pass


def mask_timestamp(value: Any, where: str) -> str:
    if not isinstance(value, str):
        raise TranscriptError(f"{where}: expected an ISO-8601 string, got {value!r}")
    if _INSTANT_Z.match(value):
        return "<instant:Z>"
    if _INSTANT_OFFSET.match(value):
        return "<instant:+00:00>"
    raise TranscriptError(f"{where}: not an ISO-8601 UTC timestamp: {value!r}")


def normalise(value: Any, ids: IdMasker, where: str = "$") -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            path = f"{where}.{key}"
            if key in ID_KEYS and isinstance(item, int) and not isinstance(item, bool):
                out[key] = ids.alias(item)
            elif key in TIMESTAMP_KEYS:
                out[key] = mask_timestamp(item, path)
            elif key in SERVICE_NAME_KEYS and isinstance(item, str) and item:
                out[key] = "<service-name>"
            else:
                out[key] = normalise(item, ids, path)
        return out
    if isinstance(value, list):
        return [normalise(item, ids, f"{where}[{i}]") for i, item in enumerate(value)]
    return value


def _decode_body(response: httpx.Response) -> Any:
    if not response.content:
        return None
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return response.json()
    return {"non_json_text": response.text}


def run_scenario(
    scenario: Scenario, client_for: Callable[[str], httpx.Client]
) -> dict[str, Any]:
    client = client_for(scenario.context)
    ids = IdMasker()
    captured: dict[str, int] = {}
    steps: list[dict[str, Any]] = []
    for step in scenario.steps:
        try:
            url = step.path.format(**captured)
        except KeyError as exc:
            raise TranscriptError(
                f"{scenario.name}/{step.name}: path uses uncaptured id {exc}"
            ) from exc
        headers: dict[str, str] = {}
        content: bytes | None = None
        if step.json_body is not None:
            content = json.dumps(step.json_body).encode()
            headers["Content-Type"] = "application/json"
        if step.raw_body is not None:
            content = step.raw_body.encode()
        if step.content_type is not None:
            headers["Content-Type"] = step.content_type
        response = client.request(step.method, url, content=content, headers=headers)
        body = _decode_body(response)

        for var, key in step.capture.items():
            if not isinstance(body, dict) or not isinstance(body.get(key), int):
                raise TranscriptError(
                    f"{scenario.name}/{step.name}: cannot capture {var} from "
                    f"{key!r} in {response.status_code} {response.text[:200]}"
                )
            captured[var] = body[key]

        if step.unordered_by is not None and isinstance(body, list):
            body = sorted(body, key=lambda item: item[step.unordered_by])

        steps.append(
            {
                "name": step.name,
                "request": step.request_record(),
                "response": {
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    "body": normalise(body, ids),
                },
            }
        )
    return {
        "scenario": scenario.name,
        "context": scenario.context,
        "description": scenario.description,
        "steps": steps,
    }


def dump(transcript: Mapping[str, Any]) -> str:
    return json.dumps(transcript, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
