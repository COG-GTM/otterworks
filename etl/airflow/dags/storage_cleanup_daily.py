"""storage_cleanup_daily — replaces etl/scripts/storage_cleanup_daily.py (cron: 30 2 * * *).

Objects under the file-storage prefix that no file-metadata row references, and that are older
than the grace period, are moved to the quarantine bucket under ``<prefix>/<ds>/``. A guard
fails the run (before anything moves) if the orphan ratio is implausibly high, and
``storage_cleanup_dry_run`` makes the run report-only.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.decorators import task

from otterworks_etl import settings
from otterworks_etl.common import DAG_KWARGS, default_args
from otterworks_etl.tasks import storage as S

with DAG(
    dag_id="storage_cleanup_daily",
    description="Quarantine orphaned S3 objects not referenced by file metadata",
    schedule="30 2 * * *",
    default_args=default_args(sla=timedelta(hours=1)),
    doc_md=__doc__,
    **DAG_KWARGS,
) as dag:

    @task
    def list_s3_objects(ds=None):
        return S.list_s3_objects(ds, settings.load_config())

    @task
    def list_metadata_references(ds=None):
        return S.list_metadata_references(ds, settings.load_config())

    @task
    def find_orphaned_objects(ds=None, data_interval_end=None):
        return S.find_orphaned_objects(ds, settings.load_config(), data_interval_end)

    @task
    def move_to_quarantine(ds=None):
        return S.move_to_quarantine(ds, settings.load_config())

    @task
    def generate_storage_report(inventory: dict, moved: dict, ds=None):
        return S.generate_storage_report(ds, settings.load_config(), inventory, moved,
                                         pendulum.now("UTC").isoformat())

    inventory = list_s3_objects()
    refs = list_metadata_references()
    orphans = find_orphaned_objects()
    [inventory, refs] >> orphans
    moved = move_to_quarantine()
    orphans >> moved
    generate_storage_report(inventory, moved)
