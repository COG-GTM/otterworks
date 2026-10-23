# QA audit: notification-service

Kotlin/Ktor service (`services/notification-service`) behind the gateway at `/api/v1/notifications` and `/api/v1/preferences`, fed by `file_shared` / `comment_added` / `document_edited` / `user_mentioned` events from SNS -> SQS (`otterworks-notifications`). Data lives in the DynamoDB tables `otterworks-notifications` and `otterworks-notification-preferences`.

## What was exercised

- **REST routes**: list (pagination envelope, defaults, `hasMore`, page past the end, newest first), unread count, get by id, mark read, mark all read, delete, `GET`/`PUT /preferences`, health and metrics.
- **Identity and ownership**: a gateway-injected `X-User-ID` wins over a `?user_id=` query parameter; a spoofed `X-User-ID` header is stripped; cross-user get/mark-read/delete; cross-user preference writes.
- **Event-triggered notifications**: user A uploads a file and shares it with user B. B gets an unread `file_shared` notification with `actorId` = A, and A gets none. Also checked how delivery preferences (IN_APP/EMAIL/PUSH) are applied and that email failures are not recorded as delivered.
- **Repository (DynamoDB)**: item mapping, GSI query across `LastEvaluatedKey` pages, in-memory pagination, conditional mark-read, mark-all-read counting, preference defaults and serialisation.
- **WebSocket manager**: per-user session add/remove, push delivery and pruning of broken sessions.
- **Web client (client-app)**: share dialog -> notifications page, bell badge, click-to-read, "Mark all as read", and Settings -> notification preference toggles persisting across reload.

## Pyramid

| Layer | Location | Tests | Pass | xfail / skip |
|---|---|---|---|---|
| Unit (JUnit/Gradle) | `services/notification-service/src/test/kotlin/**/*QaTest.kt` (5 files) | 55 | 46 | 9 `@Ignore` (NS-1..5, 7, 8, 13 + NS-4 repo) |
| Functional (pytest via gateway) | `tests/api/test_qa_notification_service.py` | 25 | 11 | 14 xfail |
| E2E (Playwright) | `frontend/client-app/e2e/qa-notification-service.spec.ts` | 6 | 3 | 3 `test.fail` (NS-6 x2, NS-9) |
| E2E (computer use) | Recorded browser run by the testing agent (recording in the PR comments) | 5 steps | 5 (the share step plus 3 documented defects reproduced: NS-9 bell without badge, NS-6 PATCH returning 404 and POST returning 405) | — |

The whole notification-service Gradle suite (`gradle check`) passes: 93 tests, 0 failures, 9 skipped (all skips are the QA findings above).

## Findings

| ID | Severity | Location | Repro | Expected | Actual |
|---|---|---|---|---|---|
| NS-1 | High | `routes/Routes.kt:88` `GET /notifications/{id}` | User C requests user B's notification id | 403/404 | 200 with B's notification (IDOR) |
| NS-2 | High | `routes/Routes.kt:102` `PUT /notifications/{id}/read` | User C marks B's notification read | 403/404, B's item stays unread | 204, B's item is marked read |
| NS-3 | High | `routes/Routes.kt:127` `DELETE /notifications/{id}` | User C deletes B's notification | 403/404, item survives | 204, item deleted |
| NS-4 | Medium | `routes/Routes.kt:61-62`, `repository/NotificationRepository.kt:88` | `?page=0`, `?page=-1`, `?page_size=0` | 400 | No validation; a negative `drop()` index throws, giving a 500 |
| NS-5 | High | `routes/Routes.kt:154-157` `PUT /preferences` | User C sends `{"userId": B, "eventType": "file_shared", "channels": []}` | Use the authenticated identity, or return 403 | B's preferences are overwritten (B's share notifications are muted) |
| NS-6 | High | `frontend/client-app/src/lib/api.ts:431-435` vs `Routes.kt` | Click a notification, or click "Mark all as read" in the web app | Read state persists | Client sends `PATCH /{id}/read` and `POST /read-all`; the service only routes `PUT`, so the request fails and nothing is marked read |
| NS-7 | Low | `routes/Routes.kt:155` | `PUT /preferences` with a missing `userId` or an unknown channel | 400 | 500 (the global `StatusPages` catches the deserialisation error) |
| NS-8 | Low | `repository/NotificationRepository.kt:143-151` `markAllAsRead` | One `UpdateItem` fails (throttling) | `markedCount` excludes the failures | Every unread item is counted |
| NS-9 | Medium | `frontend/client-app/src/lib/api.ts:439` vs `UnreadCountResponse` | Receive a share and look at the bell | Bell shows the unread badge | Client reads `data.count`, the service returns `unreadCount`, so the badge never appears |
| NS-10 | Medium | `service/NotificationService.kt:75` | Set `file_shared` channels to `["EMAIL"]`, then receive a share | No inbox entry when IN_APP is disabled | Notification is still saved and listed (only `deliveredVia` omits `in_app`) |
| NS-11 | Low | `frontend/client-app/src/lib/api.ts:427` vs `Routes.kt:62` | Client lists notifications with `pageSize` | Page size is honoured | Service only reads `page_size`, so it always uses the default of 20 |
| NS-12 | Medium | `frontend/client-app/src/pages/settings.tsx` / `src/lib/api.ts:668-676` | Turn off "In-app notifications" in Settings | Delivery preferences in notification-service change | The toggles PATCH auth-service `/settings` and never reach `/api/v1/preferences`, so delivery is unaffected (design gap; no test marked) |
| NS-13 | Low | `repository/NotificationRepository.kt:155` | `DELETE /notifications/{random-uuid}` | 404 | 204 (`DeleteItem` is unconditional) |

Each exposing test is marked with its finding ID: `@Ignore("FINDING NS-x ...")` in Kotlin, `pytest.mark.xfail(reason="FINDING NS-x ...")` in pytest, and `test.fail(true, "FINDING NS-x ...")` in Playwright. When a bug is fixed, the strict markers start failing, which tells you to remove the marker. No product code was changed.

## Out-of-scope observation (computer-use run)

- After sharing in the client-app Share dialog, the success toast "Shared with ..." appears, but the dialog's access list keeps showing "No one else has access yet". The recipient still gets the notification and can open the file. This affects the file-service / share-dialog flows, which are outside this unit, so it is recorded here only for the owning QA unit to triage.

## Not tested / limitations

- **Email/SES delivery**: SES is stubbed in LocalStack. Only the `EmailSender` call and the counter logic are unit-tested, not real delivery.
- **WebSocket `/ws/notifications/{userId}` end to end**: the gateway does not proxy this socket and the web client does not use it. Only `WebSocketManager` is unit-tested. Note that the socket path trusts the `userId` in the URL; this is unauthenticated when the service port is reachable directly.
- **`comment_added` / `document_edited` / `user_mentioned` event producers**: event routing is unit-tested, but only `file_shared` was triggered end to end, because the other producers live in other services' scopes.
- **SQS failure mode (`NOTIFICATION_SQS_ALWAYS_FAIL`) and the alert publisher**: left disabled so no alert/Slack/Devin integrations fire. Existing tests cover these.
- **Load and very large inboxes**: `getNotificationsByUserId` reads every page into memory before paginating, which will degrade for large inboxes. This was not load-tested.
