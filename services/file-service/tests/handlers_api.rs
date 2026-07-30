//! HTTP handlers driven directly with faked AWS/Redis boundaries.

mod common;

use actix_multipart::Multipart;
use actix_web::body::to_bytes;
use actix_web::http::header::{HeaderMap, HeaderName, HeaderValue};
use actix_web::http::StatusCode;
use actix_web::test::TestRequest;
use actix_web::{web, HttpRequest, HttpResponse};
use aws_smithy_runtime::client::http::test_util::ReplayEvent;
use bytes::Bytes;
use common::*;
use file_service::config::{AppConfig, ServerConfig, SnsConfig};
use file_service::errors::ServiceError;
use file_service::handlers;
use file_service::metadata::MetadataClient;
use file_service::models::{
    ActivityQuery, CreateFolderRequest, ListFilesQuery, ListFoldersQuery, MoveFileRequest,
    RenameFileRequest, ShareFileRequest, SharePermission, UpdateFolderRequest,
};
use serde_json::{json, Value};
use uuid::Uuid;

// -- helpers --

fn request_from(user_id: Option<&Uuid>) -> HttpRequest {
    let mut builder = TestRequest::default();
    if let Some(user_id) = user_id {
        builder = builder.insert_header(("X-User-ID", user_id.to_string()));
    }
    builder.to_http_request()
}

fn list_query(owner_id: Option<Uuid>) -> web::Query<ListFilesQuery> {
    web::Query(ListFilesQuery {
        folder_id: None,
        owner_id,
        page: None,
        page_size: None,
        include_trashed: None,
    })
}

async fn body_of(resp: HttpResponse) -> Value {
    let bytes = to_bytes(resp.into_body()).await.unwrap();
    serde_json::from_slice(&bytes).unwrap()
}

fn app_config(max_upload_bytes: u64) -> web::Data<AppConfig> {
    web::Data::new(AppConfig {
        server: ServerConfig {
            port: 8082,
            max_upload_bytes,
        },
        aws: aws_config_for_tests(),
        sns: SnsConfig { topic_arn: None },
    })
}

/// `(field name, filename, content type, contents)`
type Part<'a> = (&'a str, Option<&'a str>, Option<&'a str>, &'a str);

fn multipart_body(parts: &[Part<'_>]) -> Multipart {
    const BOUNDARY: &str = "otterworksboundary";
    let mut body = String::new();
    for (name, filename, content_type, contents) in parts {
        body.push_str(&format!("--{BOUNDARY}\r\n"));
        body.push_str(&format!("Content-Disposition: form-data; name=\"{name}\""));
        if let Some(filename) = filename {
            body.push_str(&format!("; filename=\"{filename}\""));
        }
        body.push_str("\r\n");
        if let Some(content_type) = content_type {
            body.push_str(&format!("Content-Type: {content_type}\r\n"));
        }
        body.push_str("\r\n");
        body.push_str(contents);
        body.push_str("\r\n");
    }
    body.push_str(&format!("--{BOUNDARY}--\r\n"));

    let mut headers = HeaderMap::new();
    headers.insert(
        HeaderName::from_static("content-type"),
        HeaderValue::from_static("multipart/form-data; boundary=otterworksboundary"),
    );
    Multipart::new(
        &headers,
        futures_util::stream::once(async move {
            Ok::<Bytes, actix_web::error::PayloadError>(Bytes::from(body))
        }),
    )
}

/// The five `web::Data` arguments every upload needs.
struct UploadDeps {
    s3: web::Data<file_service::storage::S3Client>,
    meta: web::Data<MetadataClient>,
    events: web::Data<file_service::events::EventPublisher>,
    redis: web::Data<redis::aio::ConnectionManager>,
    s3_http: aws_smithy_runtime::client::http::test_util::StaticReplayClient,
}

async fn upload_deps(
    s3_events: Vec<ReplayEvent>,
    dynamo_events: Vec<ReplayEvent>,
    chaos: bool,
) -> UploadDeps {
    let (s3, s3_http) = s3_client(s3_events);
    let (meta, _dynamo_http) = metadata_client(dynamo_events);
    UploadDeps {
        s3: web::Data::new(s3),
        meta: web::Data::new(meta),
        events: web::Data::new(silent_publisher().await),
        redis: web::Data::new(fake_redis(chaos).await),
        s3_http,
    }
}

// -- upload --

#[actix_web::test]
async fn upload_file_stores_the_blob_metadata_and_first_version() {
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4();
    let deps = upload_deps(
        vec![s3_ok("")],
        vec![dynamo_ok(json!({})), dynamo_ok(json!({}))],
        false,
    )
    .await;

    let resp = handlers::upload_file(
        request_from(Some(&owner)),
        deps.s3.clone(),
        deps.meta.clone(),
        deps.events.clone(),
        app_config(1024),
        deps.redis.clone(),
        multipart_body(&[
            ("file", Some("notes.txt"), Some("text/plain"), "hello world"),
            ("folder_id", None, None, &folder.to_string()),
            ("ignored", None, None, "whatever"),
        ]),
    )
    .await
    .expect("upload should succeed");

    assert_eq!(resp.status(), StatusCode::CREATED);
    let body = body_of(resp).await;
    assert_eq!(body["file"]["name"], "notes.txt");
    assert_eq!(body["file"]["mime_type"], "text/plain");
    assert_eq!(body["file"]["size_bytes"], 11);
    assert_eq!(body["file"]["owner_id"], owner.to_string());
    assert_eq!(body["file"]["folder_id"], folder.to_string());
    assert_eq!(body["file"]["version"], 1);

    let put = deps.s3_http.actual_requests().next().expect("one PUT");
    assert!(put.uri().contains(BUCKET), "{}", put.uri());
    assert_eq!(put.body().bytes(), Some(&b"hello world"[..]));
}

#[actix_web::test]
async fn upload_file_falls_back_to_the_owner_id_field() {
    let owner = Uuid::new_v4();
    let deps = upload_deps(
        vec![s3_ok("")],
        vec![dynamo_ok(json!({})), dynamo_ok(json!({}))],
        false,
    )
    .await;

    let resp = handlers::upload_file(
        request_from(None),
        deps.s3.clone(),
        deps.meta.clone(),
        deps.events.clone(),
        app_config(1024),
        deps.redis.clone(),
        multipart_body(&[
            ("owner_id", None, None, &owner.to_string()),
            ("folder_id", None, None, "   "),
            ("file", Some("a.txt"), None, "hi"),
        ]),
    )
    .await
    .unwrap();

    let body = body_of(resp).await;
    assert_eq!(body["file"]["owner_id"], owner.to_string());
    assert_eq!(
        body["file"]["folder_id"],
        Value::Null,
        "blank folder ignored"
    );
    assert_eq!(
        body["file"]["mime_type"], "application/octet-stream",
        "default content type"
    );
}

#[actix_web::test]
async fn upload_file_requires_an_owner() {
    let deps = upload_deps(vec![], vec![], false).await;

    let err = handlers::upload_file(
        request_from(None),
        deps.s3.clone(),
        deps.meta.clone(),
        deps.events.clone(),
        app_config(1024),
        deps.redis.clone(),
        multipart_body(&[("file", Some("a.txt"), None, "hi")]),
    )
    .await
    .expect_err("no owner anywhere");

    assert_eq!(err.to_string(), "Bad request: owner_id is required");
}

#[actix_web::test]
async fn upload_file_requires_a_file_part() {
    let owner = Uuid::new_v4();
    let deps = upload_deps(vec![], vec![], false).await;

    let err = handlers::upload_file(
        request_from(Some(&owner)),
        deps.s3.clone(),
        deps.meta.clone(),
        deps.events.clone(),
        app_config(1024),
        deps.redis.clone(),
        multipart_body(&[("folder_id", None, None, "")]),
    )
    .await
    .expect_err("nothing to store");

    assert_eq!(err.to_string(), "Bad request: file field is required");
}

#[actix_web::test]
async fn upload_file_rejects_an_unparseable_owner_id() {
    let deps = upload_deps(vec![], vec![], false).await;

    let err = handlers::upload_file(
        request_from(None),
        deps.s3.clone(),
        deps.meta.clone(),
        deps.events.clone(),
        app_config(1024),
        deps.redis.clone(),
        multipart_body(&[("owner_id", None, None, "not-a-uuid")]),
    )
    .await
    .expect_err("bad uuid");

    assert!(err.to_string().starts_with("Bad request: invalid owner_id"));
}

#[actix_web::test]
async fn upload_file_rejects_an_unparseable_folder_id() {
    let owner = Uuid::new_v4();
    let deps = upload_deps(vec![], vec![], false).await;

    let err = handlers::upload_file(
        request_from(Some(&owner)),
        deps.s3.clone(),
        deps.meta.clone(),
        deps.events.clone(),
        app_config(1024),
        deps.redis.clone(),
        multipart_body(&[("folder_id", None, None, "not-a-uuid")]),
    )
    .await
    .expect_err("bad uuid");

    assert!(err
        .to_string()
        .starts_with("Bad request: invalid folder_id"));
}

#[actix_web::test]
async fn upload_file_enforces_the_configured_size_limit() {
    let owner = Uuid::new_v4();
    let deps = upload_deps(vec![], vec![], false).await;

    let err = handlers::upload_file(
        request_from(Some(&owner)),
        deps.s3.clone(),
        deps.meta.clone(),
        deps.events.clone(),
        app_config(4),
        deps.redis.clone(),
        multipart_body(&[("file", Some("a.txt"), None, "far too long")]),
    )
    .await
    .expect_err("over the limit");

    match err {
        ServiceError::FileTooLarge {
            max_bytes,
            actual_bytes,
        } => {
            assert_eq!(max_bytes, 4);
            assert!(actual_bytes > 4);
        }
        other => panic!("expected FileTooLarge, got {other:?}"),
    }
}

#[actix_web::test]
async fn upload_file_redirects_to_a_missing_bucket_when_the_chaos_flag_is_set() {
    let owner = Uuid::new_v4();
    let deps = upload_deps(vec![s3_err(404, "NoSuchBucket")], vec![], true).await;

    let err = handlers::upload_file(
        request_from(Some(&owner)),
        deps.s3.clone(),
        deps.meta.clone(),
        deps.events.clone(),
        app_config(1024),
        deps.redis.clone(),
        multipart_body(&[("file", Some("a.txt"), None, "hi")]),
    )
    .await
    .expect_err("the chaos bucket does not exist");

    assert!(matches!(err, ServiceError::S3Error(_)), "{err:?}");
    let put = deps.s3_http.actual_requests().next().expect("one PUT");
    assert!(
        put.uri().contains("otterworks-files-chaos-nonexistent"),
        "{}",
        put.uri()
    );
}

// -- read paths --

#[actix_web::test]
async fn get_file_metadata_includes_the_share_list() {
    let (id, owner, viewer) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, _http) = metadata_client(vec![
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
        scan_page(
            vec![share_item(&Uuid::new_v4(), &id, &viewer, &owner, "viewer")],
            None,
        ),
    ]);

    let resp = handlers::get_file_metadata(web::Data::new(meta), web::Path::from(id.to_string()))
        .await
        .unwrap();

    assert_eq!(resp.status(), StatusCode::OK);
    let body = body_of(resp).await;
    assert_eq!(body["name"], "a.txt");
    assert_eq!(body["shared_with"][0]["shared_with"], viewer.to_string());
}

#[actix_web::test]
async fn get_file_metadata_tolerates_a_failing_share_lookup() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _http) = metadata_client(vec![
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
        dynamo_err("ValidationException"),
    ]);

    let resp = handlers::get_file_metadata(web::Data::new(meta), web::Path::from(id.to_string()))
        .await
        .unwrap();

    assert_eq!(body_of(resp).await["shared_with"], json!([]));
}

#[actix_web::test]
async fn get_file_metadata_rejects_a_malformed_id() {
    let (meta, _http) = metadata_client(vec![]);

    let err =
        handlers::get_file_metadata(web::Data::new(meta), web::Path::from("nope".to_string()))
            .await
            .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

#[actix_web::test]
async fn list_files_prefers_the_header_owner_over_the_query_string() {
    let (header_owner, query_owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![scan_page(vec![], None)]);

    let resp = handlers::list_files(
        request_from(Some(&header_owner)),
        web::Data::new(meta),
        list_query(Some(query_owner)),
    )
    .await
    .unwrap();

    assert_eq!(resp.status(), StatusCode::OK);
    let scan: Value = serde_json::from_slice(
        http.actual_requests()
            .next()
            .unwrap()
            .body()
            .bytes()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        scan["ExpressionAttributeValues"][":owner_id"]["S"],
        header_owner.to_string(),
        "the spoofable query owner is ignored"
    );
}

#[actix_web::test]
async fn list_files_pages_the_results() {
    let owner = Uuid::new_v4();
    let items = (0..5)
        .map(|n| {
            file_item(
                &Uuid::new_v4(),
                &owner,
                &format!("file-{n}.txt"),
                None,
                false,
            )
        })
        .collect();
    let (meta, _http) = metadata_client(vec![scan_page(items, None)]);

    let resp = handlers::list_files(
        request_from(None),
        web::Data::new(meta),
        web::Query(ListFilesQuery {
            folder_id: None,
            owner_id: Some(owner),
            page: Some(2),
            page_size: Some(2),
            include_trashed: Some(true),
        }),
    )
    .await
    .unwrap();

    let body = body_of(resp).await;
    assert_eq!(body["total"], 5);
    assert_eq!(body["page"], 2);
    assert_eq!(body["page_size"], 2);
    assert_eq!(body["files"].as_array().unwrap().len(), 2);
    assert_eq!(body["files"][0]["name"], "file-2.txt");
}

#[actix_web::test]
async fn list_files_clamps_the_page_size() {
    let (meta, _http) = metadata_client(vec![scan_page(vec![], None)]);

    let resp = handlers::list_files(
        request_from(None),
        web::Data::new(meta),
        web::Query(ListFilesQuery {
            folder_id: None,
            owner_id: None,
            page: Some(0),
            page_size: Some(5_000),
            include_trashed: None,
        }),
    )
    .await
    .unwrap();

    let body = body_of(resp).await;
    assert_eq!(body["page"], 1, "page 0 is clamped up");
    assert_eq!(body["page_size"], 100, "page size is capped");
}

#[actix_web::test]
async fn list_files_surfaces_metadata_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = handlers::list_files(request_from(None), web::Data::new(meta), list_query(None))
        .await
        .expect_err("dynamo is down");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[actix_web::test]
async fn list_shared_files_skips_duplicates_and_trashed_files() {
    let (user, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let live = Uuid::new_v4();
    let trashed = Uuid::new_v4();
    let (meta, _http) = metadata_client(vec![
        scan_page(
            vec![
                share_item(&Uuid::new_v4(), &live, &user, &owner, "viewer"),
                share_item(&Uuid::new_v4(), &live, &user, &owner, "editor"),
                share_item(&Uuid::new_v4(), &trashed, &user, &owner, "viewer"),
            ],
            None,
        ),
        dynamo_ok(json!({ "Item": file_item(&live, &owner, "live.txt", None, false) })),
        dynamo_ok(json!({ "Item": file_item(&trashed, &owner, "gone.txt", None, true) })),
    ]);

    let resp = handlers::list_shared_files(
        web::Data::new(meta),
        request_from(Some(&user)),
        list_query(None),
    )
    .await
    .unwrap();

    let body = body_of(resp).await;
    assert_eq!(body["total"], 1, "one duplicate and one trashed file drop");
    assert_eq!(body["files"][0]["name"], "live.txt");
}

#[actix_web::test]
async fn list_shared_files_requires_the_user_header() {
    let (meta, _http) = metadata_client(vec![]);

    let err =
        handlers::list_shared_files(web::Data::new(meta), request_from(None), list_query(None))
            .await
            .expect_err("no user context");

    assert_eq!(err.to_string(), "Bad request: missing X-User-ID header");
}

#[actix_web::test]
async fn list_shared_files_surfaces_metadata_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = handlers::list_shared_files(
        web::Data::new(meta),
        request_from(Some(&Uuid::new_v4())),
        list_query(None),
    )
    .await
    .expect_err("dynamo is down");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[actix_web::test]
async fn list_trashed_returns_the_owners_deleted_files() {
    let owner = Uuid::new_v4();
    let (meta, _http) = metadata_client(vec![scan_page(
        vec![file_item(&Uuid::new_v4(), &owner, "gone.txt", None, true)],
        None,
    )]);

    let resp = handlers::list_trashed(
        request_from(Some(&owner)),
        web::Data::new(meta),
        list_query(None),
    )
    .await
    .unwrap();

    let body = body_of(resp).await;
    assert_eq!(body["total"], 1);
    assert_eq!(body["files"][0]["is_trashed"], true);
}

#[actix_web::test]
async fn list_trashed_surfaces_metadata_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = handlers::list_trashed(request_from(None), web::Data::new(meta), list_query(None))
        .await
        .expect_err("dynamo is down");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

// -- mutations --

#[actix_web::test]
async fn delete_file_removes_metadata_and_the_blob() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
        dynamo_ok(json!({})),
    ]);
    let (s3, s3_http) = s3_client(vec![s3_ok("")]);

    let resp = handlers::delete_file(
        web::Data::new(s3),
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(id.to_string()),
    )
    .await
    .unwrap();

    assert_eq!(resp.status(), StatusCode::NO_CONTENT);
    let deleted = s3_http.actual_requests().next().expect("one DELETE");
    assert_eq!(deleted.method(), "DELETE");
    assert!(deleted.uri().contains(&id.to_string()), "{}", deleted.uri());
}

#[actix_web::test]
async fn delete_file_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);
    let (s3, _s3_http) = s3_client(vec![]);

    let err = handlers::delete_file(
        web::Data::new(s3),
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from("nope".to_string()),
    )
    .await
    .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

#[actix_web::test]
async fn download_file_returns_a_presigned_url() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![dynamo_ok(
        json!({ "Item": file_item(&id, &owner, "a.txt", None, false) }),
    )]);
    let (s3, s3_http) = s3_client(vec![]);

    let resp = handlers::download_file(
        web::Data::new(s3),
        web::Data::new(meta),
        web::Path::from(id.to_string()),
    )
    .await
    .unwrap();

    let body = body_of(resp).await;
    assert_eq!(body["expires_in_secs"], 3600);
    assert!(body["url"].as_str().unwrap().contains("X-Amz-Signature="));
    assert_eq!(
        s3_http.actual_requests().count(),
        0,
        "presigning is offline"
    );
}

#[actix_web::test]
async fn download_file_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);
    let (s3, _s3_http) = s3_client(vec![]);

    let err = handlers::download_file(
        web::Data::new(s3),
        web::Data::new(meta),
        web::Path::from("nope".to_string()),
    )
    .await
    .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

#[actix_web::test]
async fn move_file_updates_the_folder() {
    let (id, owner, folder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", Some(&folder), false) })),
    ]);

    let resp = handlers::move_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(id.to_string()),
        web::Json(MoveFileRequest {
            folder_id: Some(folder),
        }),
    )
    .await
    .unwrap();

    assert_eq!(body_of(resp).await["folder_id"], folder.to_string());
}

#[actix_web::test]
async fn move_file_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::move_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from("nope".to_string()),
        web::Json(MoveFileRequest { folder_id: None }),
    )
    .await
    .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

#[actix_web::test]
async fn rename_file_trims_and_persists_the_new_name() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, dynamo) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "renamed.txt", None, false) })),
    ]);

    let resp = handlers::rename_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(id.to_string()),
        web::Json(RenameFileRequest {
            name: "  renamed.txt  ".into(),
        }),
    )
    .await
    .unwrap();

    assert_eq!(body_of(resp).await["name"], "renamed.txt");
    let update: Value = serde_json::from_slice(
        dynamo
            .actual_requests()
            .next()
            .unwrap()
            .body()
            .bytes()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        update["ExpressionAttributeValues"][":n"]["S"],
        "renamed.txt"
    );
}

#[actix_web::test]
async fn rename_file_rejects_a_blank_name() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::rename_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(Uuid::new_v4().to_string()),
        web::Json(RenameFileRequest { name: "   ".into() }),
    )
    .await
    .expect_err("blank name");

    assert_eq!(err.to_string(), "Bad request: name cannot be empty");
}

#[actix_web::test]
async fn rename_file_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::rename_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from("nope".to_string()),
        web::Json(RenameFileRequest { name: "a".into() }),
    )
    .await
    .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

#[actix_web::test]
async fn list_versions_returns_the_stored_versions() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![dynamo_ok(json!({
        "Items": [version_item(&id, &owner, 2), version_item(&id, &owner, 1)],
        "Count": 2,
    }))]);

    let resp = handlers::list_versions(web::Data::new(meta), web::Path::from(id.to_string()))
        .await
        .unwrap();

    let body = body_of(resp).await;
    assert_eq!(body["versions"].as_array().unwrap().len(), 2);
    assert_eq!(body["versions"][0]["version"], 2);
}

#[actix_web::test]
async fn list_versions_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::list_versions(web::Data::new(meta), web::Path::from("nope".to_string()))
        .await
        .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

#[actix_web::test]
async fn trash_file_marks_the_file_as_trashed() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, true) })),
    ]);

    let resp = handlers::trash_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(id.to_string()),
    )
    .await
    .unwrap();

    assert_eq!(body_of(resp).await["is_trashed"], true);
}

#[actix_web::test]
async fn trash_file_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::trash_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from("nope".to_string()),
    )
    .await
    .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

#[actix_web::test]
async fn restore_file_clears_the_trashed_flag() {
    let (id, owner, folder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", Some(&folder), false) })),
    ]);

    let resp = handlers::restore_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(id.to_string()),
    )
    .await
    .unwrap();

    assert_eq!(body_of(resp).await["is_trashed"], false);
}

#[actix_web::test]
async fn restore_file_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::restore_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from("nope".to_string()),
    )
    .await
    .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

// -- sharing --

fn share_request(shared_with: Uuid, permission: SharePermission) -> web::Json<ShareFileRequest> {
    web::Json(ShareFileRequest {
        shared_with,
        permission,
        shared_by: Uuid::new_v4(),
    })
}

#[actix_web::test]
async fn share_file_creates_a_new_share() {
    let (id, owner, viewer) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
        scan_page(vec![], None),
        dynamo_ok(json!({})),
    ]);

    let resp = handlers::share_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(id.to_string()),
        share_request(viewer, SharePermission::Viewer),
    )
    .await
    .unwrap();

    assert_eq!(resp.status(), StatusCode::CREATED);
    let body = body_of(resp).await;
    assert_eq!(body["share"]["shared_with"], viewer.to_string());
    assert_eq!(body["share"]["permission"], "viewer");
}

#[actix_web::test]
async fn share_file_returns_an_identical_existing_share_unchanged() {
    let (id, owner, viewer, share) = (
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
    );
    let (meta, dynamo) = metadata_client(vec![
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
        scan_page(
            vec![share_item(&share, &id, &viewer, &owner, "viewer")],
            None,
        ),
    ]);

    let resp = handlers::share_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(id.to_string()),
        share_request(viewer, SharePermission::Viewer),
    )
    .await
    .unwrap();

    assert_eq!(resp.status(), StatusCode::OK);
    assert_eq!(body_of(resp).await["share"]["id"], share.to_string());
    assert_eq!(dynamo.actual_requests().count(), 2, "nothing is written");
}

#[actix_web::test]
async fn share_file_upgrades_the_permission_of_an_existing_share() {
    let (id, owner, viewer, share) = (
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
    );
    let (meta, dynamo) = metadata_client(vec![
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
        scan_page(
            vec![share_item(&share, &id, &viewer, &owner, "viewer")],
            None,
        ),
        dynamo_ok(json!({})),
    ]);

    let resp = handlers::share_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from(id.to_string()),
        share_request(viewer, SharePermission::Editor),
    )
    .await
    .unwrap();

    assert_eq!(resp.status(), StatusCode::OK);
    let body = body_of(resp).await;
    assert_eq!(body["share"]["id"], share.to_string(), "same share record");
    assert_eq!(body["share"]["permission"], "editor");
    let written: Value = serde_json::from_slice(
        dynamo
            .actual_requests()
            .nth(2)
            .unwrap()
            .body()
            .bytes()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(written["Item"]["permission"]["S"], "editor");
}

#[actix_web::test]
async fn share_file_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::share_file(
        web::Data::new(meta),
        web::Data::new(silent_publisher().await),
        web::Path::from("nope".to_string()),
        share_request(Uuid::new_v4(), SharePermission::Viewer),
    )
    .await
    .expect_err("not a uuid");

    assert!(err.to_string().starts_with("Bad request: invalid file id"));
}

#[actix_web::test]
async fn remove_share_deletes_the_matching_record() {
    let (id, owner, viewer, share) = (
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
    );
    let (meta, dynamo) = metadata_client(vec![
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
        scan_page(
            vec![share_item(&share, &id, &viewer, &owner, "editor")],
            None,
        ),
        dynamo_ok(json!({})),
    ]);

    let resp = handlers::remove_share(
        web::Data::new(meta),
        web::Path::from((id.to_string(), viewer.to_string())),
    )
    .await
    .unwrap();

    assert_eq!(resp.status(), StatusCode::NO_CONTENT);
    let delete: Value = serde_json::from_slice(
        dynamo
            .actual_requests()
            .nth(2)
            .unwrap()
            .body()
            .bytes()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(delete["Key"]["id"]["S"], share.to_string());
}

#[actix_web::test]
async fn remove_share_reports_a_missing_share() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
        scan_page(vec![], None),
    ]);

    let err = handlers::remove_share(
        web::Data::new(meta),
        web::Path::from((id.to_string(), Uuid::new_v4().to_string())),
    )
    .await
    .expect_err("never shared");

    assert!(matches!(err, ServiceError::ShareNotFound(_)), "{err:?}");
}

#[actix_web::test]
async fn remove_share_rejects_malformed_ids() {
    let (meta, _dynamo) = metadata_client(vec![]);
    let file_err = handlers::remove_share(
        web::Data::new(meta),
        web::Path::from(("nope".to_string(), Uuid::new_v4().to_string())),
    )
    .await
    .expect_err("bad file id");
    assert!(file_err
        .to_string()
        .starts_with("Bad request: invalid file id"));

    let (meta, _dynamo) = metadata_client(vec![]);
    let user_err = handlers::remove_share(
        web::Data::new(meta),
        web::Path::from((Uuid::new_v4().to_string(), "nope".to_string())),
    )
    .await
    .expect_err("bad user id");
    assert!(user_err
        .to_string()
        .starts_with("Bad request: invalid user id"));
}

// -- folders --

#[actix_web::test]
async fn list_folders_scopes_to_the_header_owner() {
    let owner = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![scan_page(
        vec![folder_item(&Uuid::new_v4(), &owner, "Finance", None)],
        None,
    )]);

    let resp = handlers::list_folders(
        request_from(Some(&owner)),
        web::Data::new(meta),
        web::Query(ListFoldersQuery {
            parent_id: None,
            owner_id: None,
        }),
    )
    .await
    .unwrap();

    assert_eq!(body_of(resp).await["folders"][0]["name"], "Finance");
    let scan: Value = serde_json::from_slice(
        http.actual_requests()
            .next()
            .unwrap()
            .body()
            .bytes()
            .unwrap(),
    )
    .unwrap();
    assert_eq!(
        scan["ExpressionAttributeValues"][":owner_id"]["S"],
        owner.to_string()
    );
}

#[actix_web::test]
async fn create_folder_persists_and_echoes_the_folder() {
    let (owner, parent) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![dynamo_ok(json!({}))]);

    let resp = handlers::create_folder(
        web::Data::new(meta),
        web::Json(CreateFolderRequest {
            name: "Finance".into(),
            parent_id: Some(parent),
            owner_id: owner,
        }),
    )
    .await
    .unwrap();

    assert_eq!(resp.status(), StatusCode::CREATED);
    let body = body_of(resp).await;
    assert_eq!(body["name"], "Finance");
    assert_eq!(body["parent_id"], parent.to_string());
    assert_eq!(body["owner_id"], owner.to_string());
}

#[actix_web::test]
async fn get_folder_returns_the_folder() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![dynamo_ok(
        json!({ "Item": folder_item(&id, &owner, "Finance", None) }),
    )]);

    let resp = handlers::get_folder(web::Data::new(meta), web::Path::from(id.to_string()))
        .await
        .unwrap();

    assert_eq!(body_of(resp).await["name"], "Finance");
}

#[actix_web::test]
async fn get_folder_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::get_folder(web::Data::new(meta), web::Path::from("nope".to_string()))
        .await
        .expect_err("not a uuid");

    assert!(err
        .to_string()
        .starts_with("Bad request: invalid folder id"));
}

#[actix_web::test]
async fn update_folder_applies_the_new_name() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _dynamo) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": folder_item(&id, &owner, "Renamed", None) })),
    ]);

    let resp = handlers::update_folder(
        web::Data::new(meta),
        web::Path::from(id.to_string()),
        web::Json(UpdateFolderRequest {
            name: Some("Renamed".into()),
            parent_id: None,
        }),
    )
    .await
    .unwrap();

    assert_eq!(body_of(resp).await["name"], "Renamed");
}

#[actix_web::test]
async fn update_folder_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::update_folder(
        web::Data::new(meta),
        web::Path::from("nope".to_string()),
        web::Json(UpdateFolderRequest {
            name: None,
            parent_id: None,
        }),
    )
    .await
    .expect_err("not a uuid");

    assert!(err
        .to_string()
        .starts_with("Bad request: invalid folder id"));
}

#[actix_web::test]
async fn delete_folder_removes_the_folder() {
    let (meta, _dynamo) = metadata_client(vec![dynamo_ok(json!({}))]);

    let resp = handlers::delete_folder(
        web::Data::new(meta),
        web::Path::from(Uuid::new_v4().to_string()),
    )
    .await
    .unwrap();

    assert_eq!(resp.status(), StatusCode::NO_CONTENT);
}

#[actix_web::test]
async fn delete_folder_rejects_a_malformed_id() {
    let (meta, _dynamo) = metadata_client(vec![]);

    let err = handlers::delete_folder(web::Data::new(meta), web::Path::from("nope".to_string()))
        .await
        .expect_err("not a uuid");

    assert!(err
        .to_string()
        .starts_with("Bad request: invalid folder id"));
}

// -- activity --

#[actix_web::test]
async fn list_activity_merges_uploads_and_shares_newest_first() {
    let owner = Uuid::new_v4();
    let file = Uuid::new_v4();
    let share = Uuid::new_v4();
    let mut recent = file_item(&file, &owner, "recent.txt", None, false);
    recent["created_at"] = json!({ "S": "2024-12-31T00:00:00+00:00" });
    let mut old_share = share_item(&share, &file, &Uuid::new_v4(), &owner, "viewer");
    old_share["created_at"] = json!({ "S": "2024-01-01T00:00:00+00:00" });

    // The handler queries files and shares concurrently, so answer by table rather than order.
    let meta = routed_metadata_client(move |table, _body| {
        let items = if table == FILES_TABLE {
            vec![recent.clone()]
        } else {
            vec![old_share.clone()]
        };
        json!({ "Items": items, "Count": items.len() })
    });

    let resp = handlers::list_activity(
        request_from(Some(&owner)),
        web::Data::new(meta),
        web::Query(ActivityQuery { limit: None }),
    )
    .await
    .unwrap();

    let body = body_of(resp).await;
    let items = body["items"].as_array().unwrap();
    assert_eq!(items.len(), 2);
    assert_eq!(items[0]["type"], "upload");
    assert_eq!(items[0]["description"], "Uploaded recent.txt");
    assert_eq!(items[1]["type"], "share");
    assert_eq!(
        items[1]["description"], "Shared recent.txt",
        "share descriptions resolve the file name"
    );
}

#[actix_web::test]
async fn list_activity_honours_the_limit_and_tolerates_failures() {
    let owner = Uuid::new_v4();
    let files: Vec<Value> = (0..3)
        .map(|n| file_item(&Uuid::new_v4(), &owner, &format!("f{n}.txt"), None, false))
        .collect();
    // Shares come back malformed; the handler degrades to uploads only.
    let meta = routed_metadata_client(move |table, _body| {
        if table == FILES_TABLE {
            json!({ "Items": files, "Count": files.len() })
        } else {
            json!({ "Items": [{ "id": { "S": "not-a-uuid" } }], "Count": 1 })
        }
    });

    let resp = handlers::list_activity(
        request_from(Some(&owner)),
        web::Data::new(meta),
        web::Query(ActivityQuery { limit: Some(2) }),
    )
    .await
    .unwrap();

    assert_eq!(body_of(resp).await["items"].as_array().unwrap().len(), 2);
}

#[actix_web::test]
async fn list_activity_requires_an_owner_header() {
    let meta = routed_metadata_client(|_table, _body| json!({}));

    let err = handlers::list_activity(
        request_from(None),
        web::Data::new(meta),
        web::Query(ActivityQuery { limit: None }),
    )
    .await
    .expect_err("no user context");

    assert_eq!(err.to_string(), "Bad request: missing owner context");
}
