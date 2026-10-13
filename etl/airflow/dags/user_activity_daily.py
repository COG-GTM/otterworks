"""user_activity_daily — replaces etl/scripts/user_activity_daily.py (cron: 0 5 * * *).

Reads ``analytics_daily_summary`` (Postgres) and the per-day top-user partitions written by
analytics_daily, merges a rolling window, and writes the activity report for ``ds``. A backfill
of an older date never overwrites a newer ``latest`` pointer.

Cron only guaranteed ordering by a 3h gap; here ``wait_for_analytics`` waits for the same day's
analytics_daily load. If it never lands (e.g. analytics was paused) the sensor soft-fails after
its timeout and the report is still built, listing the day under ``missing_top_user_days``.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.decorators import task
from airflow.sensors.external_task import ExternalTaskSensor
from airflow.utils.trigger_rule import TriggerRule

from otterworks_etl import settings
from otterworks_etl.common import DAG_KWARGS, default_args
from otterworks_etl.tasks import user_activity as U

with DAG(
    dag_id="user_activity_daily",
    description="Rolling user activity report from analytics aggregates",
    schedule="0 5 * * *",
    default_args=default_args(sla=timedelta(minutes=30)),
    doc_md=__doc__,
    **DAG_KWARGS,
) as dag:

    wait_for_analytics = ExternalTaskSensor(
        task_id="wait_for_analytics",
        external_dag_id="analytics_daily",
        external_task_id="load_to_data_lake",
        execution_delta=timedelta(hours=3),
        mode="reschedule",
        poke_interval=300,
        timeout=int(timedelta(hours=2).total_seconds()),
        soft_fail=True,
    )

    @task(trigger_rule=TriggerRule.NONE_FAILED)
    def extract_daily_summaries(ds=None):
        return U.extract_daily_summaries(ds, settings.load_config())

    @task(trigger_rule=TriggerRule.NONE_FAILED)
    def extract_top_users(ds=None):
        return U.extract_top_users(ds, settings.load_config())

    @task
    def build_and_load_report(top: dict, ds=None):
        return U.build_and_load_report(ds, settings.load_config(), top["missing_days"],
                                       pendulum.now("UTC").isoformat())

    summaries = extract_daily_summaries()
    top = extract_top_users()
    report = build_and_load_report(top)
    wait_for_analytics >> [summaries, top]
    summaries >> report
