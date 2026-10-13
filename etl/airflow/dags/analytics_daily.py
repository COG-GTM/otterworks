"""analytics_daily — replaces etl/scripts/analytics_daily.py (cron: 0 2 * * *).

extract (SQS, DynamoDB -> raw zone, partitioned by event date)
  -> transform (PySpark: local[*] via SparkSubmitOperator, or EMR when OTTERWORKS_SPARK_MODE=emr)
  -> load (curated Parquet, legacy-compatible data-lake partition, Postgres upsert, report)

Every output is keyed by ``ds``, so re-running or backfilling a date overwrites that date only.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.decorators import task

from otterworks_etl import settings
from otterworks_etl.common import DAG_KWARGS, default_args
from otterworks_etl.tasks import analytics as A

with DAG(
    dag_id="analytics_daily",
    description="Daily analytics aggregation (SQS + DynamoDB -> PySpark -> S3 + Postgres)",
    schedule="0 2 * * *",
    default_args=default_args(sla=timedelta(hours=1)),
    doc_md=__doc__,
    **DAG_KWARGS,
) as dag:

    @task
    def extract_from_sqs(ds=None):
        return A.extract_from_sqs(ds, settings.load_config())

    @task
    def extract_from_dynamodb(ds=None):
        return A.extract_from_dynamodb(ds, settings.load_config())

    @task
    def load_to_data_lake(location: str, ds=None):
        cfg = settings.load_config()
        return A.load_to_data_lake(ds, cfg, A.read_aggregates(location, cfg))

    @task
    def update_postgres_aggregates(location: str, ds=None):
        cfg = settings.load_config()
        A.update_postgres_aggregates(ds, cfg, A.read_aggregates(location, cfg))

    @task
    def generate_report(location: str, ds=None):
        cfg = settings.load_config()
        return A.generate_report(ds, cfg, A.read_aggregates(location, cfg),
                                 pendulum.now("UTC").isoformat())

    extracted = [extract_from_sqs(), extract_from_dynamodb()]

    if settings.spark_mode() == "emr":
        from airflow.providers.amazon.aws.operators.emr import EmrAddStepsOperator
        from airflow.providers.amazon.aws.sensors.emr import EmrStepSensor

        @task
        def resolve_emr_paths(ds=None):
            cfg = settings.load_config()
            if not cfg["emr_cluster_id"] or not cfg["spark_jobs_s3_prefix"]:
                raise ValueError("emr mode needs emr_cluster_id and spark_jobs_s3_prefix in the "
                                 "otterworks_etl Variable")
            bucket = cfg["data_lake_bucket"]
            return {"cluster_id": cfg["emr_cluster_id"],
                    "job": f"{cfg['spark_jobs_s3_prefix'].rstrip('/')}/analytics_daily_aggregate.py",
                    "input": f"s3://{bucket}/{A.raw_prefix(cfg, ds)}/",
                    "output": f"s3://{bucket}/{A.curated_prefix(cfg, ds)}",
                    "top_n": str(cfg["top_users_limit"])}

        paths = resolve_emr_paths()
        xp = "ti.xcom_pull(task_ids='resolve_emr_paths')"
        add_step = EmrAddStepsOperator(
            task_id="aggregate_with_spark",
            aws_conn_id=settings.AWS_CONN_ID,
            job_flow_id="{{ %s['cluster_id'] }}" % xp,
            steps=[{
                "Name": "otterworks-analytics-{{ ds }}",
                "ActionOnFailure": "CONTINUE",
                "HadoopJarStep": {"Jar": "command-runner.jar", "Args": [
                    "spark-submit", "--deploy-mode", "cluster",
                    "{{ %s['job'] }}" % xp, "--ds", "{{ ds }}",
                    "--input", "{{ %s['input'] }}" % xp, "--output", "{{ %s['output'] }}" % xp,
                    "--top-n", "{{ %s['top_n'] }}" % xp]},
            }],
        )
        wait_step = EmrStepSensor(
            task_id="wait_for_spark",
            aws_conn_id=settings.AWS_CONN_ID,
            job_flow_id="{{ %s['cluster_id'] }}" % xp,
            step_id="{{ ti.xcom_pull(task_ids='aggregate_with_spark')[0] }}",
            mode="reschedule",
            poke_interval=60,
        )

        @task
        def curated_location(p: dict):
            return p["output"]

        extracted >> paths >> add_step >> wait_step
        location = curated_location(paths)
        wait_step >> location
    else:
        from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator

        @task
        def stage_raw_local(ds=None):
            cfg = settings.load_config()
            return {**A.stage_raw_local(ds, cfg), "top_n": str(cfg["top_users_limit"])}

        @task
        def publish_curated(staged: dict, ds=None):
            return A.publish_curated_local(ds, settings.load_config(), staged["out_dir"])["location"]

        staged = stage_raw_local()
        xp = "ti.xcom_pull(task_ids='stage_raw_local')"
        spark = SparkSubmitOperator(
            task_id="aggregate_with_spark",
            conn_id=settings.SPARK_CONN_ID,
            application=os.path.join(settings.SPARK_JOBS_DIR, "analytics_daily_aggregate.py"),
            name="otterworks-analytics-{{ ds }}",
            application_args=["--ds", "{{ ds }}", "--input", "{{ %s['raw_dir'] }}" % xp,
                              "--output", "{{ %s['out_dir'] }}" % xp,
                              "--top-n", "{{ %s['top_n'] }}" % xp],
            conf={"spark.sql.session.timeZone": "UTC", "spark.ui.enabled": "false"},
            verbose=False,
        )
        extracted >> staged >> spark
        location = publish_curated(staged)
        spark >> location

    load_to_data_lake(location)
    update_postgres_aggregates(location)
    generate_report(location)
