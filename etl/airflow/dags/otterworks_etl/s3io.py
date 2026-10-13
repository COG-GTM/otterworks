"""Small S3Hook helpers for JSON / JSONL(.gz) objects."""

from __future__ import annotations

import gzip
import io
import json
from collections.abc import Iterable, Iterator
from decimal import Decimal
from typing import Any


def json_default(o: Any):
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


def dumps(obj: Any, **kw) -> str:
    return json.dumps(obj, default=json_default, **kw)


def jsonl_gz_bytes(rows: Iterable[dict]) -> bytes:
    buf = io.BytesIO()
    # mtime=0 makes the archive byte-identical for identical input (idempotent re-runs).
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
        for row in rows:
            gz.write(dumps(row).encode("utf-8"))
            gz.write(b"\n")
    return buf.getvalue()


def iter_jsonl(data: bytes) -> Iterator[dict]:
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    for line in data.decode("utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def put_bytes(hook, bucket: str, key: str, data: bytes, **extra_args) -> None:
    hook.get_conn().put_object(Bucket=bucket, Key=key, Body=data, **extra_args)


def put_json(hook, bucket: str, key: str, obj: Any, gz: bool = False) -> None:
    body = dumps(obj, indent=2).encode("utf-8")
    if gz:
        body = gzip.compress(body, mtime=0)
    put_bytes(hook, bucket, key, body)


def get_bytes(hook, bucket: str, key: str) -> bytes | None:
    if not hook.check_for_key(key, bucket_name=bucket):
        return None
    return hook.get_conn().get_object(Bucket=bucket, Key=key)["Body"].read()


def get_json(hook, bucket: str, key: str) -> Any | None:
    data = get_bytes(hook, bucket, key)
    if data is None:
        return None
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    return json.loads(data)


def parse_s3_uri(uri: str) -> tuple[str, str]:
    rest = uri.split("://", 1)[1]
    bucket, _, key = rest.partition("/")
    return bucket, key
