//! Ownership / IDOR checks for every ID-addressed route. The gateway injects
//! the caller's identity as `X-User-ID`; a non-owner without a share must not
//! be able to read or mutate another user's file or folder.
//!
//! The service performs no such check today, so the expected-secure tests are
//! `#[ignore]`d (xfail) with the finding id; `current_*` tests pin the
//! observed behaviour so a fix flips them.

use actix_web::test::TestRequest;
use serde_json::json;
use uuid::Uuid;

use super::*;

fn denied(status: u16) -> bool {
    status == 403 || status == 404
}

struct World {
    alice: Uuid,
    mallory: Uuid,
    file: Uuid,
    folder: String,
}

async fn world<S, B>(app: &S) -> World
where
    S: Service<actix_http::Request, Response = ServiceResponse<B>, Error = actix_web::Error>,
    B: MessageBody,
{
    let (alice, mallory) = (Uuid::new_v4(), Uuid::new_v4());
    let file = upload(app, alice, "payroll.xlsx", b"secret").await;
    let (_, folder) = call(
        app,
        as_user(
            TestRequest::post()
                .uri("/api/v1/folders")
                .set_json(json!({"name": "HR", "owner_id": alice})),
            alice,
        ),
    )
    .await;
    World {
        alice,
        mallory,
        file,
        folder: folder["id"].as_str().unwrap().to_string(),
    }
}

#[actix_rt::test]
async fn current_non_owner_can_read_and_mutate_any_file() {
    // Pins FS-01/FS-02 as observed: every request below succeeds for Mallory.
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let w = world(&app).await;
    let f = w.file;
    let m = w.mallory;
    let reqs = [
        TestRequest::get().uri(&format!("/api/v1/files/{f}")),
        TestRequest::get().uri(&format!("/api/v1/files/{f}/download")),
        TestRequest::get().uri(&format!("/api/v1/files/{f}/versions")),
        TestRequest::patch()
            .uri(&format!("/api/v1/files/{f}/rename"))
            .set_json(json!({"name": "pwned"})),
        TestRequest::post().uri(&format!("/api/v1/files/{f}/trash")),
        TestRequest::post().uri(&format!("/api/v1/files/{f}/restore")),
    ];
    for req in reqs {
        let (s, body) = call(&app, as_user(req, m)).await;
        assert_eq!(s, 200, "{body}");
    }
    let (_, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files/{f}")),
            w.alice,
        ),
    )
    .await;
    assert_eq!(body["name"], "pwned");
}

macro_rules! idor_case {
    ($name:ident, $finding:literal, |$w:ident| $req:expr) => {
        #[actix_rt::test]
        #[ignore = $finding]
        async fn $name() {
            let ctx = Ctx::new().await;
            let app = ctx.app().await;
            let $w = world(&app).await;
            let (s, body) = call(&app, as_user($req, $w.mallory)).await;
            assert!(denied(s), "non-owner got {s}: {body}");
        }
    };
}

idor_case!(
    idor_get_metadata,
    "FS-01: GET /files/{id} has no ownership check (IDOR)",
    |w| TestRequest::get().uri(&format!("/api/v1/files/{}", w.file))
);
idor_case!(
    idor_download,
    "FS-01: GET /files/{id}/download issues a presigned URL to any caller (IDOR)",
    |w| TestRequest::get().uri(&format!("/api/v1/files/{}/download", w.file))
);
idor_case!(
    idor_versions,
    "FS-01: GET /files/{id}/versions has no ownership check (IDOR)",
    |w| TestRequest::get().uri(&format!("/api/v1/files/{}/versions", w.file))
);
idor_case!(
    idor_rename,
    "FS-02: PATCH /files/{id}/rename has no ownership check (IDOR)",
    |w| TestRequest::patch()
        .uri(&format!("/api/v1/files/{}/rename", w.file))
        .set_json(json!({"name": "x"}))
);
idor_case!(
    idor_move,
    "FS-02: PUT /files/{id}/move has no ownership check (IDOR)",
    |w| TestRequest::put()
        .uri(&format!("/api/v1/files/{}/move", w.file))
        .set_json(json!({"folder_id": null}))
);
idor_case!(
    idor_trash,
    "FS-02: POST /files/{id}/trash has no ownership check (IDOR)",
    |w| TestRequest::post().uri(&format!("/api/v1/files/{}/trash", w.file))
);
idor_case!(
    idor_restore,
    "FS-02: POST /files/{id}/restore has no ownership check (IDOR)",
    |w| TestRequest::post().uri(&format!("/api/v1/files/{}/restore", w.file))
);
idor_case!(
    idor_delete,
    "FS-02: DELETE /files/{id} permanently deletes any user's file (IDOR)",
    |w| TestRequest::delete().uri(&format!("/api/v1/files/{}", w.file))
);
idor_case!(
    idor_share,
    "FS-03: POST /files/{id}/share lets a non-owner grant themselves access",
    |w| TestRequest::post()
        .uri(&format!("/api/v1/files/{}/share", w.file))
        .set_json(json!({"shared_with": w.mallory, "permission": "editor", "shared_by": w.alice}))
);
idor_case!(
    idor_get_folder,
    "FS-04: GET /folders/{id} has no ownership check (IDOR)",
    |w| TestRequest::get().uri(&format!("/api/v1/folders/{}", w.folder))
);
idor_case!(
    idor_update_folder,
    "FS-04: PUT /folders/{id} has no ownership check (IDOR)",
    |w| TestRequest::put()
        .uri(&format!("/api/v1/folders/{}", w.folder))
        .set_json(json!({"name": "x"}))
);
idor_case!(
    idor_delete_folder,
    "FS-04: DELETE /folders/{id} has no ownership check (IDOR)",
    |w| TestRequest::delete().uri(&format!("/api/v1/folders/{}", w.folder))
);

#[actix_rt::test]
#[ignore = "FS-03: DELETE /files/{id}/share/{user} lets a non-owner revoke the owner's shares"]
async fn idor_remove_share() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let w = world(&app).await;
    let friend = Uuid::new_v4();
    call(
        &app,
        as_user(
            TestRequest::post()
                .uri(&format!("/api/v1/files/{}/share", w.file))
                .set_json(
                    json!({"shared_with": friend, "permission": "viewer", "shared_by": w.alice}),
                ),
            w.alice,
        ),
    )
    .await;
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::delete().uri(&format!("/api/v1/files/{}/share/{friend}", w.file)),
            w.mallory,
        ),
    )
    .await;
    assert!(denied(s), "non-owner revoked share: {s}");
}

#[actix_rt::test]
#[ignore = "FS-03: share_file trusts body `shared_by` instead of the authenticated X-User-ID"]
async fn share_records_authenticated_sharer() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let w = world(&app).await;
    let spoofed = Uuid::new_v4();
    let (_, body) = call(
        &app,
        as_user(
            TestRequest::post()
                .uri(&format!("/api/v1/files/{}/share", w.file))
                .set_json(json!({"shared_with": Uuid::new_v4(), "permission": "viewer", "shared_by": spoofed})),
            w.alice,
        ),
    )
    .await;
    assert_eq!(body["share"]["shared_by"], w.alice.to_string());
}

#[actix_rt::test]
#[ignore = "FS-04: POST /folders trusts body owner_id, so a caller can create folders in another user's drive"]
async fn create_folder_uses_authenticated_owner() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (mallory, victim) = (Uuid::new_v4(), Uuid::new_v4());
    let (s, body) = call(
        &app,
        as_user(
            TestRequest::post()
                .uri("/api/v1/folders")
                .set_json(json!({"name": "planted", "owner_id": victim})),
            mallory,
        ),
    )
    .await;
    assert!(
        s == 403 || body["owner_id"] == mallory.to_string(),
        "{s}: {body}"
    );
}

#[actix_rt::test]
async fn shared_viewer_access_is_expected_to_remain_allowed() {
    // Guard for a future fix: a share recipient must keep read access.
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let w = world(&app).await;
    let friend = Uuid::new_v4();
    call(
        &app,
        as_user(
            TestRequest::post()
                .uri(&format!("/api/v1/files/{}/share", w.file))
                .set_json(
                    json!({"shared_with": friend, "permission": "viewer", "shared_by": w.alice}),
                ),
            w.alice,
        ),
    )
    .await;
    for uri in [
        format!("/api/v1/files/{}", w.file),
        format!("/api/v1/files/{}/download", w.file),
    ] {
        let (s, body) = call(&app, as_user(TestRequest::get().uri(&uri), friend)).await;
        assert_eq!(s, 200, "{uri}: {body}");
    }
}
