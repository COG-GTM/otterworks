# Runbook: Search Autocomplete 500 Errors

**Severity:** Critical

## Alert

`SearchSuggestHighErrorRate` -- fires when search-service 5xx rate exceeds 5% over a 1-minute window.

## Symptoms

- Autocomplete suggestions stop appearing in the web app search bar.
- The Chaos Scenarios dashboard shows elevated error rates on the search-service panel.
- Application logs contain `KeyError: '_rankingScore'` in the suggest endpoint handler.

## Investigation Steps

1. Confirm the error in search-service logs:
   ```
   kubectl logs -l app=search-service --tail=100 -n otterworks | grep -i "KeyError\|rankingScore\|500"
   ```
2. Check whether the chaos flag `chaos:search-service:suggest_500` is set in Redis:
   ```
   redis-cli EXISTS chaos:search-service:suggest_500
   ```

<!-- TODO: Complete investigation steps -->

## Resolution Steps

Root cause: the `/suggest` handler sorted suggestion results with
`s["_rankingScore"]`, but `MeiliSearchService.suggest()` returns plain strings and
never requested ranking scores, so the lookup raised `TypeError`/`KeyError` outside
any error handling and returned a 500.

Fix: ranking now happens inside `MeiliSearchService.suggest()`, which requests
`showRankingScore` from MeiliSearch, merges hits from both indexes, and orders them by
`_rankingScore` (missing scores default to 0). The handler always runs inside its
`try/except`, so suggest failures degrade to an empty list instead of a 500.

1. Deploy a search-service build containing the fix.
2. Clear any leftover flag: `redis-cli DEL chaos:search-service:suggest_500`.
3. Confirm `GET /api/v1/search/suggest?q=te` returns 200 and the alert resolves.

## Post-Incident

<!-- TODO -->
