"""Failure / SLA-miss alerting. Every channel is optional and a no-op when unconfigured.

* Slack: an HTTP connection ``otterworks_slack_webhook`` (host ``https://hooks.slack.com``,
  password = the webhook path ``/services/T000/B000/XXX``).
* Email: ``alert_emails`` in the ``otterworks_etl`` Variable plus Airflow SMTP settings.
"""

from __future__ import annotations

import json
import logging

from otterworks_etl import settings
from otterworks_etl.json_logging import log_event

logger = logging.getLogger(__name__)


def _slack_conn_configured() -> bool:
    from airflow.exceptions import AirflowNotFoundException
    from airflow.hooks.base import BaseHook

    try:
        BaseHook.get_connection(settings.SLACK_WEBHOOK_CONN_ID)
        return True
    except AirflowNotFoundException:
        return False


def _post_slack(text: str) -> bool:
    if not _slack_conn_configured():
        return False
    from airflow.providers.http.hooks.http import HttpHook

    hook = HttpHook(method="POST", http_conn_id=settings.SLACK_WEBHOOK_CONN_ID)
    endpoint = hook.get_connection(settings.SLACK_WEBHOOK_CONN_ID).password or ""
    hook.run(endpoint=endpoint, data=json.dumps({"text": text}),
             headers={"Content-Type": "application/json"})
    return True


def _send_email(subject: str, body: str) -> bool:
    try:
        recipients = settings.load_config().get("alert_emails") or []
    except Exception:  # noqa: BLE001 - metastore unavailable: treat as unconfigured
        recipients = []
    if not recipients:
        return False
    from airflow.utils.email import send_email

    send_email(to=recipients, subject=subject, html_content=f"<pre>{body}</pre>")
    return True


def notify(subject: str, body: str) -> list[str]:
    """Send to every configured channel; never raises. Returns the channels used."""
    sent = []
    for name, fn in (("slack", lambda: _post_slack(f"*{subject}*\n{body}")),
                     ("email", lambda: _send_email(subject, body))):
        try:
            if fn():
                sent.append(name)
        except Exception as exc:  # noqa: BLE001 - alerting must never fail the task
            log_event(logger, "alert_channel_failed", logging.WARNING, channel=name, error=str(exc))
    if not sent:
        log_event(logger, "alert_not_sent_no_channel_configured", logging.WARNING, subject=subject)
    return sent


def on_failure_callback(context) -> None:
    ti = context["task_instance"]
    exc = context.get("exception")
    subject = f"[otterworks-etl] FAILED {ti.dag_id}.{ti.task_id} ({context.get('ds')})"
    body = (f"dag={ti.dag_id} task={ti.task_id} run_id={ti.run_id} try={ti.try_number}\n"
            f"error={exc!r}\nlog={getattr(ti, 'log_url', '')}")
    log_event(logger, "task_failed", logging.ERROR, dag_id=ti.dag_id, task_id=ti.task_id,
              run_id=ti.run_id, error=repr(exc))
    notify(subject, body)


def on_retry_callback(context) -> None:
    ti = context["task_instance"]
    log_event(logger, "task_retry", logging.WARNING, dag_id=ti.dag_id, task_id=ti.task_id,
              run_id=ti.run_id, try_number=ti.try_number, error=repr(context.get("exception")))


def sla_miss_callback(dag, task_list, blocking_task_list, slas, blocking_tis) -> None:
    subject = f"[otterworks-etl] SLA missed on {dag.dag_id}"
    body = f"tasks={task_list}\nblocking={blocking_task_list}"
    log_event(logger, "sla_missed", logging.WARNING, dag_id=dag.dag_id, tasks=str(task_list))
    notify(subject, body)
