import os
import uuid
from datetime import date
from decimal import Decimal

import psycopg
from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from werkzeug.exceptions import HTTPException

from auth import ADMIN, READ, WRITE, authorize_tenant, enforce_declared_policy, parse_tenant, public, requires

app = Flask(__name__)
app.config["JWT_SECRET"] = os.getenv("LEGACY_BILLING_JWT_SECRET", "")
app.before_request(enforce_declared_policy)


@app.errorhandler(HTTPException)
def http_error(error):
    response = jsonify(error=error.name, detail=error.description)
    response.status_code = error.code
    if error.code == 401:
        response.headers["WWW-Authenticate"] = 'Bearer realm="legacy-billing"'
    return response


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


def json_payload():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        abort(400, description="expected a JSON object body")
    return payload


def path_tenant(kwargs):
    return kwargs["tenant_id"]


def payload_tenant(_kwargs):
    return json_payload().get("tenant_id")


@app.get("/health")
@public
def health():
    select("SELECT 1")
    return jsonify(status="UP", service="legacy-billing")


@app.get("/")
@requires(READ)
def index():
    return render_template("index.html", plans=select("SELECT * FROM billing.fn_list_plans()"))


@app.get("/plans")
@requires(READ)
def plans():
    return jsonify(select("SELECT * FROM billing.fn_list_plans()"))


@app.get("/plans/<tenant_id>/entitlement")
@requires(READ, tenant=path_tenant)
def entitlement(tenant_id):
    return jsonify(select(
        "SELECT * FROM billing.fn_entitlement(%s, %s)",
        (tenant_id, request.args.get("on", "2026-02-28")),
    ))


@app.post("/plans/<tenant_id>/change")
@requires(WRITE, tenant=path_tenant)
def change_plan(tenant_id):
    execute(
        "CALL billing.sp_change_plan(%s, %s, %s)",
        (tenant_id, request.form["plan_id"], request.form["effective_on"]),
    )
    return redirect(url_for("entitlement", tenant_id=tenant_id, on=request.form["effective_on"]))


@app.post("/api/rating/preview")
@requires(READ, tenant=payload_tenant)
def rating_preview():
    payload = json_payload()
    return jsonify(select(
        "SELECT * FROM billing.fn_usage_rating(%s, %s, %s)",
        (payload["tenant_id"], payload["period_start"], payload["period_end"]),
    ))


@app.post("/api/rating/finalize")
@requires(ADMIN, tenant=payload_tenant)
def rating_finalize():
    payload = json_payload()
    execute(
        "CALL billing.sp_finalize_rating(%s, %s, %s)",
        (payload["tenant_id"], payload["period_start"], payload["period_end"]),
    )
    return jsonify(status="finalized")


@app.get("/api/invoices/<tenant_id>/preview")
@requires(READ, tenant=path_tenant)
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
@requires(ADMIN, tenant=path_tenant)
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
@requires(READ)
def invoice_lines(invoice_id):
    if parse_tenant(invoice_id) is None:
        abort(404)
    owner = select("SELECT tenant_id FROM billing.invoices WHERE id = %s", (invoice_id,))
    if not owner:
        abort(404)
    try:
        authorize_tenant(owner[0]["tenant_id"])
    except HTTPException:
        abort(404)
    return jsonify(select("SELECT * FROM billing.fn_invoice_lines(%s)", (invoice_id,)))


@app.get("/api/dunning/overdue")
@requires(ADMIN)
def overdue():
    return jsonify(select(
        "SELECT * FROM billing.fn_overdue_accounts(%s)",
        (request.args.get("as_of", "2026-02-28"),),
    ))


@app.post("/api/dunning/schedule")
@requires(ADMIN)
def schedule_dunning():
    execute("CALL billing.sp_schedule_dunning(%s)", (request.form["as_of"],))
    return jsonify(status="scheduled")


@app.post("/api/dunning/suspend")
@requires(ADMIN)
def suspend_overdue():
    execute("CALL billing.sp_suspend_overdue(%s)", (request.form["as_of"],))
    return jsonify(status="suspended")
