from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import settings
from app.db import connect, reset
from app.domain import BillingDomain


@asynccontextmanager
async def lifespan(_app: FastAPI):
    reset()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class PlanChange(BaseModel):
    plan_id: str
    effective_on: date


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy", "service": settings.app_name}


@app.post("/internal/reset", status_code=204)
def internal_reset() -> Response:
    reset()
    return Response(status_code=204)


@app.get("/api/plans")
def list_plans() -> list[dict]:
    with connect() as connection:
        return BillingDomain(connection).list_plans()


@app.get("/api/tenants/{tenant_id}/entitlement")
def entitlement(
    tenant_id: Annotated[str, Path()],
    on: Annotated[date, Query()],
) -> dict:
    with connect() as connection:
        result = BillingDomain(connection).entitlement(tenant_id, on)
    if result is None:
        raise HTTPException(status_code=404, detail="entitlement not found")
    return result


@app.post("/api/tenants/{tenant_id}/plan-change")
def change_plan(tenant_id: Annotated[str, Path()], request: PlanChange) -> dict:
    try:
        with connect() as connection:
            return BillingDomain(connection).change_plan(
                tenant_id, request.plan_id, request.effective_on
            )
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=400, detail="invalid plan change") from error
