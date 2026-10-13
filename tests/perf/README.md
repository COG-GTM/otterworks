# k6 load tests

Scripts for the core user flows, run through the API gateway:

| Script | Flow | p95 thresholds (ms) |
| --- | --- | --- |
| `auth-login.js` | `POST /api/v1/auth/login` + `GET /api/v1/auth/profile` | login 800, profile 300 |
| `file-upload-list.js` | multipart upload, list, delete | upload 1500, list 500, delete 800 |
| `document-crud.js` | create, get, update, list, delete | create/update 800, get 300, list/delete 500 |
| `search.js` | index seed, `GET /api/v1/search/`, suggest (needs search-service) | query 500, suggest 300 |

All scripts also require `http_req_failed < 1%` and `checks > 99%`. Thresholds are deliberately
loose (shared CI runners, bcrypt on login); tighten them from real baselines.

```bash
k6 run tests/perf/auth-login.js                                  # defaults: 10 VUs, 15s ramp, 45s hold
BASE_URL=http://localhost:8080 VUS=3 RAMP=5s HOLD=20s k6 run tests/perf/document-crud.js
```

Env: `BASE_URL` (default `http://localhost:8080`), `VUS`, `RAMP`, `HOLD`, `FILE_BYTES` (upload size).
The gateway rate-limits per IP (`RATE_LIMIT_RPS`, default 100); raise it before running high VU counts.
CI: `.github/workflows/perf.yml` (manual dispatch or weekly), summaries uploaded as artifacts.
