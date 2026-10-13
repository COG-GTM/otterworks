from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import Settings, load_settings
from app.db import Database
from app.domain import calculation, etl, rates, splits
from app.domain.errors import CommissionError, DuplicateOpenRateError
from app.repository import PostgresCommissionRepository, PostgresWarehouseRepository
from app.security import (
    CALCULATE,
    MANAGE_RATES,
    MANAGE_SPLITS,
    RUN_ETL,
    VIEW,
    Principal,
    require,
)

PERIOD_PATTERN = r"^\d{4}-\d{2}$"


class RateUpsert(BaseModel):
    product_code: str = Field(min_length=1, max_length=16)
    agent_id: int | None = None
    rate_pct: Decimal | None
    effective_from: date


class RateEnd(BaseModel):
    product_code: str = Field(min_length=1, max_length=16)
    agent_id: int | None = None
    effective_to: date


class SplitItem(BaseModel):
    agent_id: int
    split_pct: Decimal | None


class SplitsRequest(BaseModel):
    splits: list[SplitItem] = Field(max_length=100)


class CalculationRequest(BaseModel):
    period_month: str = Field(max_length=7)


class EtlRequest(BaseModel):
    period_month: str | None = Field(default=None, pattern=PERIOD_PATTERN)


def _error(exc: CommissionError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "error": {
                "code": exc.code,
                "legacy_ora_code": exc.ora_code,
                "message": exc.message,
            }
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = getattr(app.state, "settings", None) or load_settings()
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    app.state.db.migrate()
    app.state.db.ensure_seeded()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    app = FastAPI(title="commission-service", version="0.1.0", lifespan=lifespan)
    if settings is not None:
        app.state.settings = settings

    @app.exception_handler(CommissionError)
    async def commission_error(_: Request, exc: CommissionError) -> JSONResponse:
        return _error(exc)

    @app.exception_handler(psycopg.errors.UniqueViolation)
    async def unique_violation(_: Request, exc: psycopg.errors.UniqueViolation) -> JSONResponse:
        return _error(DuplicateOpenRateError("unique constraint violated"))

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "commission-service"}

    app.include_router(router)
    return app


router = APIRouter(prefix="/api/v1/commission")


@contextmanager
def commission_repo(
    request: Request, principal: Principal
) -> Iterator[PostgresCommissionRepository]:
    db: Database = request.app.state.db
    with db.tenant_transaction(principal.tenant_id) as connection:
        yield PostgresCommissionRepository(connection, principal.tenant_id)


@contextmanager
def warehouse_repo(request: Request, principal: Principal) -> Iterator[PostgresWarehouseRepository]:
    db: Database = request.app.state.db
    with db.tenant_transaction(principal.tenant_id) as connection:
        yield PostgresWarehouseRepository(connection, principal.tenant_id)


def _rate_json(rate: rates.Rate) -> dict[str, Any]:
    return {
        "rate_id": rate.rate_id,
        "product_code": rate.product_code,
        "agent_id": rate.agent_id,
        "rate_pct": str(rate.rate_pct),
        "effective_from": rate.effective_from.isoformat(),
        "effective_to": rate.effective_to.isoformat() if rate.effective_to else None,
        "created_by": rate.created_by,
    }


def _ledger_json(row: Any) -> dict[str, Any]:
    return {
        "policy_id": row.policy_id,
        "agent_id": row.agent_id,
        "period_month": row.period_month,
        "rate_id": row.rate_id,
        "split_pct": str(row.split_pct),
        "base_premium": str(row.base_premium),
        "commission_amt": str(row.commission_amt),
    }


Viewer = Annotated[Principal, Depends(require(VIEW))]
RateAdmin = Annotated[Principal, Depends(require(MANAGE_RATES))]
SplitManager = Annotated[Principal, Depends(require(MANAGE_SPLITS))]
Calculator = Annotated[Principal, Depends(require(CALCULATE))]
EtlRunner = Annotated[Principal, Depends(require(RUN_ETL))]


@router.put("/rates")
def upsert_rate(body: RateUpsert, request: Request, principal: RateAdmin) -> dict[str, Any]:
    with commission_repo(request, principal) as repo:
        rate_id = rates.upsert_commission_rate(
            repo,
            body.product_code,
            body.agent_id,
            body.rate_pct,
            body.effective_from,
            principal.subject,
        )
    return {"rate_id": rate_id}


@router.post("/rates/end")
def end_rate(body: RateEnd, request: Request, principal: RateAdmin) -> dict[str, Any]:
    with commission_repo(request, principal) as repo:
        rates.end_commission_rate(
            repo, body.product_code, body.agent_id, body.effective_to, principal.subject
        )
    return {"status": "ended"}


@router.get("/rates")
def list_rates(
    request: Request, principal: Viewer, product_code: Annotated[str, Query(max_length=16)]
) -> list[dict[str, Any]]:
    with commission_repo(request, principal) as repo:
        found = repo.rates_for_product(product_code)
    return [_rate_json(rate) for rate in found]


@router.get("/rates/resolve")
def resolve_rate(
    request: Request,
    principal: Viewer,
    product_code: Annotated[str, Query(max_length=16)],
    as_of: date,
    agent_id: int | None = None,
) -> dict[str, Any]:
    with commission_repo(request, principal) as repo:
        rate = rates.resolve_rate(repo, product_code, agent_id, as_of)
    return _rate_json(rate)


@router.put("/policies/{policy_id}/splits")
def set_splits(
    policy_id: int, body: SplitsRequest, request: Request, principal: SplitManager
) -> dict[str, Any]:
    with commission_repo(request, principal) as repo:
        stored = splits.set_commission_splits(
            repo,
            policy_id,
            [(item.agent_id, item.split_pct) for item in body.splits],
            principal.subject,
        )
    return {
        "policy_id": policy_id,
        "splits": [{"agent_id": s.agent_id, "split_pct": str(s.split_pct)} for s in stored],
    }


@router.get("/policies/{policy_id}/splits")
def get_splits(policy_id: int, request: Request, principal: Viewer) -> dict[str, Any]:
    with commission_repo(request, principal) as repo:
        if repo.get_policy(policy_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="policy not found")
        found = repo.list_splits(policy_id)
    return {
        "policy_id": policy_id,
        "splits": [{"agent_id": s.agent_id, "split_pct": str(s.split_pct)} for s in found],
    }


@router.post("/policies/{policy_id}/calculations")
def calculate(
    policy_id: int, body: CalculationRequest, request: Request, principal: Calculator
) -> dict[str, Any]:
    with commission_repo(request, principal) as repo:
        rows = calculation.calculate_policy_commission(
            repo, policy_id, body.period_month, principal.subject
        )
    return {
        "policy_id": policy_id,
        "period_month": body.period_month,
        "rows": [_ledger_json(row) for row in rows],
    }


@router.get("/ledger")
def ledger(
    request: Request,
    principal: Viewer,
    policy_id: int | None = None,
    period_month: Annotated[str | None, Query(pattern=PERIOD_PATTERN)] = None,
) -> list[dict[str, Any]]:
    """Commission payable rows (the legacy COMMISSION_LEDGER): the payout statement."""
    with commission_repo(request, principal) as repo:
        rows = repo.list_ledger(policy_id, period_month)
    return [_ledger_json(row) for row in rows]


@router.get("/audit")
def audit(request: Request, principal: RateAdmin) -> list[dict[str, Any]]:
    with commission_repo(request, principal) as repo:
        rows = repo.list_audit()
    return [row | {"logged_at": row["logged_at"].isoformat()} for row in rows]


@router.post("/etl/loads")
def load_facts(body: EtlRequest, request: Request, principal: EtlRunner) -> dict[str, Any]:
    with warehouse_repo(request, principal) as repo:
        merged = etl.load_commission_facts(repo, body.period_month)
    return {"rows_merged": merged}


@router.get("/facts")
def facts(
    request: Request,
    principal: Viewer,
    period_month: Annotated[str | None, Query(pattern=PERIOD_PATTERN)] = None,
) -> list[dict[str, Any]]:
    with warehouse_repo(request, principal) as repo:
        found = repo.list_facts(period_month)
    return [
        {
            "policy_id": f.policy_id,
            "agent_id": f.agent_id,
            "product_code": f.product_code,
            "period_month": f.period_month,
            "split_pct": str(f.split_pct),
            "base_premium": str(f.base_premium),
            "commission_amt": str(f.commission_amt),
        }
        for f in found
    ]


@router.get("/summary")
def summary(
    request: Request,
    principal: Viewer,
    period_month: Annotated[str | None, Query(pattern=PERIOD_PATTERN)] = None,
) -> list[dict[str, Any]]:
    with warehouse_repo(request, principal) as repo:
        found = repo.summary(period_month)
    return [
        {
            "agent_code": row.agent_code,
            "full_name": row.full_name,
            "period_month": row.period_month,
            "line_of_business": row.line_of_business,
            "policy_rows": row.policy_rows,
            "total_commission": str(row.total_commission),
        }
        for row in found
    ]


@router.post("/internal/reset", include_in_schema=False)
def reset(request: Request, principal: RateAdmin) -> dict[str, str]:
    """Restore the caller's own tenant to its seed. Disabled unless explicitly enabled."""
    settings: Settings = request.app.state.settings
    if not settings.enable_reset:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="not found")
    db: Database = request.app.state.db
    try:
        db.reset_tenant(principal.tenant_id)
    except KeyError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no seed for tenant") from exc
    return {"status": "reset", "tenant_id": principal.tenant_id}


app = create_app()
