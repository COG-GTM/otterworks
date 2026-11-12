#!/usr/bin/env python3
# search_reindex_weekly.py - Weekly full reindex of MeiliSearch
# Originally Python 2.7, minimally ported to Python 3 in 2021
# Clears MeiliSearch indices, paginates through document-service and
# file-service APIs, bulk-indexes into MeiliSearch, validates counts
#
# Owner: Jake (data-team@otterworks.dev) -- Jake left mid-2020
# TODO ETL-112: Add retry logic for transient API failures (2019-12-20)
# TODO ETL-145: Use connection pooling for requests (deferred Q3 2020)
# TODO ETL-188: Add timeout handling everywhere (never done)

import configparser
import json
import sys
import time
from datetime import datetime

import requests

DOCUMENTS_INDEX = "documents"
FILES_INDEX = "files"
API_PAGE_SIZE = 100
SETTINGS_TASK_TIMEOUT = 60
INDEX_TASK_TIMEOUT = 120

RANKING_RULES = ["words", "typo", "proximity", "attribute", "sort", "exactness"]

DOCS_SETTINGS = {
    "searchableAttributes": ["title", "content", "tags"],
    "filterableAttributes": ["type", "owner_id", "tags", "created_at", "updated_at"],
    "sortableAttributes": ["updated_at", "created_at"],
    "rankingRules": RANKING_RULES,
}

FILES_SETTINGS = {
    "searchableAttributes": ["name", "tags", "mime_type"],
    "filterableAttributes": ["type", "owner_id", "mime_type", "folder_id", "tags", "created_at", "updated_at"],
    "sortableAttributes": ["updated_at", "created_at", "size"],
    "rankingRules": RANKING_RULES,
}


def log(message):
    print("[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), message))


class MeiliClient:
    def __init__(self, url, api_key):
        self.url = url
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = "Bearer %s" % api_key

    def wait_for_task(self, task_uid, timeout):
        """Poll a MeiliSearch task until it finishes or `timeout` seconds pass.

        Returns the final task payload, or None if the deadline expired.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            task_resp = requests.get("%s/tasks/%s" % (self.url, task_uid), headers=self.headers)
            task_resp.raise_for_status()
            task = task_resp.json()
            if task.get("status") in ("succeeded", "failed"):
                return task
            time.sleep(1)
        return None

    def _wait_if_enqueued(self, resp, timeout):
        task_uid = resp.json().get("taskUid")
        if task_uid is None:
            return None, None
        return task_uid, self.wait_for_task(task_uid, timeout)

    def delete_index(self, index_name):
        resp = requests.delete("%s/indexes/%s" % (self.url, index_name), headers=self.headers)
        if not resp.ok:
            return
        task_uid, task = self._wait_if_enqueued(resp, SETTINGS_TASK_TIMEOUT)
        if task is not None and task.get("status") == "failed":
            log("WARNING: Delete task %s failed" % task_uid)
        log("Deleted index: %s" % index_name)

    def create_index(self, index_name):
        resp = requests.post(
            "%s/indexes" % self.url,
            headers=self.headers,
            data=json.dumps({"uid": index_name, "primaryKey": "id"}),
        )
        resp.raise_for_status()
        self._wait_if_enqueued(resp, SETTINGS_TASK_TIMEOUT)
        log("Created index: %s" % index_name)

    def update_settings(self, index_name, settings):
        resp = requests.patch(
            "%s/indexes/%s/settings" % (self.url, index_name),
            headers=self.headers,
            data=json.dumps(settings),
        )
        resp.raise_for_status()
        self._wait_if_enqueued(resp, SETTINGS_TASK_TIMEOUT)

    def add_documents(self, index_name, batch):
        resp = requests.post(
            "%s/indexes/%s/documents" % (self.url, index_name),
            headers=self.headers,
            data=json.dumps(batch),
        )
        resp.raise_for_status()
        _, task = self._wait_if_enqueued(resp, INDEX_TASK_TIMEOUT)
        if task is not None and task.get("status") == "failed":
            log("WARNING: Index task failed: %s" % task.get("error", {}))

    def document_count(self, index_name):
        resp = requests.get("%s/indexes/%s/stats" % (self.url, index_name), headers=self.headers)
        resp.raise_for_status()
        return resp.json().get("numberOfDocuments", 0)


def to_document_record(doc):
    return {
        "id": doc.get("document_id", doc.get("id", "")),
        "title": doc.get("title", ""),
        "content": doc.get("content", ""),
        "owner_id": doc.get("owner_id", ""),
        "tags": doc.get("tags", []),
        "type": "document",
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def to_file_record(f):
    return {
        "id": f.get("file_id", f.get("id", "")),
        "name": f.get("file_name", f.get("name", "")),
        "owner_id": f.get("owner_id", ""),
        "mime_type": f.get("mime_type", ""),
        "folder_id": f.get("folder_id", ""),
        "size": f.get("size_bytes", f.get("size", 0)),
        "tags": f.get("tags", []),
        "type": "file",
        "created_at": f.get("created_at"),
        "updated_at": f.get("updated_at"),
    }


def reindex_source(meili, index_name, source_url, size_param, items_key, to_record):
    """Page through a service listing API and bulk-index every page.

    Returns the number of source items indexed.
    """
    indexed = 0
    page = 1
    while True:
        # No session reuse, no timeout, no retry -- just raw requests
        resp = requests.get(source_url, params={"page": page, size_param: API_PAGE_SIZE})
        resp.raise_for_status()
        data = resp.json()
        items = data.get(items_key, data.get("items", []))

        if not items:
            break

        meili.add_documents(index_name, [to_record(item) for item in items])
        indexed += len(items)

        if len(items) < API_PAGE_SIZE:
            break
        page += 1
    return indexed


def reset_indices(meili):
    log("Clearing MeiliSearch indices...")
    for index_name in [DOCUMENTS_INDEX, FILES_INDEX]:
        try:
            meili.delete_index(index_name)
        except Exception:
            log("Index %s did not exist, skipping delete" % index_name)

    for index_name in [DOCUMENTS_INDEX, FILES_INDEX]:
        meili.create_index(index_name)

    meili.update_settings(DOCUMENTS_INDEX, DOCS_SETTINGS)
    meili.update_settings(FILES_INDEX, FILES_SETTINGS)
    log("MeiliSearch indices configured")


def validate_counts(meili, docs_indexed, files_indexed):
    log("Validating index counts...")
    docs_count = meili.document_count(DOCUMENTS_INDEX)
    files_count = meili.document_count(FILES_INDEX)

    log("Validation: documents=%d (expected %d), files=%d (expected %d)" % (
        docs_count, docs_indexed,
        files_count, files_indexed,
    ))

    if docs_count != docs_indexed:
        log("ERROR: Documents index count mismatch: %d != %d" % (docs_count, docs_indexed))
        sys.exit(1)
    if files_count != files_indexed:
        log("ERROR: Files index count mismatch: %d != %d" % (files_count, files_indexed))
        sys.exit(1)


def main():
    log("search_reindex_weekly.py starting...")

    config = configparser.ConfigParser()
    config.read("/opt/etl/config.ini")

    document_service_url = config.get("services", "document_service_url")
    file_service_url = config.get("services", "file_service_url")
    meili = MeiliClient(
        config.get("services", "meilisearch_url"),
        config.get("services", "meilisearch_api_key"),
    )

    reset_indices(meili)

    log("Indexing documents from document-service...")
    docs_indexed = reindex_source(
        meili, DOCUMENTS_INDEX, "%s/api/v1/documents" % document_service_url,
        "size", "documents", to_document_record,
    )
    log("Indexed %d documents into %s" % (docs_indexed, DOCUMENTS_INDEX))

    log("Indexing files from file-service...")
    files_indexed = reindex_source(
        meili, FILES_INDEX, "%s/api/v1/files" % file_service_url,
        "page_size", "files", to_file_record,
    )
    log("Indexed %d files into %s" % (files_indexed, FILES_INDEX))

    validate_counts(meili, docs_indexed, files_indexed)

    log("search_reindex_weekly.py completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log("FATAL: %s" % str(e))
        sys.exit(1)
