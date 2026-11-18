"""Shared test helpers."""

from __future__ import annotations

import json

import meilisearch
import requests


def meili_api_error(status: int = 404, code: str = "index_not_found") -> meilisearch.errors.MeilisearchApiError:
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(
        {"message": code, "code": code, "type": "invalid_request", "link": ""}
    ).encode()
    return meilisearch.errors.MeilisearchApiError(code, response)
