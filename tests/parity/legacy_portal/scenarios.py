"""Parity scenarios for every route in services/legacy-portal/DECOMPOSITION.md.

Order matters only where a context has global state: each ``*_empty_state`` scenario
must run before anything writes to that context, and ``announcements_validation`` writes
boundary-length rows so it runs after ``announcements_lifecycle``. Everything else uses
its own user ids. Run the whole suite against a freshly started target.
"""

from __future__ import annotations

from harness import CONTEXTS, Scenario, Step

MISSING_ID = 999999


def _service_scenarios(context: str) -> list[Scenario]:
    return [
        Scenario(
            name=f"{context}_service_health",
            context=context,
            description="Custom /health plus Actuator health, probes and info.",
            steps=(
                Step("custom health", "GET", "/health"),
                Step("actuator health", "GET", "/actuator/health"),
                Step("liveness probe", "GET", "/actuator/health/liveness"),
                Step("readiness probe", "GET", "/actuator/health/readiness"),
                Step("actuator info", "GET", "/actuator/info"),
            ),
        ),
        Scenario(
            name=f"{context}_unknown_route",
            context=context,
            description="Unmapped paths fall through to Boot's default 404 body.",
            steps=(
                Step("unknown api path", "GET", "/api/does-not-exist"),
                Step("unknown root path", "GET", "/nope"),
            ),
        ),
    ]


ANNOUNCEMENTS = [
    Scenario(
        name="announcements_empty_state",
        context="announcements",
        description="Lists on an empty table, default and explicit publishedOnly.",
        steps=(
            Step("list default (publishedOnly=true)", "GET", "/api/announcements"),
            Step(
                "list publishedOnly=true",
                "GET",
                "/api/announcements?publishedOnly=true",
            ),
            Step(
                "list publishedOnly=false",
                "GET",
                "/api/announcements?publishedOnly=false",
            ),
        ),
    ),
    Scenario(
        name="announcements_lifecycle",
        context="announcements",
        description=(
            "Create draft and published rows, newest-first published list, publish "
            "transition, idempotent re-publish, explicit published=false."
        ),
        steps=(
            Step(
                "create draft (published absent)",
                "POST",
                "/api/announcements",
                json_body={
                    "title": "Maintenance window",
                    "body": "Saturday 02:00-04:00 UTC",
                },
                capture={"draft": "id"},
            ),
            Step(
                "create published release 1.0",
                "POST",
                "/api/announcements",
                json_body={
                    "title": "Release 1.0",
                    "body": "v1.0 is out",
                    "published": True,
                },
                capture={"rel10": "id"},
            ),
            Step(
                "create published release 1.1",
                "POST",
                "/api/announcements",
                json_body={
                    "title": "Release 1.1",
                    "body": "v1.1 is out",
                    "published": True,
                },
                capture={"rel11": "id"},
            ),
            Step("get draft", "GET", "/api/announcements/{draft}"),
            Step("get release 1.0", "GET", "/api/announcements/{rel10}"),
            Step("list default is published newest first", "GET", "/api/announcements"),
            Step(
                "list publishedOnly=true is published newest first",
                "GET",
                "/api/announcements?publishedOnly=true",
            ),
            Step(
                "list publishedOnly=false has every row (database order, compared by id)",
                "GET",
                "/api/announcements?publishedOnly=false",
                unordered_by="id",
            ),
            Step("publish draft", "POST", "/api/announcements/{draft}/publish"),
            Step(
                "re-publish draft is idempotent",
                "POST",
                "/api/announcements/{draft}/publish",
            ),
            Step(
                "re-publish release 1.1", "POST", "/api/announcements/{rel11}/publish"
            ),
            Step("get draft after publish", "GET", "/api/announcements/{draft}"),
            Step(
                "published list orders by createdAt, not publish time",
                "GET",
                "/api/announcements",
            ),
            Step(
                "create with explicit published=false",
                "POST",
                "/api/announcements",
                json_body={"title": "Hidden", "body": "not yet", "published": False},
                capture={"hidden": "id"},
            ),
            Step("published list excludes explicit draft", "GET", "/api/announcements"),
            Step(
                "full list includes explicit draft",
                "GET",
                "/api/announcements?publishedOnly=false",
                unordered_by="id",
            ),
        ),
    ),
    Scenario(
        name="announcements_not_found_and_bad_ids",
        context="announcements",
        description=(
            "GlobalExceptionHandler mappings: 404 for unknown ids, 400 with message for "
            "unconvertible ids and publishedOnly values."
        ),
        steps=(
            Step("get unknown id", "GET", f"/api/announcements/{MISSING_ID}"),
            Step("get negative id", "GET", "/api/announcements/-1"),
            Step(
                "publish unknown id", "POST", f"/api/announcements/{MISSING_ID}/publish"
            ),
            Step("get non-numeric id", "GET", "/api/announcements/abc"),
            Step("get decimal id", "GET", "/api/announcements/1.5"),
            Step("publish non-numeric id", "POST", "/api/announcements/abc/publish"),
            Step(
                "list with non-boolean publishedOnly",
                "GET",
                "/api/announcements?publishedOnly=maybe",
            ),
            Step(
                "list with empty publishedOnly",
                "GET",
                "/api/announcements?publishedOnly=",
            ),
        ),
    ),
    Scenario(
        name="announcements_validation",
        context="announcements",
        description=(
            "Bean validation and body parsing failures return Boot's default 400 body; "
            "field limits accept exactly the maximum length."
        ),
        steps=(
            Step("empty object", "POST", "/api/announcements", json_body={}),
            Step(
                "blank title",
                "POST",
                "/api/announcements",
                json_body={"title": "   ", "body": "text"},
            ),
            Step(
                "missing body",
                "POST",
                "/api/announcements",
                json_body={"title": "No body"},
            ),
            Step(
                "title over 200 chars",
                "POST",
                "/api/announcements",
                json_body={"title": "t" * 201, "body": "text"},
            ),
            Step(
                "body over 4000 chars",
                "POST",
                "/api/announcements",
                json_body={"title": "Long body", "body": "b" * 4001},
            ),
            Step(
                "published not a boolean",
                "POST",
                "/api/announcements",
                json_body={"title": "x", "body": "y", "published": "yes"},
            ),
            Step(
                "malformed json",
                "POST",
                "/api/announcements",
                raw_body='{"title": "unterminated',
                content_type="application/json",
            ),
            Step(
                "no request body",
                "POST",
                "/api/announcements",
                content_type="application/json",
            ),
            Step(
                "unsupported content type",
                "POST",
                "/api/announcements",
                raw_body="title=x&body=y",
                content_type="text/plain",
            ),
            Step(
                "title and body at maximum length",
                "POST",
                "/api/announcements",
                json_body={"title": "t" * 200, "body": "b" * 4000},
            ),
        ),
    ),
    Scenario(
        name="announcements_method_not_allowed",
        context="announcements",
        description="Mapped paths with unmapped methods return Boot's default 405 body.",
        steps=(
            Step("DELETE by id", "DELETE", "/api/announcements/1"),
            Step("PUT collection", "PUT", "/api/announcements", json_body={}),
            Step("GET publish", "GET", "/api/announcements/1/publish"),
        ),
    ),
]


PREFERENCES = [
    Scenario(
        name="preferences_defaults_not_persisted",
        context="preferences",
        description="Unknown users get defaults on every read; reads do not create rows.",
        steps=(
            Step("defaults for unknown user", "GET", "/api/preferences/pref-new-user"),
            Step("defaults again", "GET", "/api/preferences/pref-new-user"),
        ),
    ),
    Scenario(
        name="preferences_upsert_overwrite",
        context="preferences",
        description="PUT creates, a second PUT overwrites, absent emailNotifications is false.",
        steps=(
            Step("defaults before first write", "GET", "/api/preferences/pref-alice"),
            Step(
                "create",
                "PUT",
                "/api/preferences/pref-alice",
                json_body={
                    "theme": "dark",
                    "locale": "nl-NL",
                    "emailNotifications": False,
                },
            ),
            Step("read created", "GET", "/api/preferences/pref-alice"),
            Step(
                "overwrite",
                "PUT",
                "/api/preferences/pref-alice",
                json_body={
                    "theme": "solarized",
                    "locale": "en-GB",
                    "emailNotifications": True,
                },
            ),
            Step("read overwritten", "GET", "/api/preferences/pref-alice"),
            Step(
                "overwrite without emailNotifications",
                "PUT",
                "/api/preferences/pref-alice",
                json_body={"theme": "light", "locale": "de-DE"},
            ),
            Step(
                "read after absent emailNotifications",
                "GET",
                "/api/preferences/pref-alice",
            ),
            Step("other user untouched", "GET", "/api/preferences/pref-bob"),
        ),
    ),
    Scenario(
        name="preferences_validation",
        context="preferences",
        description="Validation and parsing failures return the default 400 body and persist nothing.",
        steps=(
            Step("empty object", "PUT", "/api/preferences/pref-invalid", json_body={}),
            Step(
                "blank theme",
                "PUT",
                "/api/preferences/pref-invalid",
                json_body={"theme": " ", "locale": "en-US"},
            ),
            Step(
                "missing locale",
                "PUT",
                "/api/preferences/pref-invalid",
                json_body={"theme": "dark"},
            ),
            Step(
                "theme over 20 chars",
                "PUT",
                "/api/preferences/pref-invalid",
                json_body={"theme": "x" * 21, "locale": "en-US"},
            ),
            Step(
                "locale over 20 chars",
                "PUT",
                "/api/preferences/pref-invalid",
                json_body={"theme": "dark", "locale": "l" * 21},
            ),
            Step(
                "emailNotifications not a boolean",
                "PUT",
                "/api/preferences/pref-invalid",
                json_body={
                    "theme": "dark",
                    "locale": "en-US",
                    "emailNotifications": "sometimes",
                },
            ),
            Step(
                "malformed json",
                "PUT",
                "/api/preferences/pref-invalid",
                raw_body="{theme: dark}",
                content_type="application/json",
            ),
            Step(
                "unsupported content type",
                "PUT",
                "/api/preferences/pref-invalid",
                raw_body="theme=dark",
                content_type="text/plain",
            ),
            Step("nothing persisted", "GET", "/api/preferences/pref-invalid"),
            Step(
                "theme and locale at maximum length",
                "PUT",
                "/api/preferences/pref-limits",
                json_body={
                    "theme": "x" * 20,
                    "locale": "l" * 20,
                    "emailNotifications": True,
                },
            ),
        ),
    ),
    Scenario(
        name="preferences_user_id_edge_cases",
        context="preferences",
        description=(
            "userId is an unchecked path String: dots and encoded spaces are kept, 100 chars "
            "fits the column, 101 chars reads as defaults but fails on write with a 500."
        ),
        steps=(
            Step(
                "userId with a dot",
                "PUT",
                "/api/preferences/first.last",
                json_body={
                    "theme": "dark",
                    "locale": "fr-FR",
                    "emailNotifications": True,
                },
            ),
            Step("read userId with a dot", "GET", "/api/preferences/first.last"),
            Step(
                "userId with an encoded space", "GET", "/api/preferences/pref%20space"
            ),
            Step(
                "userId of 100 chars",
                "PUT",
                "/api/preferences/" + "u" * 100,
                json_body={
                    "theme": "dark",
                    "locale": "en-US",
                    "emailNotifications": False,
                },
            ),
            Step("read userId of 100 chars", "GET", "/api/preferences/" + "u" * 100),
            Step("read userId of 101 chars", "GET", "/api/preferences/" + "v" * 101),
            Step(
                "write userId of 101 chars",
                "PUT",
                "/api/preferences/" + "v" * 101,
                json_body={
                    "theme": "dark",
                    "locale": "en-US",
                    "emailNotifications": False,
                },
            ),
        ),
    ),
    Scenario(
        name="preferences_method_not_allowed",
        context="preferences",
        description="Mapped paths with unmapped methods return Boot's default 405 body.",
        steps=(
            Step("DELETE by user", "DELETE", "/api/preferences/pref-alice"),
            Step(
                "POST by user",
                "POST",
                "/api/preferences/pref-alice",
                json_body={"theme": "dark", "locale": "en-US"},
            ),
        ),
    ),
]


FEEDBACK = [
    Scenario(
        name="feedback_empty_state",
        context="feedback",
        description="Average of an empty table is 0.0; unknown user has no feedback.",
        steps=(
            Step(
                "average rating on empty table", "GET", "/api/feedback/average-rating"
            ),
            Step(
                "list for user with no feedback", "GET", "/api/feedback?userId=fb-alice"
            ),
        ),
    ),
    Scenario(
        name="feedback_submit_list_average",
        context="feedback",
        description=(
            "Submit, list by userId newest first, filtering, empty userId, and the "
            "in-memory average across every row."
        ),
        steps=(
            Step(
                "alice rates 5",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-alice", "rating": 5, "message": "great"},
            ),
            Step(
                "alice rates 4",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-alice", "rating": 4, "message": "good"},
            ),
            Step(
                "bob rates 2",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-bob", "rating": 2, "message": "meh"},
            ),
            Step("alice newest first", "GET", "/api/feedback?userId=fb-alice"),
            Step("bob only", "GET", "/api/feedback?userId=fb-bob"),
            Step("unknown user", "GET", "/api/feedback?userId=fb-nobody"),
            Step("empty userId", "GET", "/api/feedback?userId="),
            Step("average of 5, 4, 2", "GET", "/api/feedback/average-rating"),
            Step(
                "rating as a numeric string is coerced",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-carol", "rating": "3", "message": "ok"},
            ),
            Step(
                "rating and message at the limits",
                "POST",
                "/api/feedback",
                json_body={"userId": "c" * 100, "rating": 1, "message": "m" * 2000},
            ),
            Step("average of 5, 4, 2, 3, 1", "GET", "/api/feedback/average-rating"),
        ),
    ),
    Scenario(
        name="feedback_validation",
        context="feedback",
        description=(
            "Bean validation (rating 1..5, blank/oversized fields) and parsing failures "
            "return the default 400 body; userId is required on the list."
        ),
        steps=(
            Step(
                "rating 0",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-invalid", "rating": 0, "message": "zero"},
            ),
            Step(
                "rating 6",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-invalid", "rating": 6, "message": "six"},
            ),
            Step(
                "rating 9",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-invalid", "rating": 9, "message": "nine"},
            ),
            Step(
                "rating absent",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-invalid", "message": "no rating"},
            ),
            Step(
                "rating not a number",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-invalid", "rating": "five", "message": "text"},
            ),
            Step(
                "blank message",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-invalid", "rating": 3, "message": ""},
            ),
            Step(
                "message over 2000 chars",
                "POST",
                "/api/feedback",
                json_body={"userId": "fb-invalid", "rating": 3, "message": "m" * 2001},
            ),
            Step(
                "blank userId",
                "POST",
                "/api/feedback",
                json_body={"userId": " ", "rating": 3, "message": "who"},
            ),
            Step(
                "userId over 100 chars",
                "POST",
                "/api/feedback",
                json_body={"userId": "u" * 101, "rating": 3, "message": "long"},
            ),
            Step("empty object", "POST", "/api/feedback", json_body={}),
            Step(
                "malformed json",
                "POST",
                "/api/feedback",
                raw_body='{"userId": "fb-invalid", "rating": }',
                content_type="application/json",
            ),
            Step(
                "unsupported content type",
                "POST",
                "/api/feedback",
                raw_body="rating=3",
                content_type="text/plain",
            ),
            Step("list without userId", "GET", "/api/feedback"),
            Step(
                "nothing persisted for rejected user",
                "GET",
                "/api/feedback?userId=fb-invalid",
            ),
        ),
    ),
    Scenario(
        name="feedback_method_not_allowed",
        context="feedback",
        description="Mapped paths with unmapped methods return Boot's default 405 body.",
        steps=(
            Step("DELETE collection", "DELETE", "/api/feedback"),
            Step(
                "POST average-rating",
                "POST",
                "/api/feedback/average-rating",
                json_body={},
            ),
            Step(
                "PUT average-rating",
                "PUT",
                "/api/feedback/average-rating",
                json_body={},
            ),
        ),
    ),
]


SCENARIOS: tuple[Scenario, ...] = (
    *(s for context in CONTEXTS for s in _service_scenarios(context)),
    *ANNOUNCEMENTS,
    *PREFERENCES,
    *FEEDBACK,
)
