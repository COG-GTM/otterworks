"""search_reindex_weekly — replaces etl/scripts/search_reindex_weekly.py (cron: 0 4 * * 0).

Per index: rebuild ``<index>_staging`` from the owning service's paged API, validate the
document count, then atomically swap it with the live index (blue/green; search stays up and a
failed run never touches the live index).
"""

from __future__ import annotations

from datetime import timedelta

from airflow import DAG
from airflow.decorators import task, task_group

from otterworks_etl import settings
from otterworks_etl.common import DAG_KWARGS, default_args
from otterworks_etl.tasks import search as S

with DAG(
    dag_id="search_reindex_weekly",
    description="Blue/green MeiliSearch reindex of documents and files",
    schedule="0 4 * * 0",
    default_args=default_args(sla=timedelta(hours=1)),
    doc_md=__doc__,
    **DAG_KWARGS,
) as dag:

    for kind in ("documents", "files"):

        @task_group(group_id=f"reindex_{kind}")
        def reindex(kind: str = kind):
            @task
            def prepare_staging_index():
                return S.prepare_staging_index(kind, settings.load_config())

            @task
            def extract_transform_load():
                return S.index_source(kind, settings.load_config())

            @task
            def validate_staging(expected: int):
                return S.validate_staging(kind, settings.load_config(), expected)

            @task
            def swap_into_live(prepared: dict):
                return S.swap_into_live(kind, settings.load_config(), prepared["prepared_at"])

            @task
            def drop_previous_index():
                return S.drop_previous_index(kind, settings.load_config())

            prepared = prepare_staging_index()
            indexed = extract_transform_load()
            prepared >> indexed
            validate_staging(indexed) >> swap_into_live(prepared) >> drop_previous_index()

        reindex()
