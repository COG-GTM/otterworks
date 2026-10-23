//! Upload, metadata, download, rename, move, trash/restore, delete, listing,
//! versions and activity through the real routes.

use actix_web::test::TestRequest;
use serde_json::json;
use uuid::Uuid;

use super::*;

#[actix_rt::test]
async fn health_and_metrics_are_served() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (s, body) = call(&app, TestRequest::get().uri("/health")).await;
    assert_eq!(s, 200);
    assert_eq!(body["status"], "healthy");
    let resp = test::call_service(&app, TestRequest::get().uri("/metrics").to_request()).await;
    assert_eq!(resp.status(), 200);
}

#[actix_rt::test]
async fn upload_persists_object_metadata_and_first_version() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let (s, body) = call(
        &app,
        upload_req(
            Some(owner),
            &[("file", Some("notes.txt"), Some("text/plain"), b"hello")],
        ),
    )
    .await;
    assert_eq!(s, 201, "{body}");
    let f = &body["file"];
    assert_eq!(f["name"], "notes.txt");
    assert_eq!(f["mime_type"], "text/plain");
    assert_eq!(f["size_bytes"], 5);
    assert_eq!(f["owner_id"], owner.to_string());
    assert_eq!(f["version"], 1);
    assert_eq!(f["is_trashed"], false);
    let id = f["id"].as_str().unwrap();
    let key = format!("files/{owner}/{id}");
    assert_eq!(f["s3_key"], key);
    assert!(ctx.aws.has_object(BUCKET, &key));
    assert_eq!(ctx.aws.table(FILES).len(), 1);
    let versions = ctx.aws.table(VERSIONS);
    assert_eq!(versions.len(), 1);
    assert_eq!(versions[0]["file_id"]["S"], id);
}

#[actix_rt::test]
async fn upload_falls_back_to_multipart_owner_id_without_gateway_header() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4().to_string();
    let (s, body) = call(
        &app,
        upload_req(
            None,
            &[
                ("owner_id", None, None, owner.as_bytes()),
                ("file", Some("a.txt"), Some("text/plain"), b"x"),
            ],
        ),
    )
    .await;
    assert_eq!(s, 201, "{body}");
    assert_eq!(body["file"]["owner_id"], owner);
}

#[actix_rt::test]
async fn upload_gateway_header_overrides_spoofed_multipart_owner() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let real = Uuid::new_v4();
    let spoofed = Uuid::new_v4().to_string();
    let (s, body) = call(
        &app,
        upload_req(
            Some(real),
            &[
                ("owner_id", None, None, spoofed.as_bytes()),
                ("file", Some("a.txt"), Some("text/plain"), b"x"),
            ],
        ),
    )
    .await;
    assert_eq!(s, 201);
    assert_eq!(body["file"]["owner_id"], real.to_string());
}

#[actix_rt::test]
async fn upload_validation_errors_are_400_and_write_nothing() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let file: Part = ("file", Some("a.txt"), Some("text/plain"), b"x");
    let cases: Vec<(Option<Uuid>, Vec<Part>)> = vec![
        // no owner at all
        (None, vec![file]),
        // empty file
        (
            Some(owner),
            vec![("file", Some("a.txt"), Some("text/plain"), b"")],
        ),
        // no file part
        (Some(owner), vec![("folder_id", None, None, b"")]),
        // malformed owner_id
        (None, vec![("owner_id", None, None, b"not-a-uuid"), file]),
        // malformed folder_id
        (Some(owner), vec![("folder_id", None, None, b"nope"), file]),
    ];
    for (user, parts) in cases {
        let (s, body) = call(&app, upload_req(user, &parts)).await;
        assert_eq!(s, 400, "{body}");
        assert_eq!(body["error"], "bad_request");
    }
    assert!(ctx.aws.table(FILES).is_empty());
    assert!(ctx.aws.objects.lock().unwrap().is_empty());
}

#[actix_rt::test]
async fn upload_size_limit_is_inclusive_and_oversize_is_413() {
    let ctx = Ctx::with(Opts {
        max_upload_bytes: 8,
        ..Default::default()
    })
    .await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let (s, _) = call(
        &app,
        upload_req(Some(owner), &[("file", Some("ok.bin"), None, &[1u8; 8])]),
    )
    .await;
    assert_eq!(s, 201);
    let (s, body) = call(
        &app,
        upload_req(Some(owner), &[("file", Some("big.bin"), None, &[1u8; 9])]),
    )
    .await;
    assert_eq!(s, 413, "{body}");
    assert_eq!(body["error"], "file_too_large");
    assert_eq!(ctx.aws.table(FILES).len(), 1);
}

#[actix_rt::test]
async fn upload_defaults_content_type_and_honours_folder_id() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4().to_string();
    let (s, body) = call(
        &app,
        upload_req(
            Some(owner),
            &[
                ("folder_id", None, None, folder.as_bytes()),
                ("file", Some("blob"), None, b"abc"),
            ],
        ),
    )
    .await;
    assert_eq!(s, 201, "{body}");
    assert_eq!(body["file"]["mime_type"], "application/octet-stream");
    assert_eq!(body["file"]["folder_id"], folder);
}

#[actix_rt::test]
async fn upload_redis_chaos_flag_surfaces_storage_error_without_metadata() {
    let ctx = Ctx::new().await;
    ctx.redis.set_flag("chaos:file-service:upload_s3_error");
    let app = ctx.app().await;
    let (s, body) = call(
        &app,
        upload_req(Some(Uuid::new_v4()), &[("file", Some("a.txt"), None, b"x")]),
    )
    .await;
    assert_eq!(s, 500, "{body}");
    assert_eq!(body["error"], "storage_error");
    assert!(ctx.aws.table(FILES).is_empty());
}

#[actix_rt::test]
async fn upload_always_fail_switch_surfaces_storage_error() {
    let ctx = Ctx::with(Opts {
        upload_always_fail: true,
        ..Default::default()
    })
    .await;
    let app = ctx.app().await;
    let (s, body) = call(
        &app,
        upload_req(Some(Uuid::new_v4()), &[("file", Some("a.txt"), None, b"x")]),
    )
    .await;
    assert_eq!(s, 500);
    assert_eq!(body["error"], "storage_error");
    assert!(ctx.aws.table(FILES).is_empty());
}

#[actix_rt::test]
async fn upload_publishes_file_uploaded_event() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let id = upload(&app, Uuid::new_v4(), "a.txt", b"x").await;
    let published = ctx.aws.sns_published.lock().unwrap().clone();
    assert_eq!(published.len(), 1);
    assert_eq!(published[0].0, TOPIC);
    assert!(
        published[0].1.contains("file_uploaded"),
        "{}",
        published[0].1
    );
    assert!(published[0].1.contains(&id.to_string()));
}

#[actix_rt::test]
async fn get_metadata_returns_file_and_shares_or_404_400() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    let (s, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files/{id}")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200);
    assert_eq!(body["id"], id.to_string());
    assert_eq!(body["shared_with"], json!([]));

    let (s, body) = call(
        &app,
        TestRequest::get().uri(&format!("/api/v1/files/{}", Uuid::new_v4())),
    )
    .await;
    assert_eq!(s, 404);
    assert_eq!(body["error"], "file_not_found");
    let (s, body) = call(&app, TestRequest::get().uri("/api/v1/files/not-a-uuid")).await;
    assert_eq!(s, 400);
    assert_eq!(body["error"], "bad_request");
}

#[actix_rt::test]
async fn download_returns_presigned_url_for_object_key() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    let (s, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files/{id}/download")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200, "{body}");
    assert_eq!(body["expires_in_secs"], 3600);
    let url = body["url"].as_str().unwrap();
    assert!(
        url.contains(&format!("{BUCKET}/files/{owner}/{id}")),
        "{url}"
    );
    assert!(url.contains("X-Amz-Signature="), "{url}");
    assert!(url.contains("X-Amz-Expires=3600"), "{url}");

    let (s, _) = call(
        &app,
        TestRequest::get().uri(&format!("/api/v1/files/{}/download", Uuid::new_v4())),
    )
    .await;
    assert_eq!(s, 404);
    let (s, _) = call(&app, TestRequest::get().uri("/api/v1/files/zzz/download")).await;
    assert_eq!(s, 400);
}

#[actix_rt::test]
async fn rename_trims_name_and_rejects_blank_or_unknown() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    let uri = format!("/api/v1/files/{id}/rename");
    let (s, body) = call(
        &app,
        as_user(
            TestRequest::patch()
                .uri(&uri)
                .set_json(json!({"name": "  b.txt  "})),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200, "{body}");
    assert_eq!(body["name"], "b.txt");
    for blank in ["", "   "] {
        let (s, _) = call(
            &app,
            as_user(
                TestRequest::patch()
                    .uri(&uri)
                    .set_json(json!({"name": blank})),
                owner,
            ),
        )
        .await;
        assert_eq!(s, 400);
    }
    let (s, _) = call(
        &app,
        TestRequest::patch()
            .uri(&format!("/api/v1/files/{}/rename", Uuid::new_v4()))
            .set_json(json!({"name": "c"})),
    )
    .await;
    assert_eq!(s, 404);
}

#[actix_rt::test]
async fn move_into_folder_and_back_to_root() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    let (_, folder) = call(
        &app,
        as_user(
            TestRequest::post()
                .uri("/api/v1/folders")
                .set_json(json!({"name": "Docs", "owner_id": owner})),
            owner,
        ),
    )
    .await;
    let folder_id = folder["id"].as_str().unwrap().to_string();
    let uri = format!("/api/v1/files/{id}/move");
    let (s, body) = call(
        &app,
        as_user(
            TestRequest::put()
                .uri(&uri)
                .set_json(json!({"folder_id": folder_id})),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200, "{body}");
    assert_eq!(body["folder_id"], folder_id);

    let (_, listing) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files?folder_id={folder_id}")),
            owner,
        ),
    )
    .await;
    assert_eq!(listing["total"], 1);

    let (s, body) = call(
        &app,
        as_user(
            TestRequest::put()
                .uri(&uri)
                .set_json(json!({"folder_id": null})),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200);
    assert!(body.get("folder_id").is_none_or(|v| v.is_null()), "{body}");

    let (s, _) = call(
        &app,
        TestRequest::put()
            .uri(&format!("/api/v1/files/{}/move", Uuid::new_v4()))
            .set_json(json!({"folder_id": null})),
    )
    .await;
    assert_eq!(s, 404);
}

#[actix_rt::test]
async fn trash_hides_file_from_listing_and_restore_brings_it_back() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    let list = || as_user(TestRequest::get().uri("/api/v1/files"), owner);
    let trash = || as_user(TestRequest::get().uri("/api/v1/files/trash"), owner);

    let (s, body) = call(
        &app,
        as_user(
            TestRequest::post().uri(&format!("/api/v1/files/{id}/trash")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200, "{body}");
    assert_eq!(body["is_trashed"], true);
    assert_eq!(call(&app, list()).await.1["total"], 0);
    assert_eq!(call(&app, trash()).await.1["total"], 1);
    let (_, all) = call(
        &app,
        as_user(
            TestRequest::get().uri("/api/v1/files?include_trashed=true"),
            owner,
        ),
    )
    .await;
    assert_eq!(all["total"], 1);

    let (s, body) = call(
        &app,
        as_user(
            TestRequest::post().uri(&format!("/api/v1/files/{id}/restore")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200);
    assert_eq!(body["is_trashed"], false);
    assert_eq!(call(&app, list()).await.1["total"], 1);
    assert_eq!(call(&app, trash()).await.1["total"], 0);

    for action in ["trash", "restore"] {
        let (s, body) = call(
            &app,
            TestRequest::post().uri(&format!("/api/v1/files/{}/{action}", Uuid::new_v4())),
        )
        .await;
        assert_eq!(s, 404, "{action}: {body}");
        assert_eq!(body["error"], "file_not_found");
    }
}

#[actix_rt::test]
async fn permanent_delete_removes_metadata_and_object() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    let key = format!("files/{owner}/{id}");
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::delete().uri(&format!("/api/v1/files/{id}")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 204);
    assert!(ctx.aws.table(FILES).is_empty());
    assert!(!ctx.aws.has_object(BUCKET, &key));
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files/{id}")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 404);
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::delete().uri(&format!("/api/v1/files/{id}")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 404);
}

#[actix_rt::test]
async fn list_scopes_to_gateway_user_and_ignores_spoofed_owner_query() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (alice, bob) = (Uuid::new_v4(), Uuid::new_v4());
    upload(&app, alice, "alice.txt", b"a").await;
    upload(&app, bob, "bob.txt", b"b").await;
    let (_, body) = call(
        &app,
        as_user(TestRequest::get().uri("/api/v1/files"), alice),
    )
    .await;
    assert_eq!(body["total"], 1);
    assert_eq!(body["files"][0]["name"], "alice.txt");
    let (_, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files?owner_id={bob}")),
            alice,
        ),
    )
    .await;
    assert_eq!(body["total"], 1);
    assert_eq!(body["files"][0]["name"], "alice.txt");
    let (_, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files/trash?owner_id={bob}")),
            alice,
        ),
    )
    .await;
    assert_eq!(body["total"], 0);
}

#[actix_rt::test]
async fn list_pagination_clamps_page_and_page_size() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    for i in 0..3 {
        upload(&app, owner, &format!("f{i}.txt"), b"x").await;
    }
    let get = |q: &str| as_user(TestRequest::get().uri(&format!("/api/v1/files?{q}")), owner);
    let (_, b) = call(&app, get("page=1&page_size=2")).await;
    assert_eq!(
        (b["total"].as_u64(), b["files"].as_array().unwrap().len()),
        (Some(3), 2)
    );
    let (_, b) = call(&app, get("page=2&page_size=2")).await;
    assert_eq!(b["files"].as_array().unwrap().len(), 1);
    let (_, b) = call(&app, get("page=0&page_size=500")).await;
    assert_eq!(b["page"], 1);
    assert_eq!(b["page_size"], 100);
    let (_, b) = call(&app, get("page=99")).await;
    assert_eq!(b["files"], json!([]));
    let (s, _) = call(&app, get("page=-1")).await;
    assert_eq!(s, 400);
}

#[actix_rt::test]
async fn versions_lists_initial_version_and_rejects_bad_id() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"hello").await;
    let (s, body) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files/{id}/versions")),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 200, "{body}");
    let versions = body["versions"].as_array().unwrap();
    assert_eq!(versions.len(), 1);
    assert_eq!(versions[0]["version"], 1);
    assert_eq!(versions[0]["size_bytes"], 5);
    let (s, _) = call(&app, TestRequest::get().uri("/api/v1/files/bad/versions")).await;
    assert_eq!(s, 400);
}

#[actix_rt::test]
#[ignore = "FS-13: GET /files/{id}/versions returns 200 [] for a file that does not exist"]
async fn finding_fs13_versions_of_unknown_file_is_404() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (s, _) = call(
        &app,
        TestRequest::get().uri(&format!("/api/v1/files/{}/versions", Uuid::new_v4())),
    )
    .await;
    assert_eq!(s, 404);
}

#[actix_rt::test]
async fn activity_requires_user_and_lists_uploads_and_shares() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (s, body) = call(&app, TestRequest::get().uri("/api/v1/files/activity")).await;
    assert_eq!(s, 400, "{body}");

    let (owner, friend) = (Uuid::new_v4(), Uuid::new_v4());
    let id = upload(&app, owner, "report.pdf", b"x").await;
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::post()
                .uri(&format!("/api/v1/files/{id}/share"))
                .set_json(
                    json!({"shared_with": friend, "permission": "viewer", "shared_by": owner}),
                ),
            owner,
        ),
    )
    .await;
    assert_eq!(s, 201);
    let (s, body) = call(
        &app,
        as_user(TestRequest::get().uri("/api/v1/files/activity"), owner),
    )
    .await;
    assert_eq!(s, 200, "{body}");
    let items = body["items"].as_array().unwrap().clone();
    let kinds: Vec<_> = items
        .iter()
        .map(|i| i["type"].as_str().unwrap_or_default().to_string())
        .collect();
    assert!(kinds.contains(&"upload".to_string()), "{body}");
    assert!(kinds.contains(&"share".to_string()), "{body}");

    let (_, body) = call(
        &app,
        as_user(
            TestRequest::get().uri("/api/v1/files/activity?limit=1"),
            owner,
        ),
    )
    .await;
    assert_eq!(body["items"].as_array().unwrap().len(), 1);
}

#[actix_rt::test]
#[ignore = "FS-06: no file-type validation; active content (text/html, image/svg+xml) is stored with the client-declared MIME type"]
async fn finding_fs06_active_content_types_are_rejected_or_neutralised() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let (s, body) = call(
        &app,
        upload_req(
            Some(Uuid::new_v4()),
            &[(
                "file",
                Some("x.html"),
                Some("text/html"),
                b"<script>alert(1)</script>",
            )],
        ),
    )
    .await;
    assert!(
        s == 415 || body["file"]["mime_type"] != "text/html",
        "{s}: {body}"
    );
}

#[actix_rt::test]
#[ignore = "FS-12: trashed files remain downloadable/renamable/shareable until restored"]
async fn finding_fs12_trashed_file_is_read_only() {
    let ctx = Ctx::new().await;
    let app = ctx.app().await;
    let owner = Uuid::new_v4();
    let id = upload(&app, owner, "a.txt", b"x").await;
    call(
        &app,
        as_user(
            TestRequest::post().uri(&format!("/api/v1/files/{id}/trash")),
            owner,
        ),
    )
    .await;
    let (s, _) = call(
        &app,
        as_user(
            TestRequest::get().uri(&format!("/api/v1/files/{id}/download")),
            owner,
        ),
    )
    .await;
    assert_ne!(s, 200, "trashed file still downloadable");
}
