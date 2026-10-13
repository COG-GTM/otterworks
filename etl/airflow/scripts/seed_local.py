"""Provision + seed LocalStack for the ETL DAGs (local development only).

Creates the queue / tables / buckets the DAGs expect (localstack-init.sh only creates some of
them) and seeds demo data for one ``--ds``. Refuses to talk to anything but a local endpoint.

    python etl/airflow/scripts/seed_local.py --ds 2026-10-12   # from the host, needs boto3
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

import boto3

LOCAL_HOSTS = {"localhost", "127.0.0.1", "otterworks-localstack", "localstack"}
BUCKETS = ["otterworks-data-lake", "otterworks-file-storage", "otterworks-file-quarantine",
           "otterworks-audit-archive"]
TABLES = {
    "otterworks-analytics-events": [("event_id", "HASH")],
    # Same key schemas as scripts/localstack-init.sh (it usually creates these two first).
    "otterworks-audit-events": [("id", "HASH")],
    "otterworks-file-metadata": [("id", "HASH")],
}
EVENT_TYPES = ["document_created", "document_edited", "comment_added", "file_uploaded",
               "file_shared", "file_deleted"]


def clients(endpoint: str):
    host = urlparse(endpoint).hostname
    if host not in LOCAL_HOSTS:
        sys.exit(f"refusing to seed non-local endpoint {endpoint!r}")
    kw = {"endpoint_url": endpoint, "region_name": "us-east-1",
          "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID", "test"),
          "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY", "test")}
    return boto3.client("s3", **kw), boto3.client("sqs", **kw), boto3.resource("dynamodb", **kw)


def provision(s3, sqs, ddb) -> None:
    existing = {b["Name"] for b in s3.list_buckets()["Buckets"]}
    for b in BUCKETS:
        if b not in existing:
            s3.create_bucket(Bucket=b)
    sqs.create_queue(QueueName="otterworks-analytics")
    names = set(ddb.meta.client.list_tables()["TableNames"])
    for name, keys in TABLES.items():
        if name not in names:
            ddb.create_table(
                TableName=name, BillingMode="PAY_PER_REQUEST",
                KeySchema=[{"AttributeName": k, "KeyType": t} for k, t in keys],
                AttributeDefinitions=[{"AttributeName": k, "AttributeType": "S"} for k, _ in keys],
            ).wait_until_exists()


def event(rnd: random.Random, ds: str, i: int, prefix: str) -> dict:
    etype = rnd.choice(EVENT_TYPES)
    e = {"eventId": f"{prefix}-{ds}-{i}", "eventType": etype,
         "timestamp": f"{ds}T{rnd.randrange(24):02d}:{rnd.randrange(60):02d}:00Z",
         "ownerId": f"user-{rnd.randrange(25):03d}"}
    if etype.startswith("document") or etype == "comment_added":
        e["documentId"] = f"doc-{rnd.randrange(40):03d}"
    else:
        e["fileId"] = f"file-{rnd.randrange(40):03d}"
        e["sizeBytes"] = rnd.randrange(1_000, 5_000_000)
    return e


def seed(s3, sqs, ddb, ds: str, n_events: int) -> dict:
    rnd = random.Random(ds)
    url = sqs.get_queue_url(QueueName="otterworks-analytics")["QueueUrl"]
    sqs_events = [event(rnd, ds, i, "sqs") for i in range(n_events)]
    for start in range(0, len(sqs_events), 10):
        sqs.send_message_batch(QueueUrl=url, Entries=[
            {"Id": str(j), "MessageBody": json.dumps(e)}
            for j, e in enumerate(sqs_events[start:start + 10])])
    with ddb.Table("otterworks-analytics-events").batch_writer() as w:
        for i in range(n_events // 2):
            e = event(rnd, ds, i, "ddb")
            w.put_item(Item={"event_id": e["eventId"], "event_date": ds, **e})

    # storage_cleanup: 20 referenced files + 2 orphans (backdated via metadata is impossible in
    # S3, so run with storage_cleanup_grace_hours=0 to see them quarantined right away).
    with ddb.Table("otterworks-file-metadata").batch_writer() as w:
        for i in range(20):
            key = f"files/user-{i % 5:03d}/file-{i:03d}.bin"
            s3.put_object(Bucket="otterworks-file-storage", Key=key, Body=os.urandom(256))
            w.put_item(Item={"id": f"file-{i:03d}", "s3_key": key})
    for i in range(2):
        s3.put_object(Bucket="otterworks-file-storage", Key=f"files/orphans/orphan-{i}.bin",
                      Body=os.urandom(128))

    # audit_archive: 15 events past 90-day retention + 5 recent.
    old = (date.fromisoformat(ds) - timedelta(days=120)).isoformat()
    with ddb.Table("otterworks-audit-events").batch_writer() as w:
        for i in range(20):
            ts = f"{old if i < 15 else ds}T12:{i:02d}:00Z"
            # Same item shape as audit-service's DynamoDbAuditRepository.
            w.put_item(Item={"id": f"audit-{i:03d}", "Id": f"audit-{i:03d}", "Timestamp": ts,
                             "Action": "document.view", "UserId": f"user-{i % 5:03d}",
                             "ResourceType": "document", "ResourceId": f"doc-{i:03d}"})
    return {"sqs_events": len(sqs_events), "dynamodb_events": n_events // 2,
            "files": 22, "audit_events": 20}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--ds", default=(datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat())
    p.add_argument("--events", type=int, default=200)
    p.add_argument("--endpoint", default=os.getenv("LOCALSTACK_ENDPOINT", "http://localhost:4566"))
    args = p.parse_args()
    s3, sqs, ddb = clients(args.endpoint)
    provision(s3, sqs, ddb)
    print(json.dumps({"seeded": args.ds, **seed(s3, sqs, ddb, args.ds, args.events)}))


if __name__ == "__main__":
    main()
