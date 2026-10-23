//! Folder CRUD through the real routes.

use actix_web::test::TestRequest;
use serde_json::json;
use uuid::Uuid;

use super::*;

async fn create<S, B>(app: &S, owner: Uuid, name: &str, parent: Option<&str>) -> String
where
    S: Service<actix_http::Request, Response = ServiceResponse<B>, Error = actix_web::Error>,
    B: MessageBody,
{
    let (s, body) = call(
        app,
        as_user(
            TestRequest::post()
                .uri("/api/v1/folders")
                .set_json(json!({"name": name, "parent_id": parent, "owner_id": owner})),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 201, "{body}");
    body["id"].as_str().unwrap().to_string()
}

#[actix_rt::test]
async fn create_get_and_list_root_and_child_folders() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let root = create(&app, owner, "Projects", None).await;
    let child = create(&app, owner, "2026", Some(&root)).await;

    let (s, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/folders/{child}")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200);
    assert_eq!(body["name"], "2026");
    assert_eq!(body["parent_id"], root);
    assert_eq!(body["owner_id"], owner.to_string());

    let (_, body) = call(
        &app,
        as_user(TestRequest::get().uri("/api/v1/folders"), owner),
    )
    .await;
    let names: Vec<_> = body["folders"]
        .as_array()
        .unwrap()
        .iter()
        .map(|f| f["name"].clone())
        .collect();
    assert_eq!(names, vec![json!("Projects")]);
    let (_, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/folders?parent_id={root}")),
            owner,
        ),
    )
    .await;
    assert_eq!(body["folders"].as_array().unwrap().len(), 1);
    assert_eq!(body["folders"][0]["id"], child);
}

#[actix_rt::test]
async fn folder_listing_is_scoped_to_gateway_user() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (alice, bob) = (Uuid::new_v4(), Uuid::new_v4());
    create(&app, alice, "Alice", None).await;
    create(&app, bob, "Bob", None).await;
    let (_, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/folders?owner_id={bob}")),
            alice,
        ),
    )
    .await;
    let folders = body["folders"].as_array().unwrap();
    assert_eq!(folders.len(), 1);
    assert_eq!(folders[0]["name"], "Alice");
}

#[actix_rt::test]
async fn update_folder_renames_and_reparents() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let a = create(&app, owner, "A", None).await;
    let b = create(&app, owner, "B", None).await;
    let uri = format!("/api/v1/folders/{b}");
    let (s, body) = call(
        &app,
        as_user(
            TestRequest::put().uri(&uri).set_json(json!({"name": "B2"})),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200, "{body}");
    assert_eq!(body["name"], "B2");
    let (s, body) = call(
        &app,
        as_user(
            TestRequest::put()
                .uri(&uri)
                .set_json(json!({"parent_id": a})),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200);
    assert_eq!(body["parent_id"], a);
    assert_eq!(body["name"], "B2");
}

#[actix_rt::test]
async fn folder_routes_validate_ids_and_404_unknown() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let missing = Uuid::new_v4();
    let (s, body) = call(
        &app,
        TestRequest::get().uri(&format!("/api/v1/folders/{missing}")),
    )
    .await;
    assert_eq!(s, 404);
    assert_eq!(body["error"], "folder_not_found");
    let (s, _) = call(
        &app,
        TestRequest::put()
            .uri(&format!("/api/v1/folders/{missing}"))
            .set_json(json!({"name": "x"})),
    )
    .await;
    assert_eq!(s, 404);
    for req in [
        TestRequest::get().uri("/api/v1/folders/bad"),
        TestRequest::put()
            .uri("/api/v1/folders/bad")
            .set_json(json!({"name": "x"})),
        TestRequest::delete().uri("/api/v1/folders/bad"),
    ] {
        assert_eq!(call(&app, req).await.0, 400);
    }
    // Missing required owner_id in the body is rejected by the JSON extractor.
    let (s, _) = call(
        &app,
        TestRequest::post()
            .uri("/api/v1/folders")
            .set_json(json!({"name": "x"})),
    )
    .await;
    assert_eq!(s, 400);
}

#[actix_rt::test]
async fn delete_folder_removes_it() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let f = create(&app, owner, "Tmp", None).await;
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::delete().uri(&format!("/api/v1/folders/{f}")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 204);
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/folders/{f}")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 404);
}

// ── Findings (ignored = xfail; see docs/qa/file-service.md) ─────────────

#[actix_rt::test]
#[ignore = "FS-09: DELETE /folders/{id} returns 204 for a folder that does not exist"]
async fn finding_fs09_delete_unknown_folder_is_404() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (s, _) = call(
        &app,
        TestRequest::delete().uri(&format!("/api/v1/folders/{}", Uuid::new_v4())),
    )
    .await;
    assert_eq!(s, 404);
}

#[actix_rt::test]
#[ignore = "FS-08: deleting a folder orphans the files inside it (folder_id points at a deleted folder)"]
async fn finding_fs08_delete_folder_does_not_orphan_files() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let f = create(&app, owner, "Docs", None).await;
    let id = upload(&app, owner, "a.txt", b"x").await;
    call(
        &app,
        as_user(
            TestRequest::put()
                .uri(&format!("/api/v1/files/{id}/move"))
                .set_json(json!({"folder_id": f})),
            owner,
        ),
    )
    .await;
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::delete().uri(&format!("/api/v1/folders/{f}")),
            owner,
        ),
    )
    .await;
    // Either refuse (409) or move contents to root / trash; never leave dangling folder_id.
    if s == 204 {
        let (_, body) = call(
            &app,
            as_user(
                TestRequest::get().uri(&format!("/api/v1/files/{id}")),
                owner,
            ),
        )
        .await;
        assert!(
            body["folder_id"].is_null(),
            "file still references deleted folder: {body}"
        );
    } else {
        assert_eq!(s, 409);
    }
}

#[actix_rt::test]
#[ignore = "FS-10: moving a file into a nonexistent folder is accepted (200)"]
async fn finding_fs10_move_into_unknown_folder_is_rejected() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::put()
                .uri(&format!("/api/v1/files/{id}/move"))
                .set_json(json!({"folder_id": Uuid::new_v4()})),
            owner,
        ),
    )
    .await;
    assert!(s == 400 || s == 404, "got {s}");
}

#[actix_rt::test]
#[ignore = "FS-11: a folder can be made its own parent (cycle) and blank folder names are accepted"]
async fn finding_fs11_folder_name_and_parent_validation() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::post()
                .uri("/api/v1/folders")
                .set_json(json!({"name": "   ", "owner_id": owner})),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 400, "blank folder name accepted");
    let f = create(&app, owner, "Loop", None).await;
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::put()
                .uri(&format!("/api/v1/folders/{f}"))
                .set_json(json!({"parent_id": f})),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 400, "folder accepted itself as parent");
}
