# Search Service: Flask to FastAPI Translation Guide

## Overview

This guide describes how to translate the search-service from its current Flask 3.0 synchronous
implementation to a FastAPI asynchronous implementation while preserving all external behaviour.

## Current Stack

| Layer | Technology |
|-------|-----------|
| Framework | Flask 3.0 (WSGI, synchronous) |
| Server | Gunicorn with sync workers |
| Routing | `Blueprint` with `url_prefix` |
| Config | Dataclasses from environment variables (`app/config.py`) |
| Logging | `structlog` with JSON renderer |
| Metrics | `prometheus_client` (Counter, Histogram) |
| Search backend | MeiliSearch via `meilisearch` Python SDK |
| Queue consumer | SQS polling in a background thread |
| Auth | Middleware registered via `require_auth(app)` |

## Target Stack

| Layer | Technology |
|-------|-----------|
| Framework | FastAPI (ASGI, async/await) |
| Server | Uvicorn with uvloop |
| Routing | `APIRouter` with `prefix` |
| Config | Pydantic `BaseSettings` (or keep dataclasses with `from_settings`) |
| Logging | `structlog` with JSON renderer (unchanged) |
| Metrics | `prometheus_client` with ASGI middleware |
| Search backend | MeiliSearch via `meilisearch` SDK (sync calls wrapped with `run_in_executor` or async SDK) |
| Queue consumer | `asyncio.Task` with async SQS polling |
| Auth | FastAPI `Depends()` dependency |

## What Must Be Preserved

1. **All API endpoints** - Every path, method, query parameter, header, request body, and
   response schema documented in `shared/openapi/search-service.yaml`
2. **Prometheus metrics names** - The following metric names must remain identical:
   - `search_service_requests_total` (labels: method, endpoint, status)
   - `search_service_request_duration_seconds` (labels: method, endpoint)
   - `search_service_searches_total`
   - `search_service_index_operations_total` (labels: operation, type)
3. **Structured logging format** - JSON-structured logs via structlog with the same event names
   (e.g., `search_executed`, `advanced_search_executed`, `api_document_indexed`)
4. **MeiliSearch client integration** - Index names (`documents`, `files`), searchable/filterable
   attributes configuration, and all search parameters
5. **Health/readiness checks** - `/health` returns `{"status": "alive", "service": "search-service"}`;
   `/ready` (alias `/health/ready`) pings MeiliSearch and returns 503 when unreachable
6. **Tenant isolation** - X-User-ID header scoping on all search endpoints

## Key Translation Points

### 1. Blueprint to APIRouter

**Current** (`app/api/search.py:16`, `app/main.py:77`):
```python
# app/api/search.py line 16
search_bp = Blueprint("search", __name__)

# app/main.py line 77
app.register_blueprint(search_bp, url_prefix="/api/v1/search")
```

**Target**:
```python
# app/api/search.py
from fastapi import APIRouter
router = APIRouter(prefix="/api/v1/search", tags=["search"])

# app/main.py
from app.api.search import router as search_router
app.include_router(search_router)
```

### 2. Route Decorators

**Current** (`app/api/search.py:44`):
```python
@search_bp.route("/", methods=["GET"], strict_slashes=False)
def search_documents() -> tuple:
```

**Target**:
```python
@router.get("/", response_model=SearchResponse)
async def search_documents(
    q: str = Query(..., description="Search query"),
    type: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_user_id: str | None = Header(None, alias="X-User-ID"),
):
```

### 3. Query Parameters

**Current** (`app/api/search.py:52-58`):
```python
query = request.args.get("q", "")
try:
    page = max(1, int(request.args.get("page", 1)))
    page_size = max(1, min(100, int(request.args.get("size", 20))))
except (ValueError, TypeError):
    return jsonify({"error": "Invalid page or size parameter"}), 400
doc_type = request.args.get("type")
```

**Target**:
```python
# FastAPI validates and coerces automatically via Query()
async def search_documents(
    q: str = Query(...),
    type: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
```
FastAPI returns a 422 Validation Error automatically for invalid types. To keep the exact
400 status code and message format, use a custom exception handler or manual validation.

### 4. Request Headers

**Current** (`app/api/search.py:59`):
```python
owner_id = request.headers.get("X-User-ID", "").strip() or None
```

**Target**:
```python
from fastapi import Header

async def search_documents(
    ...,
    x_user_id: str | None = Header(None, alias="X-User-ID"),
):
    owner_id = x_user_id.strip() if x_user_id else None
```

### 5. JSON Responses

**Current** (`app/api/search.py:75-80`):
```python
return jsonify(results.to_dict()), 200
# or on error:
return jsonify({"error": "Search failed"}), 500
```

**Target** (with Pydantic models):
```python
from pydantic import BaseModel

class SearchHitModel(BaseModel):
    id: str
    title: str
    content_snippet: str
    type: str
    owner_id: str
    tags: list[str] = []
    score: float = 0.0
    highlights: dict[str, list[str]] = {}
    created_at: str | None = None
    updated_at: str | None = None
    mime_type: str | None = None
    folder_id: str | None = None
    size: int | None = None

class SearchResponseModel(BaseModel):
    results: list[SearchHitModel]
    total: int
    page: int
    page_size: int
    query: str

# In the route handler:
@router.get("/", response_model=SearchResponseModel)
async def search_documents(...):
    ...
    return SearchResponseModel(**results.to_dict())
```

For error responses, use `HTTPException`:
```python
from fastapi import HTTPException
raise HTTPException(status_code=500, detail="Search failed")
```

### 6. Request Body (POST endpoints)

**Current** (`app/api/search.py:126`):
```python
data = request.get_json() or {}
query = data.get("q")
```

**Target**:
```python
class AdvancedSearchRequest(BaseModel):
    q: str | None = None
    type: str | None = None
    tags: list[str] | None = None
    date_from: str | None = None
    date_to: str | None = None
    page: int = 1
    size: int = 20

@router.post("/advanced", response_model=SearchResponseModel)
async def advanced_search(
    body: AdvancedSearchRequest,
    x_user_id: str | None = Header(None, alias="X-User-ID"),
):
```

### 7. App Configuration via Dependency Injection

**Current** (`app/api/search.py:39-41`):
```python
def _get_service() -> MeiliSearchService:
    """Get the shared MeiliSearchService from app config."""
    return current_app.config["SEARCH_SERVICE"]
```

**Target**:
```python
from functools import lru_cache
from fastapi import Depends

@lru_cache
def get_config() -> AppConfig:
    return AppConfig()

def get_search_service(config: AppConfig = Depends(get_config)) -> MeiliSearchService:
    # Could also use app.state or a lifespan context
    return MeiliSearchService(config.meilisearch)

@router.get("/")
async def search_documents(
    service: MeiliSearchService = Depends(get_search_service),
    ...
):
```

### 8. Application Factory and Lifespan

**Current** (`app/main.py:51-122`):
```python
def create_app(config: AppConfig | None = None) -> Flask:
    app = Flask(__name__)
    # ... setup ...
    return app
```

**Target**:
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    config = AppConfig()
    search_service = MeiliSearchService(config.meilisearch)
    search_service.ensure_indices()
    app.state.search_service = search_service
    yield
    # Shutdown
    # Clean up resources

app = FastAPI(lifespan=lifespan)
app.include_router(search_router)
app.include_router(index_router)
app.include_router(health_router)
```

### 9. Prometheus Metrics Middleware

**Current** (`app/main.py:84-97`):
```python
@app.before_request
def _start_timer() -> None:
    g.start_time = time.monotonic()

@app.after_request
def _record_metrics(response):
    elapsed = time.monotonic() - g.get("start_time", time.monotonic())
    endpoint = flask_request.url_rule.rule if flask_request.url_rule else "unknown"
    REQUEST_COUNT.labels(...).inc()
    REQUEST_LATENCY.labels(...).observe(elapsed)
    return response
```

**Target**:
```python
from starlette.middleware.base import BaseHTTPMiddleware

class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in ("/metrics", "/health"):
            return await call_next(request)
        start = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - start
        endpoint = request.url.path
        REQUEST_COUNT.labels(
            method=request.method, endpoint=endpoint, status=response.status_code
        ).inc()
        REQUEST_LATENCY.labels(method=request.method, endpoint=endpoint).observe(elapsed)
        return response

app.add_middleware(PrometheusMiddleware)
```

### 10. Health Endpoints

**Current** (`app/api/health.py:39-59`):
```python
@health_bp.route("/health")
def health() -> tuple:
    return jsonify({"status": "alive", "service": "search-service"}), 200

@health_bp.route("/health/ready")
def readiness() -> tuple:
    search_service = current_app.config.get("SEARCH_SERVICE")
    healthy = False
    if search_service:
        healthy = search_service.ping()
    if healthy:
        return jsonify({"ready": True}), 200
    return jsonify({"ready": False, "reason": "meilisearch_unavailable"}), 503
```

**Target**:
```python
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

health_router = APIRouter()

@health_router.get("/health")
async def health():
    return {"status": "alive", "service": "search-service"}

@health_router.get("/health/ready")
async def readiness(request: Request):
    search_service = request.app.state.search_service
    if search_service and search_service.ping():
        return {"ready": True}
    return JSONResponse(
        status_code=503,
        content={"ready": False, "reason": "meilisearch_unavailable"},
    )
```

## File-by-File Reference

| Current file | Purpose | Key lines |
|-------------|---------|-----------|
| `app/main.py` | App factory, blueprint registration, middleware | Lines 51-122 |
| `app/api/search.py` | Search and suggest endpoints | Lines 44-168 |
| `app/api/index.py` | Document/file indexing and removal endpoints | Lines 25-93 |
| `app/api/health.py` | Health, readiness, metrics endpoints and Prometheus counters | Lines 17-69 |
| `app/config.py` | Dataclass-based config from env vars | Lines 1-61 |
| `app/models/search_result.py` | Response dataclasses (SearchHit, SearchResponse, etc.) | Lines 1-100 |
| `app/services/meilisearch_client.py` | MeiliSearch SDK wrapper | Lines 71-402 |
| `app/services/indexer.py` | Indexing logic with validation | Lines 19-198 |
| `app/middleware/auth.py` | Authentication middleware | - |

## Verification Steps

1. **Run the contract tests** against the translated service:
   ```bash
   pytest tests/contract/test_search_contract.py -v
   ```
   The contract tests load `shared/openapi/search-service.yaml` and validate live responses.

2. **Compare Prometheus metrics output**:
   ```bash
   curl http://localhost:8087/metrics | grep search_service_
   ```
   Ensure all four metric families are present with correct label sets.

3. **Verify structured logging**:
   ```bash
   # Start the service and perform a search
   curl "http://localhost:8087/api/v1/search/?q=test" -H "X-User-ID: user-001"
   # Check logs contain JSON with event="search_executed"
   ```

4. **Health checks**:
   ```bash
   curl http://localhost:8087/health
   # {"status": "alive", "service": "search-service"}
   curl http://localhost:8087/ready
   # {"ready": true} or {"ready": false, "reason": "meilisearch_unavailable"}
   ```

5. **Run the existing unit tests** (they test business logic, not Flask-specific code):
   ```bash
   cd services/search-service && pytest tests/ -v
   ```

## Dependencies to Update

Remove from `requirements.txt` / `pyproject.toml`:
- `flask`
- `flask-cors`
- `gunicorn`

Add:
- `fastapi`
- `uvicorn[standard]`
- `pydantic`
- `starlette` (transitive via fastapi)

Keep unchanged:
- `structlog`
- `prometheus-client`
- `meilisearch`
- `boto3` (for SQS)
- `redis`

## Common Pitfalls

1. **MeiliSearch SDK is synchronous** - wrap calls with `asyncio.to_thread()` or use
   `run_in_executor` to avoid blocking the event loop.
2. **`strict_slashes=False`** - FastAPI does not strip trailing slashes by default. Use
   `redirect_slashes=True` in the app config or define both variants.
3. **Error response format** - Flask returns `{"error": "..."}`, FastAPI's default HTTPException
   returns `{"detail": "..."}`. Use a custom exception handler to maintain the `error` key.
4. **Prometheus metrics with async** - `prometheus_client` is thread-safe but the ASGI middleware
   approach differs from Flask's `before_request`/`after_request` hooks.
5. **`g` object** - Flask's request-scoped `g` does not exist in FastAPI. Use middleware state
   or `request.state` instead.
