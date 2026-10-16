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

3. Hit the endpoint directly; a 500 for any prefix of 2+ chars confirms the regression:
   ```
   curl -s -o /dev/null -w "%{http_code}\n" -H "X-User-ID: <user>" "http://search-service:8087/api/v1/search/suggest?q=te"
   ```

## Root Cause

The ranking-score enrichment step in the `/suggest` handler sorted suggestions with
`s["_rankingScore"]`. `MeiliSearchService.suggest()` returns plain strings, and MeiliSearch
only includes `_rankingScore` when `showRankingScore` is requested, so the lookup raised
`TypeError` (non-empty results) or `KeyError` (empty results) and the handler returned 500.

## Resolution Steps

1. Deploy a search-service build in which ranking happens inside
   `MeiliSearchService.suggest()` (requests `showRankingScore`, merges document and file hits
   by score, tolerates hits without a score) and the handler no longer does its own key lookup.
2. Clear the leftover Redis key: `redis-cli DEL chaos:search-service:suggest_500`.
3. Confirm `/suggest` returns 200 and the alert resolves within a few minutes.

## Post-Incident

<!-- TODO -->
