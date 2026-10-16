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

3. Look for `TypeError: string indices must be integers` or `KeyError: '_rankingScore'`
   raised from `suggest()` in `app/api/search.py`.

## Resolution Steps

Root cause (Oct 2026): the ranking-score enrichment step in `/suggest` sorted the output of
`MeiliSearchService.suggest()` with `s["_rankingScore"]`. That method returns plain strings
and never requested `showRankingScore`, so every request raised `TypeError` (results found)
or `KeyError` (no results) and returned 500.

Fix: relevance ordering now lives in `MeiliSearchService.suggest()`, which requests
`showRankingScore` and reads it with a safe default; the handler no longer indexes into
hits. Verify with:

```
curl -s "http://<search-service>:8087/api/v1/search/suggest?q=te"   # expect HTTP 200
```

## Post-Incident

<!-- TODO -->
