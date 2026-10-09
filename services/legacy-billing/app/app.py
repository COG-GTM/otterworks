import hmac
import os
import uuid
from datetime import date
from decimal import Decimal
from urllib.parse import urlsplit

import psycopg
from flask import (
    Flask,
    abort,
    current_app,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

DEFAULT_ALLOWED_HOSTS = "localhost,127.0.0.1,legacy-billing"
REQUEST_HEADER = "X-Legacy-Billing-Request"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PUBLIC_ENDPOINTS = frozenset({"health"})


def allowed_hosts():
    raw = os.getenv("LEGACY_BILLING_ALLOWED_HOSTS", DEFAULT_ALLOWED_HOSTS).strip()
    if raw == "*":
        return None
    return [host.strip() for host in raw.split(",") if host.strip()]


def bearer_token():
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def same_origin(origin):
    parts = urlsplit(origin)
    return parts.scheme in ("http", "https") and parts.netloc.lower() == request.host.lower()


app = Flask(__name__)
app.config["TRUSTED_HOSTS"] = allowed_hosts()
app.config["API_TOKEN"] = os.getenv("LEGACY_BILLING_API_TOKEN", "")


@app.before_request
def enforce_request_guards():
    expected = current_app.config["API_TOKEN"]
    if (
        expected
        and request.endpoint not in PUBLIC_ENDPOINTS
        and not hmac.compare_digest(bearer_token().encode(), expected.encode())
    ):
        abort(401)
    if request.method in SAFE_METHODS:
        return
    if request.headers.get(REQUEST_HEADER) != "1":
        abort(403)
    origin = request.headers.get("Origin")
    if origin is not None and not same_origin(origin):
        abort(403)
    if request.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
        abort(403)


def db_connect():
    return psycopg.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "billing_dev"),
        user=os.getenv("DB_USER", "billing"),
        password=os.getenv("DB_PASSWORD", "billing"),
    )


def json_value(value):
    if isinstance(value, (Decimal, date)):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def rows(cursor):
    names = [column.name for column in cursor.description]
    return [{name: json_value(value) for name, value in zip(names, row)} for row in cursor]


def select(sql, params=()):
    with db_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            return rows(cursor)


def execute(sql, params=()):
    with db_connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)


@app.get("/health")
def health():
    select("SELECT 1")
    return jsonify(status="UP", service="legacy-billing")


@app.get("/")
def index():
    return render_template("index.html", plans=select("SELECT * FROM billing.fn_list_plans()"))


@app.get("/plans")
def plans():
    return jsonify(select("SELECT * FROM billing.fn_list_plans()"))


@app.get("/plans/<tenant_id>/entitlement")
def entitlement(tenant_id):
    return jsonify(select(
        "SELECT * FROM billing.fn_entitlement(%s, %s)",
        (tenant_id, request.args.get("on", "2026-02-28")),
    ))


@app.post("/plans/<tenant_id>/change")
def change_plan(tenant_id):
    execute(
        "CALL billing.sp_change_plan(%s, %s, %s)",
        (tenant_id, request.form["plan_id"], request.form["effective_on"]),
    )
    return redirect(url_for("entitlement", tenant_id=tenant_id, on=request.form["effective_on"]))


@app.post("/api/rating/preview")
def rating_preview():
    payload = request.get_json()
    return jsonify(select(
        "SELECT * FROM billing.fn_usage_rating(%s, %s, %s)",
        (payload["tenant_id"], payload["period_start"], payload["period_end"]),
    ))


@app.post("/api/rating/finalize")
def rating_finalize():
    payload = request.get_json()
    execute(
        "CALL billing.sp_finalize_rating(%s, %s, %s)",
        (payload["tenant_id"], payload["period_start"], payload["period_end"]),
    )
    return jsonify(status="finalized")


@app.get("/api/invoices/<tenant_id>/preview")
def invoice_preview(tenant_id):
    return jsonify(select(
        "SELECT * FROM billing.fn_invoice_preview(%s, %s, %s)",
        (
            tenant_id,
            request.args.get("period_start", "2026-02-01"),
            request.args.get("period_end", "2026-02-28"),
        ),
    ))


@app.post("/api/invoices/<tenant_id>/issue")
def invoice_issue(tenant_id):
    execute(
        "CALL billing.sp_issue_invoice(%s, %s, %s)",
        (
            tenant_id,
            request.form["period_start"],
            request.form["period_end"],
        ),
    )
    return jsonify(status="issued")


@app.get("/api/invoices/<invoice_id>/lines")
def invoice_lines(invoice_id):
    return jsonify(select("SELECT * FROM billing.fn_invoice_lines(%s)", (invoice_id,)))


@app.get("/api/dunning/overdue")
def overdue():
    return jsonify(select(
        "SELECT * FROM billing.fn_overdue_accounts(%s)",
        (request.args.get("as_of", "2026-02-28"),),
    ))


@app.post("/api/dunning/schedule")
def schedule_dunning():
    execute("CALL billing.sp_schedule_dunning(%s)", (request.form["as_of"],))
    return jsonify(status="scheduled")


@app.post("/api/dunning/suspend")
def suspend_overdue():
    execute("CALL billing.sp_suspend_overdue(%s)", (request.form["as_of"],))
    return jsonify(status="suspended")
