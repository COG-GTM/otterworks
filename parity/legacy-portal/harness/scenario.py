"""Scenario loading, request expansion and response normalisation.

Scenarios are plain YAML so reviewers can read the contract without reading
Python. Everything that is inherently non-deterministic between two runs of the
same build (wall-clock timestamps) is normalised; everything else -- status
codes, media types, field names, identity values, ordering, error envelopes and
number formatting -- must match byte-for-byte after JSON canonicalisation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROOT.parent.parent
SCENARIO_DIR = ROOT / "scenarios"
TRANSCRIPT_DIR = ROOT / "transcripts"

INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$")
INSTANT_TOKEN = "<instant>"
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

CONTEXT_ORDER = ("announcements", "user-preferences", "feedback", "platform")
BUSINESS_CONTEXTS = [c for c in CONTEXT_ORDER if c != "platform"]


@dataclass
class Step:
    name: str
    request: dict[str, Any]
    capture: dict[str, str] = field(default_factory=dict)
    ignore: list[str] = field(default_factory=list)


@dataclass
class Scenario:
    id: str
    steps: list[Step]


@dataclass
class ScenarioFile:
    context: str
    fanout: bool
    scenarios: list[Scenario]


def load_contexts() -> dict[str, Any]:
    with open(ROOT / "contexts.yaml", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_scenarios(context: str) -> ScenarioFile:
    with open(SCENARIO_DIR / f"{context}.yaml", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if raw["context"] != context:
        raise ValueError(f"{context}.yaml declares context {raw['context']!r}")
    scenarios = []
    for sc in raw["scenarios"]:
        steps = []
        for i, st in enumerate(sc["steps"]):
            req = st["request"]
            steps.append(
                Step(
                    name=st.get("name") or f"{req['method'].lower()}-{i}",
                    request=req,
                    capture=st.get("capture", {}),
                    ignore=st.get("ignore", []),
                )
            )
        scenarios.append(Scenario(id=sc["id"], steps=steps))
    return ScenarioFile(context=context, fanout=bool(raw.get("fanout")), scenarios=scenarios)


def expand(value: Any, variables: dict[str, Any]) -> Any:
    """Resolve {$repeat: s, times: n} generators and {var} placeholders."""
    if isinstance(value, dict):
        if "$repeat" in value:
            return str(value["$repeat"]) * int(value["times"])
        return {k: expand(v, variables) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, variables) for v in value]
    if isinstance(value, str):
        return PLACEHOLDER_RE.sub(lambda m: str(variables[m.group(1)]), value)
    return value


def json_path_get(doc: Any, path: str) -> Any:
    if not path.startswith("$"):
        raise ValueError(f"json path must start with $: {path}")
    cur = doc
    for part in [p for p in path[1:].split(".") if p]:
        if isinstance(cur, list):
            cur = cur[int(part)]
        else:
            cur = cur[part]
    return cur


def json_path_delete(doc: Any, path: str) -> None:
    parts = [p for p in path[1:].split(".") if p]
    cur = doc
    for part in parts[:-1]:
        cur = cur[int(part)] if isinstance(cur, list) else cur.get(part)
        if cur is None:
            return
    if isinstance(cur, dict):
        cur.pop(parts[-1], None)


def normalise_body(body: Any, ignore: list[str]) -> Any:
    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str) and INSTANT_RE.match(node):
            return INSTANT_TOKEN
        return node

    out = walk(body)
    for path in ignore:
        json_path_delete(out, path)
    return out


def media_type(content_type: str | None) -> str | None:
    if not content_type:
        return None
    return content_type.split(";", 1)[0].strip().lower()


def parse_body(raw: bytes, mtype: str | None) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if mtype and (mtype == "application/json" or mtype.endswith("+json")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"$unparseable": text}
    return {"$text": text}


def diff(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """Structural diff; key order is irrelevant, list order is significant."""
    if isinstance(expected, dict) and isinstance(actual, dict):
        out: list[str] = []
        for k in sorted(set(expected) | set(actual)):
            p = f"{path}.{k}"
            if k not in actual:
                out.append(f"{p}: missing (expected {json.dumps(expected[k])})")
            elif k not in expected:
                out.append(f"{p}: unexpected {json.dumps(actual[k])}")
            else:
                out.extend(diff(expected[k], actual[k], p))
        return out
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [f"{path}: length {len(actual)} != expected {len(expected)}"]
        out = []
        for i, (e, a) in enumerate(zip(expected, actual)):
            out.extend(diff(e, a, f"{path}.{i}"))
        return out
    # bool is an int subclass in Python; true must not equal 1 in a JSON contract.
    if type(expected) is not type(actual) or expected != actual:
        return [f"{path}: {json.dumps(actual)} != expected {json.dumps(expected)}"]
    return []
