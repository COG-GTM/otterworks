"""DAG integrity: every DAG imports, matches the legacy cron schedule, retries with backoff."""

import importlib
import os
from datetime import timedelta
from pathlib import Path

import pytest
from airflow.models import DagBag
from airflow.utils.dag_cycle_tester import check_cycle

DAGS_DIR = Path(__file__).resolve().parents[1] / "dags"
CRONTAB = Path(__file__).resolve().parents[2] / "crontab"

EXPECTED = {
    "analytics_daily": "0 2 * * *",
    "audit_archive_weekly": "0 3 * * 0",
    "search_reindex_weekly": "0 4 * * 0",
    "storage_cleanup_daily": "30 2 * * *",
    "user_activity_daily": "0 5 * * *",
}


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder=str(DAGS_DIR), include_examples=False)


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}


def test_one_dag_per_legacy_job(dagbag):
    assert set(dagbag.dag_ids) == set(EXPECTED)
    legacy = {p.stem for p in (CRONTAB.parent / "scripts").glob("*.py")}
    assert legacy == set(EXPECTED)


@pytest.mark.parametrize("dag_id,schedule", sorted(EXPECTED.items()))
def test_schedule_matches_legacy_crontab(dagbag, dag_id, schedule):
    dag = dagbag.dags[dag_id]
    assert dag.schedule_interval == schedule
    cron_lines = [line for line in CRONTAB.read_text().splitlines()
                  if f"{dag_id}.py" in line and not line.lstrip().startswith("#")]
    assert cron_lines, f"{dag_id} not found in legacy crontab"
    assert " ".join(cron_lines[0].split()[:5]) == schedule


@pytest.mark.parametrize("dag_id", sorted(EXPECTED))
def test_no_cycles_and_backfill_safety(dagbag, dag_id):
    dag = dagbag.dags[dag_id]
    check_cycle(dag)
    assert dag.catchup is False
    assert dag.max_active_runs == 1
    assert dag.timezone.name == "UTC"
    assert dag.sla_miss_callback is not None


@pytest.mark.parametrize("dag_id", sorted(EXPECTED))
def test_every_task_retries_with_backoff_sla_and_alerting(dagbag, dag_id):
    for t in dagbag.dags[dag_id].tasks:
        assert t.retries >= 3, t.task_id
        assert t.retry_exponential_backoff, t.task_id
        assert t.max_retry_delay == timedelta(minutes=30), t.task_id
        assert t.sla is not None, t.task_id
        assert t.on_failure_callback, t.task_id
        assert t.execution_timeout is not None, t.task_id


def test_extract_transform_load_are_separate_tasks(dagbag):
    ids = set(dagbag.dags["analytics_daily"].task_ids)
    assert {"extract_from_sqs", "extract_from_dynamodb", "aggregate_with_spark",
            "load_to_data_lake", "update_postgres_aggregates", "generate_report"} <= ids
    spark = dagbag.dags["analytics_daily"].get_task("aggregate_with_spark")
    assert type(spark).__name__ == "SparkSubmitOperator"
    assert Path(spark.application).name == "analytics_daily_aggregate.py"
    assert Path(spark.application).exists()


def test_emr_mode_swaps_in_emr_operators(monkeypatch):
    monkeypatch.setenv("OTTERWORKS_SPARK_MODE", "emr")
    bag = DagBag(dag_folder=str(DAGS_DIR / "analytics_daily.py"), include_examples=False)
    assert bag.import_errors == {}
    dag = bag.dags["analytics_daily"]
    assert type(dag.get_task("aggregate_with_spark")).__name__ == "EmrAddStepsOperator"
    assert type(dag.get_task("wait_for_spark")).__name__ == "EmrStepSensor"
    check_cycle(dag)


def test_no_plaintext_credentials_or_raw_clients_in_dags():
    for path in DAGS_DIR.rglob("*.py"):
        src = path.read_text()
        assert "import boto3" not in src and "import psycopg2" not in src, path
        assert "aws_secret_access_key" not in src and "AKIA" not in src, path
        assert "password=" not in src.replace("conn.password", ""), path


def test_settings_defaults_have_no_secrets():
    settings = importlib.import_module("otterworks_etl.settings")
    for key in settings.DEFAULTS:
        assert not any(s in key for s in ("password", "secret", "api_key", "access_key")), key
    assert os.path.basename(settings.SPARK_JOBS_DIR) == "jobs"


def test_user_activity_waits_for_same_day_analytics(dagbag):
    from datetime import timedelta

    dag = dagbag.dags["user_activity_daily"]
    sensor = dag.get_task("wait_for_analytics")
    assert sensor.external_dag_id == "analytics_daily"
    assert sensor.external_task_id in dagbag.dags["analytics_daily"].task_ids
    # 05:00 run looks at the 02:00 analytics run of the same day.
    assert sensor.execution_delta == timedelta(hours=3)
    assert sensor.soft_fail and sensor.mode == "reschedule"
    for tid in ("extract_daily_summaries", "extract_top_users"):
        assert dag.get_task(tid).trigger_rule == "none_failed"
