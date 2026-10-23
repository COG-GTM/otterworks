# QA audit: search-service

Scope: `services/search-service` (Python/Flask, MeiliSearch). Covers document and file indexing (REST and SNS/SQS events), query, type/tag/date filters, pagination, empty and special-character queries, per-user isolation, and the OpenAPI contract (`shared/openapi/search-service.yaml`, `tests/contract/test_search_contract.py`).

Stack used: `/home/ubuntu/otterworks-up.sh` (core profile) plus `docker compose ... up -d search-service`, built from this branch. All black-box traffic goes through the API gateway (`:8080`) with real JWTs from auth-service. Documents and files are created through document-service and file-service, and reach search through LocalStack SNS→SQS.

## Test pyramid

| Layer | File | Tests | Result |
|---|---|---|---|
| Unit (pytest, mocked MeiliSearch) | `services/search-service/tests/test_qa_search_service.py` | 100 | 87 passed, 13 xfailed (strict) |
| Unit, whole service suite (existing + new) | `services/search-service/tests/` | 141 | 128 passed, 13 xfailed; app coverage 91% |
| Functional/API (gateway) | `tests/api/test_qa_search_service.py` | 33 | 22 passed, 10 xfailed, 1 skipped by default (destructive; xfails as expected with `OTTERWORKS_QA_DESTRUCTIVE=1`) |
| E2E (Playwright) | `frontend/client-app/e2e/qa-search-service.spec.ts` | 4 | 4 passed |
| E2E (computer use) | Testing-agent recording linked from the PR | 1 run | See the PR comment |
| Existing contract tests (live, `:8087`) | `tests/contract/test_search_contract.py` (unchanged) | 18 | 16 passed, 2 failed: `test_index_{document,file}_missing_body` (SEARCH-QA-11) |

Commands:

```bash
cd services/search-service && python -m pytest --cov=app        # unit
python -m pytest tests/api/test_qa_search_service.py -rxXs       # API (stack up, incl. search-service)
OTTERWORKS_QA_DESTRUCTIVE=1 python -m pytest tests/api/test_qa_search_service.py -k reindex
cd frontend/client-app && CI=1 npx playwright test e2e/qa-search-service.spec.ts
```

### What the tests cover

- **Auth**: health/metrics are public. Other routes need `X-User-ID` or the service bearer token. The gateway rejects missing JWTs and drops client-supplied `X-User-ID`.
- **Query**: `q` required, `page`/`size` parsing and clamping (1–100), type routing across both indexes, highlight `<em>` markup, snippet and title mapping, chaos/Redis fallbacks, 500 mapping.
- **Isolation**: the owner filter always comes from `X-User-ID`, never from `owner_id` in the query or body. Filter values are escaped. A second user never sees the first user's document or file through search, advanced search, or the UI.
- **Indexing pipeline**: real document create → SNS → SQS → index; real file upload → index; document delete → removed from index; REST index/delete endpoints; SQS envelope unwrapping, camelCase/snake_case normalisation, delete-vs-redeliver semantics.
- **Pagination**: pages within one index, and pages across the merged documents+files result (totals and no duplicates).
- **Special input**: quotes, HTML/script, SQL-ish text, filter-injection text, `%_*?\`, emoji and accented Unicode all return 200 and no stray results. Unicode titles can be found.
- **Filters**: type (`document`/`file`) in REST and UI, tags (list), date range.

## Findings

Severity: High = cross-user data exposure or tampering; Medium = broken feature or contract; Low = cosmetic or robustness.

| ID | Severity | Location | Repro | Expected | Actual | Live-verified |
|---|---|---|---|---|---|---|
| SEARCH-QA-1 | High | `app/api/search.py` `suggest()` → `app/services/meilisearch_client.py:250-260` | User B: `GET /api/v1/search/suggest?q=<prefix of A's title>` | Only B's titles | Returns A's document and file titles (no `owner_id` filter) | Yes (API) |
| SEARCH-QA-2 | High | `app/api/index.py:26-60`, `app/services/indexer.py:40,65` | User B: `POST /api/v1/search/index/document {"owner_id": "<A>", "title": "Reset your password"}` | 403, or owner forced to the caller | 201. The entry appears in A's search results (result poisoning) | Yes (API) |
| SEARCH-QA-3 | High | `app/api/index.py:66-80`, `app/services/indexer.py:77` | User B: `DELETE /api/v1/search/index/document/<A's doc id>` | 403/404 | 200. A's document disappears from A's search | Yes (API) |
| SEARCH-QA-4 | High | `app/api/index.py:83-93` | Any user: `POST /api/v1/search/reindex` through the gateway | 401/403 (service-token/admin only) | 200. Drops and rebuilds both indexes for every tenant on the instance | Yes (API, destructive test) |
| SEARCH-QA-5 | Medium | `app/services/meilisearch_client.py:217-220`, `app/api/search.py:155` | `POST /api/v1/search/advanced {"q": "x", "date_from": "2025-01-01"}` on an index that has documents | 200 with results in the date range | 500 `Advanced search failed`. Range filters on ISO-string `created_at` are rejected by MeiliSearch, and any filter error is reported as 500, not 400 | Yes (API) |
| SEARCH-QA-6 | Medium | `app/services/indexer.py:87-175` | Reindex while document/file-service returns non-200 | Keep existing index and report failure | Index is cleared and recreated empty. Source fetches send no identity or service token | Unit only. Locally, document-service returns every user's documents to an unauthenticated in-cluster call, so the wipe did not reproduce |
| SEARCH-QA-7 | Medium | `app/api/search.py:160-168` | User B: `GET /api/v1/search/analytics` | Scoped to B, or admin-only | Every user's raw query strings and counts, process-wide | Yes (API) |
| SEARCH-QA-8 | Low | `app/api/search.py:45-80` | `GET /api/v1/search/?q=x&type=spreadsheet` | 400 (OpenAPI enum `document\|file`) | 200, empty | Yes (API) |
| SEARCH-QA-9 | Low | `app/services/meilisearch_client.py:395` | Any search | `score` reflects relevance | Always `0.0`. Ranking score is never requested | Yes (API) |
| SEARCH-QA-10 | Low | `app/services/meilisearch_client.py:215` | `POST /advanced {"tags": "finance"}` | Treated as one tag, or 400 | Split into `tags = "f" AND tags = "i" ...`, so nothing matches | Yes (API) |
| SEARCH-QA-11 | Low | `app/api/search.py:126`, `app/api/index.py:28,48` | `POST /advanced` with no body; `POST /index/document` with an empty JSON body | JSON `{"error": ...}` 400 per contract | Flask HTML 415/400 page. Also fails 2 existing contract tests | Yes (API + contract) |
| SEARCH-QA-12 | Low | `app/services/indexer.py:25-45` | `POST /index/document` with a JSON array | 400 | 500 `Failed to index document` (`AttributeError`) | Yes (API) |

The product code was not changed. Each finding has a strict `xfail` with the matching ID in the unit layer, the API layer, or both. When a bug is fixed, its test will XPASS and fail the suite, which forces whoever fixes it to remove the marker.

Cross-unit observation (not owned here): `GET http://document-service:8083/api/v1/documents/` without `X-User-ID` returns every user's documents on the internal network. This is what makes reindex "work" locally.

## Not tested, and why

- **Real AWS / per-tenant EKS**: local LocalStack only (assignment rules). The SNS/SQS path was exercised end to end on LocalStack.
- **Reindex against file-service in a real tenant**: SNS/SQS is disabled for tenants, and reindex was only run locally.
- **Folder results**: the UI has a "Folders" filter, but search-service has no folder index. Not tested as a search feature.
- **Load, relevance tuning, typo tolerance**: out of scope for a functional audit.
- **`/metrics` content and Prometheus scraping**: only checked that the route is public and returns 200.
