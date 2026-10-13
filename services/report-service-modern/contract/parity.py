#!/usr/bin/env python3
"""Replay contract/scenarios.json against report-service implementations and diff normalized responses.

  parity.py record  --base http://localhost:8091 --out golden.json
  parity.py compare --legacy http://localhost:8091 --modern http://localhost:8092 [--golden golden.json]

Normalization (mirrored by ContractParityTest.java): numeric ids -> "<id>", server-generated timestamps ->
"<ts>" only when they use the legacy wire format (yyyy-MM-dd'T'HH:mm:ss.SSS+00:00), positive fileSizeBytes ->
"<size>", Content-Length -> "<len>", generated file names / CSV "Generated:" banner / now-relative CSV instants -> masked, binary bodies ->
magic bytes + "<binary>". Request-supplied dateFrom/dateTo are compared verbatim unless a step sets maskDates.
"""
import argparse, json, re, sys, time, urllib.error, urllib.request
from pathlib import Path

TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$")
CSV_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
SERVER_TS_KEYS = {"timestamp", "createdAt", "completedAt"}
DATE_KEYS = {"dateFrom", "dateTo"}
TERMINAL = {"COMPLETED", "FAILED"}
SCENARIOS = Path(__file__).with_name("scenarios.json")


def mask_ts(value):
    if value is None:
        return None
    return "<ts>" if isinstance(value, str) and TS.match(value) else f"<ts-unexpected-format:{value}>"


def normalize_json(node, mask_dates):
    if isinstance(node, list):
        return [normalize_json(n, mask_dates) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key == "id" and isinstance(value, int):
            out[key] = "<id>"
        elif key == "downloadUrl" and isinstance(value, str):
            out[key] = re.sub(r"/\d+/", "/<id>/", value)
        elif key in SERVER_TS_KEYS or (mask_dates and key in DATE_KEYS):
            out[key] = mask_ts(value)
        elif key == "fileSizeBytes" and isinstance(value, int) and value > 0:
            out[key] = "<size>"
        elif key == "path" and isinstance(value, str):
            out[key] = re.sub(r"/\d+(?=/|$)", "/<id>", value)
        else:
            out[key] = normalize_json(value, mask_dates)
    return out


def normalize_body(content_type, raw, mask_dates):
    if not raw:
        return None
    ct = (content_type or "").split(";")[0].strip()
    if ct.endswith("json"):
        return normalize_json(json.loads(raw), mask_dates)
    if ct == "text/csv":
        text = raw.decode("utf-8")
        lines = [re.sub(r'^("?)# Generated: [^"]*', r"\1# Generated: <ts>", line) for line in text.splitlines()]
        return [CSV_INSTANT.sub("<instant>", line) for line in lines]
    return {"magic": raw[:4].hex(), "body": "<binary>"}


def call(base, step, ids):
    path = re.sub(r"\{(\w+)\}", lambda m: str(ids[m.group(1)]), step["path"])
    data, headers = None, {"Accept": "*/*"}
    if "json" in step:
        data, headers["Content-Type"] = json.dumps(step["json"]).encode(), "application/json"
    elif "raw" in step:
        data, headers["Content-Type"] = step["raw"].encode(), step["contentType"]
    req = urllib.request.Request(base + path, data=data, method=step["method"], headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers, err.read()


def run(base, scenarios=SCENARIOS):
    steps = json.loads(Path(scenarios).read_text())["steps"]
    ids, transcript = {}, []
    for step in steps:
        status, headers, raw = call(base, step, ids)
        deadline = time.time() + 60
        while step.get("awaitTerminal") and json.loads(raw).get("status") not in TERMINAL and time.time() < deadline:
            time.sleep(0.25)
            status, headers, raw = call(base, step, ids)
        if "capture" in step:
            ids[step["capture"]] = json.loads(raw)["id"]
        ct = headers.get("Content-Type")
        disposition = headers.get("Content-Disposition")
        transcript.append({
            "step": step["name"],
            "request": f'{step["method"]} {step["path"]}',
            "status": status,
            "contentType": ct,
            "contentDisposition": re.sub(r"_\d{8}_\d{6}\.", "_<ts>.", disposition) if disposition else None,
            "contentLength": "<len>" if headers.get("Content-Length") not in (None, "0") else headers.get("Content-Length"),
            "body": normalize_body(ct, raw, step.get("maskDates", False)),
        })
    return transcript


def diff(expected, actual, label_a, label_b):
    problems = []
    for exp, act in zip(expected, actual):
        for field in exp:
            if exp[field] != act.get(field):
                problems.append(f'{exp["step"]}.{field}:\n    {label_a}: {json.dumps(exp[field])[:400]}\n'
                                f'    {label_b}: {json.dumps(act.get(field))[:400]}')
    if len(expected) != len(actual):
        problems.append(f"step count differs: {len(expected)} vs {len(actual)}")
    return problems


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("--base", required=True)
    rec.add_argument("--out", required=True)
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("--legacy", required=True)
    cmp_.add_argument("--modern", required=True)
    cmp_.add_argument("--golden", help="also check both live transcripts against this recorded golden file")
    args = parser.parse_args()

    if args.cmd == "record":
        Path(args.out).write_text(json.dumps(run(args.base), indent=2) + "\n")
        print(f"recorded {args.out}")
        return 0

    legacy, modern = run(args.legacy), run(args.modern)
    problems = diff(legacy, modern, "legacy", "modern")
    if args.golden:
        golden = json.loads(Path(args.golden).read_text())
        problems += [f"[golden vs legacy] {p}" for p in diff(golden, legacy, "golden", "legacy")]
        problems += [f"[golden vs modern] {p}" for p in diff(golden, modern, "golden", "modern")]
    for exp, act in zip(legacy, modern):
        mark = "OK  " if exp == act else "DIFF"
        print(f"{mark} {exp['step']:<32} {exp['request']:<44} legacy={exp['status']} modern={act['status']}")
    if problems:
        print("\nPARITY FAILURES:\n" + "\n".join(problems))
        return 1
    print(f"\nPARITY OK: {len(legacy)} steps, legacy and modern responses identical after normalization")
    return 0


if __name__ == "__main__":
    sys.exit(main())
