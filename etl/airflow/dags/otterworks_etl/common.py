"""Defaults shared by every OtterWorks DAG."""

from __future__ import annotations

from datetime import timedelta

import pendulum

from otterworks_etl.alerting import on_failure_callback, on_retry_callback, sla_miss_callback

START_DATE = pendulum.datetime(2026, 1, 1, tz="UTC")

DEFAULT_ARGS = {
    "owner": "data-platform",
    "depends_on_past": False,
    "retries": 3,
    "retry_delay": timedelta(minutes=1),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=30),
    "execution_timeout": timedelta(hours=2),
    "on_failure_callback": on_failure_callback,
    "on_retry_callback": on_retry_callback,
    # Email alerts go through alerting.notify (no-op when unconfigured), not Airflow's
    # built-in email_on_failure, so an unconfigured SMTP server never errors a task.
    "email_on_failure": False,
    "email_on_retry": False,
}

DAG_KWARGS = {
    "start_date": START_DATE,
    "catchup": False,
    "max_active_runs": 1,
    "sla_miss_callback": sla_miss_callback,
    "tags": ["otterworks", "etl"],
    "render_template_as_native_obj": False,
}


def default_args(sla: timedelta, **overrides) -> dict:
    args = dict(DEFAULT_ARGS, sla=sla)
    args.update(overrides)
    return args
