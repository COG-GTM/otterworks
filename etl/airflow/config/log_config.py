"""Airflow logging config: the stock config with every formatter swapped for JSON.

Enabled with ``AIRFLOW__LOGGING__LOGGING_CONFIG_CLASS=log_config.LOGGING_CONFIG``
(this directory must be on PYTHONPATH; the docker-compose runner does that).
"""

from copy import deepcopy

from airflow.config_templates.airflow_local_settings import DEFAULT_LOGGING_CONFIG

LOGGING_CONFIG = deepcopy(DEFAULT_LOGGING_CONFIG)
for _name, _fmt in LOGGING_CONFIG["formatters"].items():
    LOGGING_CONFIG["formatters"][_name] = {"()": "otterworks_etl.json_logging.JsonFormatter"}
