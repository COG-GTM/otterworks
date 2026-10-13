import pytest

from otterworks_etl import settings


@pytest.fixture(scope="session")
def airflow_db():
    """Initialise the throwaway sqlite metastore (only for tests that need Variables/Connections)."""
    from airflow.utils import db

    db.resetdb()
    yield


@pytest.fixture
def cfg(tmp_path):
    return dict(settings.DEFAULTS, local_data_dir=str(tmp_path / "data"), sqs_wait_seconds=0)


from spark_fixture import spark  # noqa: E402,F401
