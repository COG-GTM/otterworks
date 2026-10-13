"""Connection ids and runtime configuration for the OtterWorks ETL DAGs.

Secrets live only in Airflow Connections. Non-secret settings (bucket names,
table names, tunables) live in the ``otterworks_etl`` JSON Variable; anything
missing from it falls back to ``DEFAULTS``. Config is resolved at task run time,
never at DAG parse time, so parsing never touches the metastore.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

AWS_CONN_ID = os.getenv("OTTERWORKS_AWS_CONN_ID", "aws_default")
POSTGRES_CONN_ID = os.getenv("OTTERWORKS_POSTGRES_CONN_ID", "otterworks_postgres")
MEILISEARCH_CONN_ID = "otterworks_meilisearch"
DOCUMENT_SERVICE_CONN_ID = "otterworks_document_service"
FILE_SERVICE_CONN_ID = "otterworks_file_service"
SLACK_WEBHOOK_CONN_ID = "otterworks_slack_webhook"
SPARK_CONN_ID = os.getenv("OTTERWORKS_SPARK_CONN_ID", "spark_default")
# Where spark-submit finds the job files (the compose runner mounts etl/spark here).
SPARK_JOBS_DIR = os.getenv("OTTERWORKS_SPARK_JOBS_DIR",
                           str(Path(__file__).resolve().parents[3] / "spark" / "jobs"))

CONFIG_VARIABLE = "otterworks_etl"

DEFAULTS: dict[str, Any] = {
    # S3
    "data_lake_bucket": "otterworks-data-lake",
    "file_storage_bucket": "otterworks-file-storage",
    "quarantine_bucket": "otterworks-file-quarantine",
    "archive_bucket": "otterworks-audit-archive",
    "analytics_prefix": "analytics/daily",
    "raw_prefix": "raw",
    "curated_prefix": "curated",
    "staging_prefix": "staging",
    # SQS / DynamoDB
    "analytics_queue_name": "otterworks-analytics",
    "analytics_events_table": "otterworks-analytics-events",
    "audit_events_table": "otterworks-audit-events",
    "file_metadata_table": "otterworks-file-metadata",
    # analytics
    "sqs_max_messages": 10000,
    "top_users_limit": 100,
    # audit archive
    "audit_retention_days": 90,
    "audit_archive_storage_class": "GLACIER",
    # storage cleanup
    "files_prefix": "files/",
    "quarantine_prefix": "quarantined",
    "storage_cleanup_dry_run": False,
    "storage_cleanup_grace_hours": 24,
    "storage_cleanup_max_orphan_pct": 50.0,
    # search reindex
    "search_documents_index": "documents",
    "search_files_index": "files",
    "search_api_page_size": 100,
    # user activity
    "user_activity_lookback_days": 30,
    "user_activity_reports_prefix": "reports/user-activity",
    # spark (local mode)
    "local_data_dir": os.getenv("OTTERWORKS_ETL_DATA_DIR", "/tmp/otterworks-etl"),
    "emr_cluster_id": "",
    "spark_jobs_s3_prefix": "",
    # alerting
    "alert_emails": [],
}


def load_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return DEFAULTS merged with the ``otterworks_etl`` Variable (and optional overrides)."""
    from airflow.models import Variable

    cfg = dict(DEFAULTS)
    cfg.update(Variable.get(CONFIG_VARIABLE, default_var={}, deserialize_json=True) or {})
    if overrides:
        cfg.update(overrides)
    return cfg


def spark_mode() -> str:
    """``local`` (SparkSubmitOperator, local[*]) or ``emr`` (EMR add-steps). Parse-time switch."""
    mode = os.getenv("OTTERWORKS_SPARK_MODE", "local").strip().lower()
    return mode if mode in {"local", "emr"} else "local"
