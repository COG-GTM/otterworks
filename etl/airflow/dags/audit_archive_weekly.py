"""audit_archive_weekly — replaces etl/scripts/audit_archive_weekly.py (cron: 0 3 * * 0).

Events older than the retention window (as of the run's data_interval_end, so backfills are
deterministic) are snapshotted, written to one content-addressed Glacier object per run,
verified to exist, and only then deleted from DynamoDB.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.decorators import task

from otterworks_etl import settings
from otterworks_etl.common import DAG_KWARGS, default_args
from otterworks_etl.tasks import audit as A

with DAG(
    dag_id="audit_archive_weekly",
    description="Archive audit events past retention from DynamoDB to S3 Glacier",
    schedule="0 3 * * 0",
    default_args=default_args(sla=timedelta(hours=2)),
    doc_md=__doc__,
    **DAG_KWARGS,
) as dag:

    @task
    def scan_audit_events(ds=None, data_interval_end=None):
        return A.scan_audit_events(ds, data_interval_end.isoformat(), settings.load_config())

    @task
    def compress_and_upload(scan: dict, ds=None):
        return A.compress_and_upload(ds, settings.load_config(), scan["key_attrs"])

    @task
    def cleanup_dynamodb(scan: dict, archive: dict, ds=None):
        return A.cleanup_dynamodb(ds, settings.load_config(), scan["key_attrs"],
                                  archive.get("archive_key"))

    @task
    def generate_compliance_report(scan: dict, archive: dict, deleted: int, ds=None):
        run = {"events_scanned": scan["events_scanned"], "cutoff": scan["cutoff"],
               "events_archived": archive["events_archived"], "events_deleted": deleted,
               "archive_location": archive["archive_location"],
               "compressed_size_bytes": archive["compressed_size_bytes"]}
        return A.generate_compliance_report(ds, settings.load_config(), run,
                                            pendulum.now("UTC").isoformat())

    scan = scan_audit_events()
    archive = compress_and_upload(scan)
    deleted = cleanup_dynamodb(scan, archive)
    generate_compliance_report(scan, archive, deleted)
