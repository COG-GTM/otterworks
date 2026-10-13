"""JSON logging + alerting callbacks (no-op when unconfigured, never fail the task)."""

import json
import logging
from types import SimpleNamespace

import pytest

from otterworks_etl import alerting
from otterworks_etl.json_logging import JsonFormatter, log_event


def test_json_formatter_emits_structured_fields():
    rec = logging.LogRecord("otterworks", logging.INFO, __file__, 1, "rows %s", (3,), None)
    rec.event, rec.rows, rec.dag_id = "loaded", 3, "analytics_daily"
    out = json.loads(JsonFormatter().format(rec))
    assert out["message"] == "rows 3" and out["level"] == "INFO"
    assert out["event"] == "loaded" and out["rows"] == 3 and out["dag_id"] == "analytics_daily"


def test_log_event_outside_task_context(caplog):
    with caplog.at_level(logging.INFO):
        log_event(logging.getLogger("t"), "hello", count=2)
    assert caplog.records[-1].count == 2 and caplog.records[-1].event == "hello"


def _ctx():
    ti = SimpleNamespace(dag_id="d", task_id="t", run_id="r", try_number=2, log_url="http://x")
    return {"task_instance": ti, "ti": ti, "ds": "2026-03-01", "exception": ValueError("boom")}


def test_unconfigured_alerting_is_noop(airflow_db, monkeypatch, caplog):
    monkeypatch.delenv("AIRFLOW_CONN_OTTERWORKS_SLACK_WEBHOOK", raising=False)
    with caplog.at_level(logging.WARNING):
        alerting.on_failure_callback(_ctx())
    assert alerting.notify("s", "b") == []
    assert any(r.message == "alert_not_sent_no_channel_configured" for r in caplog.records)


def test_slack_alert_when_configured(airflow_db, monkeypatch):
    monkeypatch.setenv("AIRFLOW_CONN_OTTERWORKS_SLACK_WEBHOOK",
                       "https://:%2Fservices%2FT0%2FB0%2FXYZ@hooks.slack.com")
    sent = []
    monkeypatch.setattr("airflow.providers.http.hooks.http.HttpHook.run",
                        lambda self, endpoint, data=None, headers=None, **kw: sent.append(
                            (endpoint, json.loads(data))))
    assert alerting.notify("subj", "body") == ["slack"]
    assert sent[0][0] == "/services/T0/B0/XYZ" and "subj" in sent[0][1]["text"]


def test_email_alert_when_configured(monkeypatch):
    monkeypatch.setattr(alerting, "_slack_conn_configured", lambda: False)
    monkeypatch.setattr(alerting.settings, "load_config", lambda: {"alert_emails": ["a@x.io"]})
    sent = []
    monkeypatch.setattr("airflow.utils.email.send_email",
                        lambda to, subject, html_content: sent.append((to, subject)))
    assert alerting.notify("subj", "body") == ["email"]
    assert sent == [(["a@x.io"], "subj")]


def test_broken_channel_never_raises(monkeypatch):
    monkeypatch.setattr(alerting, "_post_slack", lambda text: (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(alerting, "_send_email", lambda s, b: False)
    assert alerting.notify("s", "b") == []


@pytest.mark.parametrize("cb", [alerting.on_retry_callback])
def test_retry_callback_logs(cb, caplog):
    with caplog.at_level(logging.WARNING):
        cb(_ctx())
    assert caplog.records[-1].try_number == 2
