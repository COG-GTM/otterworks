"""Shared pytest setup for the Airflow DAG package and the PySpark jobs."""

import os
import sys
import tempfile
from pathlib import Path

ETL = Path(__file__).resolve().parent
_home = tempfile.mkdtemp(prefix="otterworks-airflow-test-")

os.environ.setdefault("AIRFLOW_HOME", _home)
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
os.environ.setdefault("AIRFLOW__CORE__DAGS_FOLDER", str(ETL / "airflow" / "dags"))
os.environ.setdefault("AIRFLOW__DATABASE__SQL_ALCHEMY_CONN", f"sqlite:///{_home}/airflow.db")
os.environ.setdefault("AIRFLOW__CORE__UNIT_TEST_MODE", "True")
# moto + provider hooks: fake credentials, never a real AWS account.
for k, v in {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
             "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": "us-east-1",
             "AIRFLOW_CONN_AWS_DEFAULT": "aws://?region_name=us-east-1"}.items():
    os.environ[k] = v
for k in ("AWS_PROFILE", "AWS_ENDPOINT_URL"):
    os.environ.pop(k, None)

for p in (ETL / "airflow" / "dags", ETL / "airflow" / "config", ETL / "spark" / "jobs"):
    sys.path.insert(0, str(p))
