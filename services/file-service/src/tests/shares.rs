//! Share create/update/remove and the shared-with-me listing.

use actix_web::test::TestRequest;
use serde_json::{json, Value};
use uuid::Uuid;

use super::*;

fn share(id: Uuid, owner: Uuid, body: Value) -> TestRequest {
    as_user(
        TestRequest::post()
            .uri(&format!("/api/v1/files/{id}/share"))
            .set_json(body),
        owner,
    )
}

#[actix_rt::test]
async fn share_creates_then_is_idempotent_then_updates_permission() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (owner, friend) = (Uuid::new_v4(), Uuid::new_v4());
    let id = upload(&app, owner, "a.txt", b"x").await;
    let body = json!({"shared_with": friend, "permission": "viewer", "shared_by": owner});
    let (s, first) = call(&app, share(id, owner, body.clone())).await;
    assert_eq!(s, 201, "{first}");
    assert_eq!(first["share"]["permission"], "viewer");
    let (s, again) = call(&app, share(id, owner, body)).await;
    assert_eq!(s, 200);
    assert_eq!(again["share"]["id"], first["share"]["id"]);
    let (s, upd) = call(
        &app,
        share(
            id,
            owner,
            json!({"shared_with": friend, "permission": "editor", "shared_by": owner}),
        ),
    )
    .await;
    assert_eq!(s, 200);
    assert_eq!(upd["share"]["id"], first["share"]["id"]);
    assert_eq!(upd["share"]["permission"], "editor");
    assert_eq!(ctx.aws.table(SHARES).len(), 1);

    let (_, detail) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files/{id}")),
            owner,
        ),
    )
    .await;
    assert_eq!(detail["shared_with"].as_array().unwrap().len(), 1);
    assert_eq!(detail["shared_with"][0]["shared_with"], friend.to_string());
}

#[actix_rt::test]
async fn new_share_publishes_one_file_shared_event() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (owner, friend) = (Uuid::new_v4(), Uuid::new_v4());
    let id = upload(&app, owner, "a.txt", b"x").await;
    let body = json!({"shared_with": friend, "permission": "viewer", "shared_by": owner});
    call(&app, share(id, owner, body.clone())).await;
    call(&app, share(id, owner, body)).await;
    let shared: Vec<_> = ctx
        .aws
        .sns_published
        .lock()
        .unwrap()
        .iter()
        .filter(|(_, m)| m.contains("file_shared"))
        .cloned()
        .collect();
    assert_eq!(shared.len(), 1, "re-share must not re-notify");
    assert!(shared[0].1.contains(&friend.to_string()));
}

#[actix_rt::test]
async fn share_validation_errors() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    let bad = [
        json!({"shared_with": Uuid::new_v4(), "permission": "owner", "shared_by": owner}),
        json!({"permission": "viewer", "shared_by": owner}),
        json!({"shared_with_email": "  ", "permission": "viewer", "shared_by": owner}),
        json!({"shared_with_email": "nobody@example.com", "permission": "viewer", "shared_by": owner}),
    ];
    for body in bad {
        let (s, resp) = call(&app, share(id, owner, body.clone())).await;
        assert_eq!(s, 400, "{body} -> {resp}");
    }
    let (s, _) = call(
        &app,
        share(
            Uuid::new_v4(),
            owner,
            json!({"shared_with": Uuid::new_v4(), "permission": "viewer", "shared_by": owner}),
        ),
    )
    .await;
    assert_eq!(s, 404);
    assert!(ctx.aws.table(SHARES).is_empty());
}

#[actix_rt::test]
async fn share_event_failure_switch_returns_event_error_but_keeps_share() {
    let ctx = Ctx::with(Opts {
        share_event_always_fail: true,
        ..Default::default()
    })
    .await;
    let app = ctx.app().await;
    let (owner, friend) = (Uuid::new_v4(), Uuid::new_v4());
    let id = upload(&app, owner, "a.txt", b"x").await;
    let (s, body) = call(
        &app,
        share(
            id,
            owner,
            json!({"shared_with": friend, "permission": "viewer", "shared_by": owner}),
        ),
    )
    .await;
    assert_eq!(s, 500, "{body}");
    assert_eq!(body["error"], "event_error");
    assert_eq!(ctx.aws.table(SHARES).len(), 1);

    // Unknown email: publish is attempted (and fails) but no share row is written.
    let (s, _) = call(
        &app,
        share(id, owner, json!({"shared_with_email": "ghost@example.com", "permission": "viewer", "shared_by": owner})),
    )
    .await;
    assert_eq!(s, 500);
    assert_eq!(ctx.aws.table(SHARES).len(), 1);
}

#[actix_rt::test]
async fn remove_share_then_404_on_repeat() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (owner, friend) = (Uuid::new_v4(), Uuid::new_v4());
    let id = upload(&app, owner, "a.txt", b"x").await;
    call(
        &app,
        share(
            id,
            owner,
            json!({"shared_with": friend, "permission": "viewer", "shared_by": owner}),
        ),
    )
    .await;
    let uri = format!("/api/v1/files/{id}/share/{friend}");
    let (s, _) = call(&app, as_user(TestRequest::delete().uri(&uri), owner)).await;
    assert_eq!(s, 204);
    let (s, body) = call(&app, as_user(TestRequest::delete().uri(&uri), owner)).await;
    assert_eq!(s, 404);
    assert_eq!(body["error"], "share_not_found");
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::delete().uri(&format!("/api/v1/files/{id}/share/bad")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 400);
}

#[actix_rt::test]
async fn shared_with_me_requires_user_and_hides_trashed_files() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (s, _) = call(&app, TestRequest::get().uri("/api/v1/files/shared")).await;
    assert_eq!(s, 400);

    let (owner, friend) = (Uuid::new_v4(), Uuid::new_v4());
    let a = upload(&app, owner, "a.txt", b"x").await;
    let b = upload(&app, owner, "b.txt", b"x").await;
    for id in [a, b] {
        call(
            &app,
            share(
                id,
                owner,
                json!({"shared_with": friend, "permission": "viewer", "shared_by": owner}),
            ),
        )
        .await;
    }
    let shared = || as_user(TestRequest::get().uri("/api/v1/files/shared"), friend);
    assert_eq!(call(&app, shared()).await.1["total"], 2);
    call(
        &app,
        as_user(
            TestRequest::post().uri(&format!("/api/v1/files/{b}/trash")),
            owner,
        ),
    )
    .await;
    let (_, body) = call(&app, shared()).await;
    assert_eq!(body["total"], 1);
    assert_eq!(body["files"][0]["name"], "a.txt");
    // The owner does not see their own files in "shared with me".
    assert_eq!(
        call(
            &app,
            as_user(TestRequest::get().uri("/api/v1/files/shared"), owner)
        )
        .await
        .1["total"],
        0
    );
}

#[actix_rt::test]
#[ignore = "FS-07: share records survive permanent delete; owner's activity keeps 'Shared a file' rows for deleted files"]
async fn finding_fs07_permanent_delete_cleans_up_shares() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (owner, friend) = (Uuid::new_v4(), Uuid::new_v4());
    let id = upload(&app, owner, "a.txt", b"x").await;
    call(
        &app,
        share(
            id,
            owner,
            json!({"shared_with": friend, "permission": "viewer", "shared_by": owner}),
        ),
    )
    .await;
    call(
        &app,
        as_user(
            TestRequest::delete().uri(&format!("/api/v1/files/{id}")),
            owner,
        ),
    )
    .await;
    assert!(
        ctx.aws.table(SHARES).is_empty(),
        "orphaned share rows remain"
    );
}
