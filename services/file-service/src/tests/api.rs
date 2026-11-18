use std::collections::HashSet;
use std::sync::{Arc, Mutex};

use actix_web::test::{self, TestRequest};
use actix_web::web;
use chrono::{Duration, Utc};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::config::AppConfig;
use crate::events::EventPublisher;
use crate::metadata::MetadataClient;
use crate::models::{FileMetadata, FileShare, Folder, SharePermission};
use crate::storage::S3Client;
use crate::test_support::{multipart, start_redis, FakeAws, Part, BUCKET, TOPIC};

const FAIL_TOPIC: &str = "arn:aws:sns:us-east-1:000000000000:file-events-v2";

struct Ctx {
    aws: FakeAws,
    flags: Arc<Mutex<HashSet<String>>>,
    cfg: web::Data<AppConfig>,
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    redis: web::Data<redis::aio::ConnectionManager>,
}

async fn ctx_with(f: impl FnOnce(&mut AppConfig), broken_redis: bool) -> Ctx {
    let aws = FakeAws::start();
    let mut cfg = aws.config();
    f(&mut cfg);
    let flags: Arc<Mutex<HashSet<String>>> = Arc::default();
    let url = start_redis(flags.clone(), broken_redis);
    let redis = redis::aio::ConnectionManager::new(redis::Client::open(url).unwrap())
        .await
        .unwrap();
    let fail_topic = cfg.sns.share_event_always_fail.then_some(FAIL_TOPIC);
    let events = aws.events(cfg.sns.topic_arn.as_deref(), fail_topic);
    Ctx {
        s3: web::Data::new(aws.s3()),
        meta: web::Data::new(aws.meta()),
        events: web::Data::new(events),
        redis: web::Data::new(redis),
        cfg: web::Data::new(cfg),
        flags,
        aws,
    }
}

async fn ctx() -> Ctx {
    ctx_with(|_| {}, false).await
}

macro_rules! app {
    ($c:expr) => {
        test::init_service(
            actix_web::App::new()
                .wrap(crate::middleware::RequestId)
                .app_data($c.cfg.clone())
                .app_data($c.s3.clone())
                .app_data($c.meta.clone())
                .app_data($c.events.clone())
                .app_data($c.redis.clone())
                .configure(crate::configure_routes),
        )
        .await
    };
}

macro_rules! send {
    ($app:expr, $req:expr) => {{
        let resp = test::call_service(&$app, $req.to_request()).await;
        let status = resp.status().as_u16();
        let body = test::read_body(resp).await;
        let json: Value = serde_json::from_slice(&body).unwrap_or(Value::Null);
        (status, json)
    }};
}

fn file_meta(owner: Uuid, name: &str, age_mins: i64) -> FileMetadata {
    let id = Uuid::new_v4();
    let ts = Utc::now() - Duration::minutes(age_mins);
    FileMetadata {
        id,
        name: name.into(),
        mime_type: "text/plain".into(),
        size_bytes: 3,
        s3_key: format!("files/{owner}/{id}"),
        folder_id: None,
        owner_id: owner,
        version: 1,
        is_trashed: false,
        created_at: ts,
        updated_at: ts,
    }
}

fn share(file_id: Uuid, with: Uuid, by: Uuid, age_mins: i64) -> FileShare {
    FileShare {
        id: Uuid::new_v4(),
        file_id,
        shared_with: with,
        permission: SharePermission::Viewer,
        shared_by: by,
        created_at: Utc::now() - Duration::minutes(age_mins),
    }
}

fn upload_req(user: Option<&str>, parts: &[Part]) -> TestRequest {
    let (ct, body) = multipart(parts);
    let mut req = TestRequest::post()
        .uri("/api/v1/files/upload")
        .insert_header(("content-type", ct))
        .set_payload(body);
    if let Some(u) = user {
        req = req.insert_header(("X-User-ID", u));
    }
    req
}

fn file_part(data: &[u8]) -> Part<'_> {
    ("file", Some("notes.txt"), Some("text/plain"), data)
}

#[actix_rt::test]
async fn health_metrics_and_request_id_middleware() {
    let c = ctx().await;
    let app = app!(c);
    let resp = test::call_service(
        &app,
        TestRequest::get()
            .uri("/health")
            .insert_header(("x-request-id", "req-123"))
            .to_request(),
    )
    .await;
    assert_eq!(resp.status(), 200);

    let resp = test::call_service(&app, TestRequest::get().uri("/nope").to_request()).await;
    assert_eq!(resp.status(), 404);

    let body =
        test::call_and_read_body(&app, TestRequest::get().uri("/metrics").to_request()).await;
    let text = String::from_utf8_lossy(&body);
    assert!(text.contains("/health"), "{text}");
    assert!(text.contains("unmatched"), "{text}");
}

#[actix_rt::test]
async fn upload_success_persists_object_metadata_version_and_event() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4();
    let (status, body) = send!(
        app,
        upload_req(
            Some(&owner.to_string()),
            &[
                file_part(b"hello"),
                ("folder_id", None, None, folder.to_string().as_bytes()),
                ("ignored", None, None, b"x"),
            ],
        )
    );
    assert_eq!(status, 201, "{body}");
    let file = &body["file"];
    assert_eq!(file["name"], "notes.txt");
    assert_eq!(file["mime_type"], "text/plain");
    assert_eq!(file["size_bytes"], 5);
    assert_eq!(file["owner_id"], owner.to_string());
    assert_eq!(file["folder_id"], folder.to_string());
    let key = file["s3_key"].as_str().unwrap().to_string();
    assert_eq!(
        c.aws.st().objects.get(&(BUCKET.to_string(), key)).unwrap(),
        b"hello"
    );
    assert_eq!(c.aws.table("files").len(), 1);
    assert_eq!(c.aws.table("versions").len(), 1);
    let published = c.aws.st().published.clone();
    assert_eq!(published.len(), 1);
    assert_eq!(published[0]["TopicArn"], TOPIC);
    assert!(published[0]["Message"].contains("file_uploaded"));
}

#[actix_rt::test]
async fn upload_owner_from_form_field_and_blank_folder() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let (status, body) = send!(
        app,
        upload_req(
            None,
            &[
                ("owner_id", None, None, owner.to_string().as_bytes()),
                ("folder_id", None, None, b""),
                ("file", None, None, b"abc"),
            ],
        )
    );
    assert_eq!(status, 201, "{body}");
    assert_eq!(body["file"]["owner_id"], owner.to_string());
    assert_eq!(body["file"]["folder_id"], Value::Null);
    assert_eq!(body["file"]["name"], "unnamed");
    assert_eq!(body["file"]["mime_type"], "application/octet-stream");
}

#[actix_rt::test]
async fn upload_validation_errors() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4().to_string();
    let cases: Vec<(Option<&str>, Vec<Part>, u16)> = vec![
        (None, vec![file_part(b"x")], 400),
        (Some(&owner), vec![], 400),
        (Some(&owner), vec![file_part(b"")], 400),
        (
            None,
            vec![("owner_id", None, None, b"not-a-uuid"), file_part(b"x")],
            400,
        ),
        (
            Some(&owner),
            vec![("folder_id", None, None, b"bad"), file_part(b"x")],
            400,
        ),
        (Some(&owner), vec![file_part(&[b'a'; 2048])], 413),
    ];
    for (user, parts, expected) in cases {
        let (status, body) = send!(app, upload_req(user, &parts));
        assert_eq!(status, expected, "{body}");
    }
    let (status, _) = send!(
        app,
        TestRequest::post()
            .uri("/api/v1/files/upload")
            .insert_header(("X-User-ID", owner.as_str()))
            .insert_header(("content-type", "multipart/form-data; boundary=zz"))
            .set_payload("garbage")
    );
    assert_eq!(status, 400);
    assert!(c.aws.table("files").is_empty());
}

#[actix_rt::test]
async fn upload_always_fail_switch_returns_storage_error_and_alerts() {
    let c = ctx_with(|cfg| cfg.server.upload_always_fail = true, false).await;
    let app = app!(c);
    let owner = Uuid::new_v4().to_string();
    let (status, body) = send!(
        app,
        upload_req(Some(&owner), &[file_part(b"hi")])
            .insert_header(("X-User-Email", " alice@example.com "))
    );
    assert_eq!(status, 500);
    assert_eq!(body["error"], "storage_error");
    assert!(c.aws.table("files").is_empty());
    let alerts = c.aws.wait_alerts(1).await;
    assert_eq!(alerts.len(), 1);
    assert_eq!(alerts[0].0.as_deref(), Some("s3cr3t"));
    assert!(alerts[0].1.to_string().contains("alice@example.com"));
}

#[actix_rt::test]
async fn upload_chaos_flag_redirects_and_rejected_alert_is_tolerated() {
    let c = ctx().await;
    c.flags
        .lock()
        .unwrap()
        .insert("chaos:file-service:upload_s3_error".into());
    c.aws.st().alert_status = 500;
    let app = app!(c);
    let (status, _) = send!(
        app,
        upload_req(Some(&Uuid::new_v4().to_string()), &[file_part(b"hi")])
    );
    assert_eq!(status, 500);
    assert_eq!(c.aws.wait_alerts(1).await.len(), 1);
}

#[actix_rt::test]
async fn upload_ignores_redis_errors_when_checking_chaos_flag() {
    let c = ctx_with(|_| {}, true).await;
    let app = app!(c);
    let (status, body) = send!(
        app,
        upload_req(Some(&Uuid::new_v4().to_string()), &[file_part(b"hi")])
    );
    assert_eq!(status, 201, "{body}");
}

#[actix_rt::test]
async fn upload_metadata_and_event_failures() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4().to_string();
    c.aws.fail("sns");
    let (status, _) = send!(app, upload_req(Some(&owner), &[file_part(b"hi")]));
    assert_eq!(status, 201);
    c.aws.fail("PutItem:versions");
    let (status, body) = send!(app, upload_req(Some(&owner), &[file_part(b"hi")]));
    assert_eq!(status, 500);
    assert_eq!(body["error"], "metadata_error");
    c.aws.fail("PutItem:files");
    let (status, _) = send!(app, upload_req(Some(&owner), &[file_part(b"hi")]));
    assert_eq!(status, 500);
}

#[actix_rt::test]
async fn get_file_metadata_variants() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let f = file_meta(owner, "a.txt", 0);
    c.meta.put_file(&f).await.unwrap();
    c.meta
        .put_share(&share(f.id, Uuid::new_v4(), owner, 0))
        .await
        .unwrap();
    let uri = format!("/api/v1/files/{}", f.id);
    let (status, body) = send!(app, TestRequest::get().uri(&uri));
    assert_eq!(status, 200);
    assert_eq!(body["shared_with"].as_array().unwrap().len(), 1);
    assert_eq!(body["name"], "a.txt");

    c.aws.fail("Scan:shares");
    let (status, body) = send!(app, TestRequest::get().uri(&uri));
    assert_eq!(status, 200);
    assert!(body["shared_with"].as_array().unwrap().is_empty());

    let (status, body) = send!(
        app,
        TestRequest::get().uri(&format!("/api/v1/files/{}", Uuid::new_v4()))
    );
    assert_eq!(status, 404);
    assert_eq!(body["error"], "file_not_found");
    let (status, _) = send!(app, TestRequest::get().uri("/api/v1/files/not-a-uuid"));
    assert_eq!(status, 400);
}

#[actix_rt::test]
async fn list_files_filters_and_paginates() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4();
    let mut in_folder = file_meta(owner, "in-folder", 1);
    in_folder.folder_id = Some(folder);
    let mut trashed = file_meta(owner, "trashed", 2);
    trashed.is_trashed = true;
    for f in [
        &in_folder,
        &trashed,
        &file_meta(owner, "root", 3),
        &file_meta(Uuid::new_v4(), "other", 0),
    ] {
        c.meta.put_file(f).await.unwrap();
    }

    let (status, body) = send!(
        app,
        TestRequest::get()
            .uri("/api/v1/files")
            .insert_header(("X-User-ID", owner.to_string()))
    );
    assert_eq!(status, 200);
    assert_eq!(body["total"], 2);
    assert_eq!(body["page"], 1);
    assert_eq!(body["page_size"], 50);

    let (_, body) = send!(
        app,
        TestRequest::get().uri(&format!(
            "/api/v1/files?owner_id={owner}&include_trashed=true&page=2&page_size=1"
        ))
    );
    assert_eq!(body["total"], 3);
    assert_eq!(body["files"].as_array().unwrap().len(), 1);

    let (_, body) = send!(
        app,
        TestRequest::get().uri(&format!("/api/v1/files?folder_id={folder}&page_size=1000"))
    );
    assert_eq!(body["page_size"], 100);
    assert_eq!(body["files"][0]["name"], "in-folder");

    let (_, body) = send!(
        app,
        TestRequest::get()
            .uri(&format!("/api/v1/files?owner_id={}", Uuid::new_v4()))
            .insert_header(("X-User-ID", "garbage"))
    );
    assert_eq!(body["total"], 0);

    c.aws.fail("Scan:files");
    let (status, _) = send!(app, TestRequest::get().uri("/api/v1/files"));
    assert_eq!(status, 500);
}

#[actix_rt::test]
async fn list_files_seeds_demo_docs_for_empty_owner() {
    let c = ctx_with(|cfg| cfg.server.seed_demo_docs = true, false).await;
    let app = app!(c);
    let owner = Uuid::new_v4().to_string();
    let req = || {
        TestRequest::get()
            .uri("/api/v1/files")
            .insert_header(("X-User-ID", owner.as_str()))
    };
    let (status, body) = send!(app, req());
    assert_eq!(status, 200);
    let seeded = body["total"].as_u64().unwrap();
    assert!(seeded > 0);
    assert_eq!(c.aws.st().objects.len() as u64, seeded);
    let (_, body) = send!(app, req());
    assert_eq!(body["total"].as_u64().unwrap(), seeded);

    let (status, body) = send!(app, TestRequest::get().uri("/api/v1/files"));
    assert_eq!(status, 200, "{body}");
}

#[actix_rt::test]
async fn list_shared_files_dedupes_and_skips_trashed_or_missing() {
    let c = ctx().await;
    let app = app!(c);
    let me = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let a = file_meta(owner, "a", 0);
    let b = file_meta(owner, "b", 1);
    let mut t = file_meta(owner, "t", 2);
    t.is_trashed = true;
    for f in [&a, &b, &t] {
        c.meta.put_file(f).await.unwrap();
    }
    for s in [
        share(a.id, me, owner, 0),
        share(a.id, me, owner, 1),
        share(b.id, me, owner, 0),
        share(t.id, me, owner, 0),
        share(Uuid::new_v4(), me, owner, 0),
    ] {
        c.meta.put_share(&s).await.unwrap();
    }
    let (status, _) = send!(app, TestRequest::get().uri("/api/v1/files/shared"));
    assert_eq!(status, 400);
    let (status, body) = send!(
        app,
        TestRequest::get()
            .uri("/api/v1/files/shared?page_size=1&page=2")
            .insert_header(("X-User-ID", me.to_string()))
    );
    assert_eq!(status, 200);
    assert_eq!(body["total"], 2);
    assert_eq!(body["files"].as_array().unwrap().len(), 1);

    c.aws.fail("Scan:shares");
    let (status, _) = send!(
        app,
        TestRequest::get()
            .uri("/api/v1/files/shared")
            .insert_header(("X-User-ID", me.to_string()))
    );
    assert_eq!(status, 500);
}

#[actix_rt::test]
async fn list_trashed_across_scan_pages() {
    let c = ctx().await;
    c.aws.st().page_size = Some(1);
    let app = app!(c);
    let owner = Uuid::new_v4();
    for (name, age) in [("old", 10), ("new", 1)] {
        let mut f = file_meta(owner, name, age);
        f.is_trashed = true;
        c.meta.put_file(&f).await.unwrap();
    }
    c.meta.put_file(&file_meta(owner, "live", 0)).await.unwrap();
    let (status, body) = send!(
        app,
        TestRequest::get()
            .uri("/api/v1/files/trash?page_size=10")
            .insert_header(("X-User-ID", owner.to_string()))
    );
    assert_eq!(status, 200);
    assert_eq!(body["total"], 2);
    assert_eq!(body["files"][0]["name"], "new");
    let (_, body) = send!(app, TestRequest::get().uri("/api/v1/files/trash"));
    assert_eq!(body["total"], 2);
    c.aws.fail("Scan");
    let (status, _) = send!(app, TestRequest::get().uri("/api/v1/files/trash"));
    assert_eq!(status, 500);
}

#[actix_rt::test]
async fn delete_and_download_file() {
    let c = ctx().await;
    let app = app!(c);
    let f = file_meta(Uuid::new_v4(), "a", 0);
    c.meta.put_file(&f).await.unwrap();
    c.s3.upload_object(&f.s3_key, b"abc".to_vec().into(), "text/plain")
        .await
        .unwrap();

    let (status, body) = send!(
        app,
        TestRequest::get().uri(&format!("/api/v1/files/{}/download", f.id))
    );
    assert_eq!(status, 200);
    assert_eq!(body["expires_in_secs"], 3600);
    assert!(body["url"].as_str().unwrap().contains(&f.s3_key));

    let (status, _) = send!(
        app,
        TestRequest::delete().uri(&format!("/api/v1/files/{}", f.id))
    );
    assert_eq!(status, 204);
    assert!(c.aws.st().objects.is_empty());
    assert!(c.aws.table("files").is_empty());
    assert!(c.aws.st().published[0]["Message"].contains("file_deleted"));

    for uri in [
        format!("/api/v1/files/{}", f.id),
        format!("/api/v1/files/{}/download", f.id),
    ] {
        let req = if uri.ends_with("download") {
            TestRequest::get()
        } else {
            TestRequest::delete()
        };
        let (status, _) = send!(app, req.uri(&uri));
        assert_eq!(status, 404);
    }
    for req in [
        TestRequest::delete().uri("/api/v1/files/bad"),
        TestRequest::get().uri("/api/v1/files/bad/download"),
    ] {
        let (status, _) = send!(app, req);
        assert_eq!(status, 400);
    }

    let g = file_meta(Uuid::new_v4(), "g", 0);
    c.meta.put_file(&g).await.unwrap();
    c.aws.fail("s3:DELETE");
    let (status, body) = send!(
        app,
        TestRequest::delete().uri(&format!("/api/v1/files/{}", g.id))
    );
    assert_eq!(status, 500);
    assert_eq!(body["error"], "storage_error");
}

#[actix_rt::test]
async fn move_rename_trash_restore_and_versions() {
    let c = ctx().await;
    let app = app!(c);
    let f = file_meta(Uuid::new_v4(), "a", 0);
    c.meta.put_file(&f).await.unwrap();
    let base = format!("/api/v1/files/{}", f.id);
    let missing = format!("/api/v1/files/{}", Uuid::new_v4());
    let folder = Uuid::new_v4();

    let (status, body) = send!(
        app,
        TestRequest::put()
            .uri(&format!("{base}/move"))
            .set_json(json!({"folder_id": folder}))
    );
    assert_eq!(status, 200, "{body}");
    assert_eq!(body["folder_id"], folder.to_string());
    let (_, body) = send!(
        app,
        TestRequest::put()
            .uri(&format!("{base}/move"))
            .set_json(json!({"folder_id": null}))
    );
    assert_eq!(body["folder_id"], Value::Null);

    let (status, body) = send!(
        app,
        TestRequest::patch()
            .uri(&format!("{base}/rename"))
            .set_json(json!({"name": "  renamed.txt "}))
    );
    assert_eq!(status, 200, "{body}");
    assert!(body["name"].as_str().unwrap().contains("renamed.txt"));
    let (status, _) = send!(
        app,
        TestRequest::patch()
            .uri(&format!("{base}/rename"))
            .set_json(json!({"name": "   "}))
    );
    assert_eq!(status, 400);

    let (status, body) = send!(app, TestRequest::post().uri(&format!("{base}/trash")));
    assert_eq!(status, 200);
    assert_eq!(body["is_trashed"], true);
    let (status, body) = send!(app, TestRequest::post().uri(&format!("{base}/restore")));
    assert_eq!(status, 200);
    assert_eq!(body["is_trashed"], false);

    let (status, body) = send!(app, TestRequest::get().uri(&format!("{base}/versions")));
    assert_eq!(status, 200);
    assert!(body["versions"].as_array().unwrap().is_empty());

    for (method, suffix, payload) in [
        ("PUT", "move", Some(json!({"folder_id": null}))),
        ("PATCH", "rename", Some(json!({"name": "x"}))),
        ("POST", "trash", None),
        ("POST", "restore", None),
    ] {
        for (uri, expected) in [
            (format!("{missing}/{suffix}"), 404),
            (format!("/api/v1/files/bad/{suffix}"), 400),
        ] {
            let mut req = TestRequest::default()
                .method(method.parse().unwrap())
                .uri(&uri);
            if let Some(p) = &payload {
                req = req.set_json(p);
            }
            let (status, body) = send!(app, req);
            assert_eq!(status, expected, "{method} {uri} {body}");
        }
    }
    let (status, _) = send!(app, TestRequest::get().uri("/api/v1/files/bad/versions"));
    assert_eq!(status, 400);

    c.aws.fail("sns");
    let (status, _) = send!(app, TestRequest::post().uri(&format!("{base}/trash")));
    assert_eq!(status, 200);
    c.aws.fail("UpdateItem");
    c.aws.fail("Query");
    let (status, _) = send!(
        app,
        TestRequest::patch()
            .uri(&format!("{base}/rename"))
            .set_json(json!({"name": "y"}))
    );
    assert_eq!(status, 500);
    let (status, _) = send!(app, TestRequest::get().uri(&format!("{base}/versions")));
    assert_eq!(status, 500);
}

fn share_req(file: &str, body: Value) -> TestRequest {
    TestRequest::post()
        .uri(&format!("/api/v1/files/{file}/share"))
        .set_json(body)
}

#[actix_rt::test]
async fn share_file_new_reshare_and_permission_change() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let f = file_meta(owner, "doc", 0);
    c.meta.put_file(&f).await.unwrap();
    let id = f.id.to_string();
    let bob = Uuid::new_v4();
    let body = json!({"shared_with": bob, "permission": "viewer", "shared_by": owner});

    let (status, resp) = send!(app, share_req(&id, body.clone()));
    assert_eq!(status, 201, "{resp}");
    assert_eq!(resp["share"]["permission"], "viewer");
    assert_eq!(c.aws.st().published.len(), 1);
    assert!(c.aws.st().published[0]["Message"].contains("file_shared"));

    let (status, resp) = send!(app, share_req(&id, body.clone()));
    assert_eq!(status, 200);
    assert_eq!(resp["share"]["permission"], "viewer");

    let (status, resp) = send!(
        app,
        share_req(
            &id,
            json!({"shared_with": bob, "permission": "editor", "shared_by": owner})
        )
    );
    assert_eq!(status, 200);
    assert_eq!(resp["share"]["permission"], "editor");
    assert_eq!(c.aws.table("shares").len(), 1);
    assert_eq!(c.aws.st().published.len(), 1);

    for (file, payload, expected) in [
        (
            id.clone(),
            json!({"permission": "viewer", "shared_by": owner}),
            400,
        ),
        (
            id.clone(),
            json!({"shared_with_email": "  ", "permission": "viewer", "shared_by": owner}),
            400,
        ),
        (
            id.clone(),
            json!({"shared_with_email": "x@example.com", "permission": "viewer", "shared_by": owner}),
            400,
        ),
        (Uuid::new_v4().to_string(), body.clone(), 404),
        ("bad".to_string(), body.clone(), 400),
    ] {
        let (status, resp) = send!(app, share_req(&file, payload));
        assert_eq!(status, expected, "{resp}");
    }
}

#[actix_rt::test]
async fn share_file_publish_failure_is_fire_and_forget_without_switch() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let f = file_meta(owner, "doc", 0);
    c.meta.put_file(&f).await.unwrap();
    c.aws.fail("sns");
    let (status, _) = send!(
        app,
        share_req(
            &f.id.to_string(),
            json!({"shared_with": Uuid::new_v4(), "permission": "viewer", "shared_by": owner})
        )
        .insert_header(("X-User-Email", "owner@example.com"))
    );
    assert_eq!(status, 201);
    assert_eq!(c.aws.table("shares").len(), 1);
    let alerts = c.aws.wait_alerts(1).await;
    assert!(alerts[0].1.to_string().contains("owner@example.com"));

    c.aws.fail("PutItem:shares");
    let (status, _) = send!(
        app,
        share_req(
            &f.id.to_string(),
            json!({"shared_with": Uuid::new_v4(), "permission": "viewer", "shared_by": owner})
        )
    );
    assert_eq!(status, 500);
}

#[actix_rt::test]
async fn share_event_always_fail_switch_surfaces_error() {
    let c = ctx_with(|cfg| cfg.sns.share_event_always_fail = true, false).await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let f = file_meta(owner, "doc", 0);
    c.meta.put_file(&f).await.unwrap();
    let id = f.id.to_string();

    let (status, body) = send!(
        app,
        share_req(
            &id,
            json!({"shared_with_email": "Unknown@Example.com", "permission": "viewer", "shared_by": owner})
        )
    );
    assert_eq!(status, 500);
    assert_eq!(body["error"], "event_error");
    assert!(c.aws.table("shares").is_empty());

    let bob = Uuid::new_v4();
    c.meta.put_share(&share(f.id, bob, owner, 0)).await.unwrap();
    let (status, _) = send!(
        app,
        share_req(
            &id,
            json!({"shared_with": bob, "permission": "viewer", "shared_by": owner})
        )
    );
    assert_eq!(status, 500);
    let (status, _) = send!(
        app,
        share_req(
            &id,
            json!({"shared_with": bob, "permission": "editor", "shared_by": owner})
        )
    );
    assert_eq!(status, 200);
    assert_eq!(c.aws.wait_alerts(2).await.len(), 2);
}

#[actix_rt::test]
async fn remove_share_variants() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let bob = Uuid::new_v4();
    let f = file_meta(owner, "doc", 0);
    c.meta.put_file(&f).await.unwrap();
    c.meta.put_share(&share(f.id, bob, owner, 0)).await.unwrap();
    let uri = |file: &str, user: &str| format!("/api/v1/files/{file}/share/{user}");
    let id = f.id.to_string();

    let (status, _) = send!(app, TestRequest::delete().uri(&uri(&id, &bob.to_string())));
    assert_eq!(status, 204);
    assert!(c.aws.table("shares").is_empty());
    for (file, user, expected) in [
        (id.clone(), bob.to_string(), 404),
        ("bad".into(), bob.to_string(), 400),
        (id.clone(), "bad".into(), 400),
        (Uuid::new_v4().to_string(), bob.to_string(), 404),
    ] {
        let (status, _) = send!(app, TestRequest::delete().uri(&uri(&file, &user)));
        assert_eq!(status, expected, "{file} {user}");
    }
}

#[actix_rt::test]
async fn folder_crud() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let (status, root) = send!(
        app,
        TestRequest::post()
            .uri("/api/v1/folders")
            .set_json(json!({"name": "Root", "owner_id": owner}))
    );
    assert_eq!(status, 201, "{root}");
    let root_id = root["id"].as_str().unwrap().to_string();
    let (status, child) = send!(
        app,
        TestRequest::post()
            .uri("/api/v1/folders")
            .set_json(json!({"name": "Child", "owner_id": owner, "parent_id": root_id}))
    );
    assert_eq!(status, 201);
    let child_id = child["id"].as_str().unwrap().to_string();

    let (status, body) = send!(
        app,
        TestRequest::get().uri(&format!("/api/v1/folders/{root_id}"))
    );
    assert_eq!(status, 200);
    assert_eq!(body["name"], "Root");

    let (_, body) = send!(
        app,
        TestRequest::get()
            .uri("/api/v1/folders")
            .insert_header(("X-User-ID", owner.to_string()))
    );
    assert_eq!(body["folders"].as_array().unwrap().len(), 1);
    let (_, body) = send!(
        app,
        TestRequest::get().uri(&format!(
            "/api/v1/folders?parent_id={root_id}&owner_id={owner}"
        ))
    );
    assert_eq!(body["folders"][0]["name"], "Child");

    let new_parent = Uuid::new_v4();
    let (status, body) = send!(
        app,
        TestRequest::put()
            .uri(&format!("/api/v1/folders/{child_id}"))
            .set_json(json!({"name": "Renamed", "parent_id": new_parent}))
    );
    assert_eq!(status, 200, "{body}");
    assert_eq!(body["name"], "Renamed");
    assert_eq!(body["parent_id"], new_parent.to_string());
    let (status, body) = send!(
        app,
        TestRequest::put()
            .uri(&format!("/api/v1/folders/{child_id}"))
            .set_json(json!({}))
    );
    assert_eq!(status, 200, "{body}");

    let (status, _) = send!(
        app,
        TestRequest::delete().uri(&format!("/api/v1/folders/{child_id}"))
    );
    assert_eq!(status, 204);

    let missing = Uuid::new_v4();
    for (req, expected) in [
        (
            TestRequest::get().uri(&format!("/api/v1/folders/{missing}")),
            404,
        ),
        (TestRequest::get().uri("/api/v1/folders/bad"), 400),
        (
            TestRequest::put()
                .uri(&format!("/api/v1/folders/{missing}"))
                .set_json(json!({"name": "x"})),
            404,
        ),
        (
            TestRequest::put()
                .uri("/api/v1/folders/bad")
                .set_json(json!({"name": "x"})),
            400,
        ),
        (TestRequest::delete().uri("/api/v1/folders/bad"), 400),
    ] {
        let (status, body) = send!(app, req);
        assert_eq!(status, expected, "{body}");
    }

    c.aws.fail("Scan:folders");
    c.aws.fail("PutItem:folders");
    let (status, _) = send!(app, TestRequest::get().uri("/api/v1/folders"));
    assert_eq!(status, 500);
    let (status, _) = send!(
        app,
        TestRequest::post()
            .uri("/api/v1/folders")
            .set_json(json!({"name": "x", "owner_id": owner}))
    );
    assert_eq!(status, 500);
}

#[actix_rt::test]
async fn list_activity_merges_uploads_and_shares() {
    let c = ctx().await;
    let app = app!(c);
    let owner = Uuid::new_v4();
    let f = file_meta(owner, "report.pdf", 5);
    c.meta.put_file(&f).await.unwrap();
    c.meta
        .put_share(&share(f.id, Uuid::new_v4(), owner, 1))
        .await
        .unwrap();
    c.meta
        .put_share(&share(Uuid::new_v4(), Uuid::new_v4(), owner, 10))
        .await
        .unwrap();

    let (status, _) = send!(app, TestRequest::get().uri("/api/v1/files/activity"));
    assert_eq!(status, 400);
    let req = |q: &str| {
        TestRequest::get()
            .uri(&format!("/api/v1/files/activity{q}"))
            .insert_header(("X-User-ID", owner.to_string()))
    };
    let (status, body) = send!(app, req(""));
    assert_eq!(status, 200);
    let items = body["items"].as_array().unwrap();
    assert_eq!(items.len(), 3);
    assert_eq!(items[0]["type"], "share");
    assert_eq!(items[0]["description"], "Shared report.pdf");
    assert_eq!(items[1]["type"], "upload");
    assert_eq!(items[2]["resource_name"], "a file");
    let (_, body) = send!(app, req("?limit=1"));
    assert_eq!(body["items"].as_array().unwrap().len(), 1);

    c.aws.fail("Scan");
    let (status, body) = send!(app, req(""));
    assert_eq!(status, 200);
    assert!(body["items"].as_array().unwrap().is_empty());
}

#[actix_rt::test]
async fn folder_model_is_listed_by_owner() {
    let c = ctx().await;
    let owner = Uuid::new_v4();
    let now = Utc::now();
    c.meta
        .put_folder(&Folder {
            id: Uuid::new_v4(),
            name: "x".into(),
            parent_id: None,
            owner_id: owner,
            created_at: now,
            updated_at: now,
        })
        .await
        .unwrap();
    assert_eq!(
        c.meta.list_folders(None, Some(owner)).await.unwrap().len(),
        1
    );
}
