//! End-to-end HTTP tests for every route in `main.rs`, driven through
//! `actix_web::test` with S3/DynamoDB replayed and Redis stubbed on loopback.

mod support;

use actix_web::http::StatusCode;
use actix_web::{test, web, App};
use aws_smithy_runtime::client::http::test_util::StaticReplayClient;
use file_service::config::{AppConfig, AwsConfig, ServerConfig, SnsConfig};
use file_service::events::EventPublisher;
use file_service::handlers;
use file_service::metadata::MetadataClient;
use file_service::storage::S3Client;
use serde_json::Value;
use support::{
    dynamo_body, dynamo_ok, dynamo_server_error, fake_metadata, fake_s3, file_item_json,
    fixed_time, folder_item_json, get_item_response, items_response, s3_ok, sample_file,
    sample_folder, sample_share, sample_version, share_item_json, spawn_redis_stub,
    version_item_json,
};
use uuid::Uuid;

// ── Harness ────────────────────────────────────────────────────────────

fn aws_config() -> AwsConfig {
    AwsConfig {
        region: "us-east-1".into(),
        endpoint_url: None,
        s3_bucket: "test-bucket".into(),
        dynamodb_table: "files-t".into(),
        dynamodb_folders_table: "folders-t".into(),
        dynamodb_versions_table: "versions-t".into(),
        dynamodb_shares_table: "shares-t".into(),
    }
}

fn app_config(max_upload_bytes: u64) -> AppConfig {
    AppConfig {
        server: ServerConfig {
            port: 8082,
            max_upload_bytes,
        },
        aws: aws_config(),
        sns: SnsConfig { topic_arn: None },
    }
}

struct Deps {
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    config: web::Data<AppConfig>,
    s3_http: StaticReplayClient,
    dynamo_http: StaticReplayClient,
}

async fn deps(s3_responses: Vec<(u16, String)>, dynamo_responses: Vec<(u16, String)>) -> Deps {
    let (s3, s3_http) = fake_s3(s3_responses);
    let (meta, dynamo_http) = fake_metadata(dynamo_responses);
    // No SNS topic is configured, so event publishing is a no-op: the handlers
    // are exercised without a second faked boundary.
    let events = EventPublisher::new(&SnsConfig { topic_arn: None }, &aws_config()).await;
    Deps {
        s3: web::Data::new(s3),
        meta: web::Data::new(meta),
        events: web::Data::new(events),
        config: web::Data::new(app_config(100 * 1024 * 1024)),
        s3_http,
        dynamo_http,
    }
}

fn routes(cfg: &mut web::ServiceConfig) {
    cfg.route("/health", web::get().to(handlers::health))
        .route("/metrics", web::get().to(handlers::metrics))
        .service(
            web::scope("/api/v1/files")
                .route("/upload", web::post().to(handlers::upload_file))
                .route("/shared", web::get().to(handlers::list_shared_files))
                .route("/trash", web::get().to(handlers::list_trashed))
                .route("/activity", web::get().to(handlers::list_activity))
                .route("", web::get().to(handlers::list_files))
                .route("/{file_id}", web::get().to(handlers::get_file_metadata))
                .route("/{file_id}", web::delete().to(handlers::delete_file))
                .route(
                    "/{file_id}/download",
                    web::get().to(handlers::download_file),
                )
                .route("/{file_id}/move", web::put().to(handlers::move_file))
                .route("/{file_id}/rename", web::patch().to(handlers::rename_file))
                .route(
                    "/{file_id}/versions",
                    web::get().to(handlers::list_versions),
                )
                .route("/{file_id}/trash", web::post().to(handlers::trash_file))
                .route("/{file_id}/restore", web::post().to(handlers::restore_file))
                .route("/{file_id}/share", web::post().to(handlers::share_file))
                .route(
                    "/{file_id}/share/{user_id}",
                    web::delete().to(handlers::remove_share),
                ),
        )
        .service(
            web::scope("/api/v1/folders")
                .route("", web::get().to(handlers::list_folders))
                .route("", web::post().to(handlers::create_folder))
                .route("/{folder_id}", web::get().to(handlers::get_folder))
                .route("/{folder_id}", web::put().to(handlers::update_folder))
                .route("/{folder_id}", web::delete().to(handlers::delete_folder)),
        );
}

/// Build the multipart body for an upload request.
fn multipart(parts: &[(&str, Option<&str>, &str)]) -> (String, Vec<u8>) {
    const BOUNDARY: &str = "otterworksboundary";
    let mut body = String::new();
    for (name, filename, value) in parts {
        body.push_str(&format!("--{BOUNDARY}\r\n"));
        match filename {
            Some(f) => body.push_str(&format!(
                "Content-Disposition: form-data; name=\"{name}\"; filename=\"{f}\"\r\nContent-Type: text/plain\r\n\r\n"
            )),
            None => body.push_str(&format!(
                "Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            )),
        }
        body.push_str(value);
        body.push_str("\r\n");
    }
    body.push_str(&format!("--{BOUNDARY}--\r\n"));
    (
        format!("multipart/form-data; boundary={BOUNDARY}"),
        body.into_bytes(),
    )
}

async fn redis_data(exists: bool) -> web::Data<redis::aio::ConnectionManager> {
    let addr = spawn_redis_stub(exists).await;
    let client = redis::Client::open(format!("redis://{addr}")).expect("valid url");
    web::Data::new(
        redis::aio::ConnectionManager::new(client)
            .await
            .expect("loopback redis"),
    )
}

// ── Health & metrics ───────────────────────────────────────────────────

#[actix_web::test]
async fn health_reports_the_service_name_and_version() {
    let app = test::init_service(App::new().configure(routes)).await;

    let body: Value =
        test::call_and_read_body_json(&app, test::TestRequest::get().uri("/health").to_request())
            .await;

    assert_eq!(body["status"], "healthy");
    assert_eq!(body["service"], "file-service");
    assert_eq!(body["version"], env!("CARGO_PKG_VERSION"));
}

#[actix_web::test]
async fn metrics_are_served_as_prometheus_text() {
    let app = test::init_service(App::new().configure(routes)).await;

    let resp =
        test::call_service(&app, test::TestRequest::get().uri("/metrics").to_request()).await;

    assert_eq!(resp.status(), StatusCode::OK);
    assert_eq!(
        resp.headers().get("content-type").expect("content type"),
        "text/plain; charset=utf-8"
    );
}

// ── Upload ─────────────────────────────────────────────────────────────

#[actix_web::test]
async fn upload_stores_the_object_then_the_metadata_and_the_first_version() {
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4();
    let d = deps(vec![s3_ok("")], vec![dynamo_ok(), dynamo_ok()]).await;
    let app = test::init_service(
        App::new()
            .app_data(d.s3.clone())
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .app_data(d.config.clone())
            .app_data(redis_data(false).await)
            .configure(routes),
    )
    .await;
    let (content_type, body) = multipart(&[
        ("file", Some("report.pdf"), "hello world"),
        ("owner_id", None, &owner.to_string()),
        ("folder_id", None, &folder.to_string()),
    ]);

    let resp = test::call_service(
        &app,
        test::TestRequest::post()
            .uri("/api/v1/files/upload")
            .insert_header(("content-type", content_type))
            .set_payload(body)
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::CREATED);
    let created: Value = test::read_body_json(resp).await;
    assert_eq!(created["file"]["name"], "report.pdf");
    assert_eq!(created["file"]["mime_type"], "text/plain");
    assert_eq!(created["file"]["size_bytes"], 11);
    assert_eq!(created["file"]["owner_id"], owner.to_string());
    assert_eq!(created["file"]["folder_id"], folder.to_string());
    assert_eq!(created["file"]["version"], 1);
    assert_eq!(created["file"]["is_trashed"], false);
    let file_id = created["file"]["id"].as_str().expect("id");
    assert_eq!(
        created["file"]["s3_key"],
        format!("files/{owner}/{file_id}")
    );

    let put = d.s3_http.actual_requests().next().expect("one S3 PUT");
    assert_eq!(put.method(), "PUT");
    assert!(put.uri().contains("test-bucket"), "{}", put.uri());
    assert_eq!(put.body().bytes().expect("in-memory"), b"hello world");

    let dynamo: Vec<_> = d.dynamo_http.actual_requests().collect();
    assert_eq!(dynamo.len(), 2, "the file row and its version row");
    let version_row: Value =
        serde_json::from_slice(dynamo[1].body().bytes().expect("body")).expect("json");
    assert_eq!(version_row["TableName"], "versions-t");
    assert_eq!(version_row["Item"]["version"]["N"], "1");
}

#[actix_web::test]
async fn upload_prefers_the_gateway_supplied_user_over_the_form_field() {
    let header_owner = Uuid::new_v4();
    let form_owner = Uuid::new_v4();
    let d = deps(vec![s3_ok("")], vec![dynamo_ok(), dynamo_ok()]).await;
    let app = test::init_service(
        App::new()
            .app_data(d.s3.clone())
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .app_data(d.config.clone())
            .app_data(redis_data(false).await)
            .configure(routes),
    )
    .await;
    let (content_type, body) = multipart(&[
        ("file", Some("a.txt"), "x"),
        ("owner_id", None, &form_owner.to_string()),
        ("folder_id", None, "   "),
        ("unexpected", None, "ignored"),
    ]);

    let created: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::post()
            .uri("/api/v1/files/upload")
            .insert_header(("content-type", content_type))
            .insert_header(("X-User-ID", header_owner.to_string()))
            .set_payload(body)
            .to_request(),
    )
    .await;

    assert_eq!(created["file"]["owner_id"], header_owner.to_string());
    assert!(
        created["file"]["folder_id"].is_null(),
        "a blank folder_id field means the drive root"
    );
}

/// (label, multipart parts, expected status, expected message fragment)
type BadUpload = (
    &'static str,
    Vec<(&'static str, Option<&'static str>, &'static str)>,
    StatusCode,
    &'static str,
);

#[actix_web::test]
async fn upload_rejects_bad_requests_before_touching_storage() {
    let cases: Vec<BadUpload> = vec![
        (
            "no owner at all",
            vec![("file", Some("a.txt"), "x")],
            StatusCode::BAD_REQUEST,
            "owner_id is required",
        ),
        (
            "no file part",
            vec![("owner_id", None, "5f1b9a3e-0000-4000-8000-000000000001")],
            StatusCode::BAD_REQUEST,
            "file field is required",
        ),
        (
            "unparseable owner_id",
            vec![("file", Some("a.txt"), "x"), ("owner_id", None, "nope")],
            StatusCode::BAD_REQUEST,
            "invalid owner_id",
        ),
        (
            "unparseable folder_id",
            vec![
                ("file", Some("a.txt"), "x"),
                ("owner_id", None, "5f1b9a3e-0000-4000-8000-000000000001"),
                ("folder_id", None, "nope"),
            ],
            StatusCode::BAD_REQUEST,
            "invalid folder_id",
        ),
    ];

    for (label, parts, expected_status, expected_message) in cases {
        let d = deps(vec![], vec![]).await;
        let app = test::init_service(
            App::new()
                .app_data(d.s3.clone())
                .app_data(d.meta.clone())
                .app_data(d.events.clone())
                .app_data(d.config.clone())
                .app_data(redis_data(false).await)
                .configure(routes),
        )
        .await;
        let (content_type, body) = multipart(&parts);

        let resp = test::call_service(
            &app,
            test::TestRequest::post()
                .uri("/api/v1/files/upload")
                .insert_header(("content-type", content_type))
                .set_payload(body)
                .to_request(),
        )
        .await;

        assert_eq!(resp.status(), expected_status, "{label}");
        let body: Value = test::read_body_json(resp).await;
        assert!(
            body["message"]
                .as_str()
                .expect("message")
                .contains(expected_message),
            "{label}: {body}"
        );
        assert_eq!(
            d.s3_http.actual_requests().count(),
            0,
            "{label}: nothing should reach S3"
        );
    }
}

#[actix_web::test]
async fn upload_rejects_a_payload_over_the_configured_limit() {
    let owner = Uuid::new_v4();
    let (s3, s3_http) = fake_s3(vec![]);
    let (meta, _dynamo) = fake_metadata(vec![]);
    let events = EventPublisher::new(&SnsConfig { topic_arn: None }, &aws_config()).await;
    let app = test::init_service(
        App::new()
            .app_data(web::Data::new(s3))
            .app_data(web::Data::new(meta))
            .app_data(web::Data::new(events))
            .app_data(web::Data::new(app_config(4)))
            .app_data(redis_data(false).await)
            .configure(routes),
    )
    .await;
    let (content_type, body) = multipart(&[
        ("file", Some("big.txt"), "0123456789"),
        ("owner_id", None, &owner.to_string()),
    ]);

    let resp = test::call_service(
        &app,
        test::TestRequest::post()
            .uri("/api/v1/files/upload")
            .insert_header(("content-type", content_type))
            .set_payload(body)
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::PAYLOAD_TOO_LARGE);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["error"], "file_too_large");
    assert!(
        body["message"].as_str().expect("message").contains("max 4"),
        "{body}"
    );
    assert_eq!(s3_http.actual_requests().count(), 0);
}

#[actix_web::test]
async fn the_upload_chaos_flag_redirects_the_put_to_a_nonexistent_bucket() {
    // Planted chaos hook: when `chaos:file-service:upload_s3_error` is set in
    // Redis the upload is deliberately aimed at a bucket that does not exist.
    let owner = Uuid::new_v4();
    let d = deps(
        vec![(
            404,
            "<Error><Code>NoSuchBucket</Code><Message>no</Message></Error>".to_string(),
        )],
        vec![],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.s3.clone())
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .app_data(d.config.clone())
            .app_data(redis_data(true).await)
            .configure(routes),
    )
    .await;
    let (content_type, body) = multipart(&[
        ("file", Some("a.txt"), "x"),
        ("owner_id", None, &owner.to_string()),
    ]);

    let resp = test::call_service(
        &app,
        test::TestRequest::post()
            .uri("/api/v1/files/upload")
            .insert_header(("content-type", content_type))
            .set_payload(body)
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::INTERNAL_SERVER_ERROR);
    let put = d.s3_http.actual_requests().next().expect("one S3 PUT");
    assert!(
        put.uri().contains("otterworks-files-chaos-nonexistent"),
        "{}",
        put.uri()
    );
}

// ── Read paths ─────────────────────────────────────────────────────────

#[actix_web::test]
async fn get_file_metadata_returns_the_file_with_its_shares() {
    let owner = Uuid::new_v4();
    let file = sample_file(Uuid::new_v4(), owner);
    let share = sample_share(Uuid::new_v4(), file.id, Uuid::new_v4());
    let d = deps(
        vec![],
        vec![
            dynamo_body(get_item_response(&file_item_json(&file))),
            dynamo_body(items_response(&[share_item_json(&share)])),
        ],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.s3.clone())
            .app_data(d.events.clone())
            .configure(routes),
    )
    .await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri(&format!("/api/v1/files/{}", file.id))
            .to_request(),
    )
    .await;

    assert_eq!(body["id"], file.id.to_string());
    assert_eq!(body["name"], "report.pdf");
    assert_eq!(body["shared_with"][0]["id"], share.id.to_string());
}

#[actix_web::test]
async fn get_file_metadata_still_answers_when_the_share_lookup_fails() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let d = deps(
        vec![],
        vec![
            dynamo_body(get_item_response(&file_item_json(&file))),
            dynamo_server_error(),
        ],
    )
    .await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri(&format!("/api/v1/files/{}", file.id))
            .to_request(),
    )
    .await;

    assert_eq!(body["id"], file.id.to_string());
    assert_eq!(
        body["shared_with"].as_array().expect("array").len(),
        0,
        "a failed share lookup degrades to an empty list"
    );
}

#[actix_web::test]
async fn an_unparseable_id_in_the_path_is_a_bad_request_on_every_route() {
    let routes_under_test = [
        ("GET", "/api/v1/files/not-a-uuid", "invalid file id"),
        ("DELETE", "/api/v1/files/not-a-uuid", "invalid file id"),
        (
            "GET",
            "/api/v1/files/not-a-uuid/download",
            "invalid file id",
        ),
        (
            "GET",
            "/api/v1/files/not-a-uuid/versions",
            "invalid file id",
        ),
        ("POST", "/api/v1/files/not-a-uuid/trash", "invalid file id"),
        (
            "POST",
            "/api/v1/files/not-a-uuid/restore",
            "invalid file id",
        ),
        ("GET", "/api/v1/folders/not-a-uuid", "invalid folder id"),
        ("DELETE", "/api/v1/folders/not-a-uuid", "invalid folder id"),
    ];

    for (method, uri, expected) in routes_under_test {
        let d = deps(vec![], vec![]).await;
        let app = test::init_service(
            App::new()
                .app_data(d.meta.clone())
                .app_data(d.s3.clone())
                .app_data(d.events.clone())
                .configure(routes),
        )
        .await;
        let req = match method {
            "GET" => test::TestRequest::get(),
            "POST" => test::TestRequest::post(),
            _ => test::TestRequest::delete(),
        };

        let resp = test::call_service(&app, req.uri(uri).to_request()).await;

        assert_eq!(resp.status(), StatusCode::BAD_REQUEST, "{method} {uri}");
        let body: Value = test::read_body_json(resp).await;
        assert!(
            body["message"]
                .as_str()
                .expect("message")
                .contains(expected),
            "{method} {uri}: {body}"
        );
    }
}

#[actix_web::test]
async fn a_missing_file_is_a_404() {
    let d = deps(vec![], vec![dynamo_ok()]).await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let resp = test::call_service(
        &app,
        test::TestRequest::get()
            .uri(&format!("/api/v1/files/{}", Uuid::new_v4()))
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["error"], "file_not_found");
}

#[actix_web::test]
async fn list_files_pages_the_result_and_honours_the_user_header() {
    let owner = Uuid::new_v4();
    let files: Vec<String> = (0..3)
        .map(|_| file_item_json(&sample_file(Uuid::new_v4(), owner)))
        .collect();
    let d = deps(vec![], vec![dynamo_body(items_response(&files))]).await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/files?page=2&page_size=2")
            .insert_header(("X-User-ID", owner.to_string()))
            .to_request(),
    )
    .await;

    assert_eq!(body["total"], 3);
    assert_eq!(body["page"], 2);
    assert_eq!(body["page_size"], 2);
    assert_eq!(
        body["files"].as_array().expect("files").len(),
        1,
        "page 2 of 3 items at 2 per page holds the remainder"
    );

    let scan: Value = serde_json::from_slice(
        d.dynamo_http
            .actual_requests()
            .next()
            .expect("one scan")
            .body()
            .bytes()
            .expect("body"),
    )
    .expect("json");
    assert_eq!(
        scan["ExpressionAttributeValues"][":owner_id"]["S"],
        owner.to_string(),
        "the header identity is what gets filtered on"
    );
}

#[actix_web::test]
async fn list_files_clamps_the_page_size_and_page_number() {
    let owner = Uuid::new_v4();
    let d = deps(vec![], vec![dynamo_body(items_response(&[]))]).await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri(&format!(
                "/api/v1/files?owner_id={owner}&page=0&page_size=500&include_trashed=true"
            ))
            .to_request(),
    )
    .await;

    assert_eq!(body["page"], 1, "page 0 is clamped up to 1");
    assert_eq!(body["page_size"], 100, "page_size is capped at 100");
}

#[actix_web::test]
async fn list_shared_files_deduplicates_and_hides_trashed_files() {
    let user = Uuid::new_v4();
    let visible = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let mut trashed = sample_file(Uuid::new_v4(), Uuid::new_v4());
    trashed.is_trashed = true;
    // Two share rows point at the same file: a legacy duplicate.
    let shares = vec![
        share_item_json(&sample_share(Uuid::new_v4(), visible.id, user)),
        share_item_json(&sample_share(Uuid::new_v4(), visible.id, user)),
        share_item_json(&sample_share(Uuid::new_v4(), trashed.id, user)),
    ];
    let d = deps(
        vec![],
        vec![
            dynamo_body(items_response(&shares)),
            dynamo_body(get_item_response(&file_item_json(&visible))),
            dynamo_body(get_item_response(&file_item_json(&trashed))),
        ],
    )
    .await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/files/shared")
            .insert_header(("X-User-ID", user.to_string()))
            .to_request(),
    )
    .await;

    assert_eq!(body["total"], 1);
    assert_eq!(body["files"][0]["id"], visible.id.to_string());
    assert_eq!(
        d.dynamo_http.actual_requests().count(),
        3,
        "the duplicate share is skipped before its file is fetched"
    );
}

#[actix_web::test]
async fn list_shared_files_requires_the_user_header() {
    let d = deps(vec![], vec![]).await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let resp = test::call_service(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/files/shared")
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    let body: Value = test::read_body_json(resp).await;
    assert!(body["message"]
        .as_str()
        .expect("message")
        .contains("missing X-User-ID header"));
}

#[actix_web::test]
async fn list_trashed_returns_only_the_trashed_files() {
    let owner = Uuid::new_v4();
    let mut trashed = sample_file(Uuid::new_v4(), owner);
    trashed.is_trashed = true;
    let d = deps(
        vec![],
        vec![dynamo_body(items_response(&[file_item_json(&trashed)]))],
    )
    .await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/files/trash")
            .insert_header(("X-User-ID", owner.to_string()))
            .to_request(),
    )
    .await;

    assert_eq!(body["total"], 1);
    assert_eq!(body["files"][0]["is_trashed"], true);
}

#[actix_web::test]
async fn download_returns_a_presigned_url_valid_for_an_hour() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let d = deps(
        vec![],
        vec![dynamo_body(get_item_response(&file_item_json(&file)))],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.s3.clone())
            .configure(routes),
    )
    .await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri(&format!("/api/v1/files/{}/download", file.id))
            .to_request(),
    )
    .await;

    assert_eq!(body["expires_in_secs"], 3600);
    let url = body["url"].as_str().expect("url");
    assert!(url.contains(&file.s3_key), "{url}");
    assert!(url.contains("X-Amz-Expires=3600"), "{url}");
}

#[actix_web::test]
async fn list_versions_returns_the_version_history() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let version = sample_version(file.id, file.owner_id);
    let d = deps(
        vec![],
        vec![dynamo_body(items_response(&[version_item_json(&version)]))],
    )
    .await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri(&format!("/api/v1/files/{}/versions", file.id))
            .to_request(),
    )
    .await;

    assert_eq!(body["versions"][0]["version"], 2);
    assert_eq!(body["versions"][0]["size_bytes"], 2048);
}

// ── Mutations ──────────────────────────────────────────────────────────

#[actix_web::test]
async fn delete_removes_the_metadata_row_and_then_the_object() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let d = deps(
        vec![(204, String::new())],
        vec![
            dynamo_body(get_item_response(&file_item_json(&file))),
            dynamo_ok(),
        ],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.s3.clone())
            .app_data(d.events.clone())
            .configure(routes),
    )
    .await;

    let resp = test::call_service(
        &app,
        test::TestRequest::delete()
            .uri(&format!("/api/v1/files/{}", file.id))
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::NO_CONTENT);
    let deleted = d.s3_http.actual_requests().next().expect("one S3 DELETE");
    assert_eq!(deleted.method(), "DELETE");
    assert!(deleted.uri().contains(&file.s3_key), "{}", deleted.uri());
}

#[actix_web::test]
async fn move_updates_the_folder_and_echoes_the_file() {
    let folder = Uuid::new_v4();
    let mut file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    file.folder_id = Some(folder);
    let d = deps(
        vec![],
        vec![
            dynamo_ok(),
            dynamo_body(get_item_response(&file_item_json(&file))),
        ],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .configure(routes),
    )
    .await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::put()
            .uri(&format!("/api/v1/files/{}/move", file.id))
            .set_json(serde_json::json!({ "folder_id": folder }))
            .to_request(),
    )
    .await;

    assert_eq!(body["folder_id"], folder.to_string());
}

#[actix_web::test]
async fn rename_trims_the_name_and_rejects_a_blank_one() {
    let mut file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    file.name = "renamed.pdf".into();
    let d = deps(
        vec![],
        vec![
            dynamo_ok(),
            dynamo_body(get_item_response(&file_item_json(&file))),
        ],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .configure(routes),
    )
    .await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::patch()
            .uri(&format!("/api/v1/files/{}/rename", file.id))
            .set_json(serde_json::json!({ "name": "  renamed.pdf  " }))
            .to_request(),
    )
    .await;
    assert_eq!(body["name"], "renamed.pdf");
    let update: Value = serde_json::from_slice(
        d.dynamo_http
            .actual_requests()
            .next()
            .expect("update")
            .body()
            .bytes()
            .expect("body"),
    )
    .expect("json");
    assert_eq!(
        update["ExpressionAttributeValues"][":n"]["S"], "renamed.pdf",
        "the stored name is trimmed"
    );

    let resp = test::call_service(
        &app,
        test::TestRequest::patch()
            .uri(&format!("/api/v1/files/{}/rename", file.id))
            .set_json(serde_json::json!({ "name": "   " }))
            .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["message"], "Bad request: name cannot be empty");
}

#[actix_web::test]
async fn trash_and_restore_flip_the_flag() {
    let mut trashed = sample_file(Uuid::new_v4(), Uuid::new_v4());
    trashed.is_trashed = true;
    let restored = sample_file(trashed.id, trashed.owner_id);
    let d = deps(
        vec![],
        vec![
            dynamo_ok(),
            dynamo_body(get_item_response(&file_item_json(&trashed))),
            dynamo_ok(),
            dynamo_body(get_item_response(&file_item_json(&restored))),
        ],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .configure(routes),
    )
    .await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::post()
            .uri(&format!("/api/v1/files/{}/trash", trashed.id))
            .to_request(),
    )
    .await;
    assert_eq!(body["is_trashed"], true);

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::post()
            .uri(&format!("/api/v1/files/{}/restore", trashed.id))
            .to_request(),
    )
    .await;
    assert_eq!(body["is_trashed"], false);
}

// ── Sharing ────────────────────────────────────────────────────────────

#[actix_web::test]
async fn sharing_a_file_for_the_first_time_creates_the_share() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let peer = Uuid::new_v4();
    let d = deps(
        vec![],
        vec![
            dynamo_body(get_item_response(&file_item_json(&file))),
            dynamo_body(items_response(&[])),
            dynamo_ok(),
        ],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .configure(routes),
    )
    .await;

    let resp = test::call_service(
        &app,
        test::TestRequest::post()
            .uri(&format!("/api/v1/files/{}/share", file.id))
            .set_json(serde_json::json!({
                "shared_with": peer,
                "permission": "editor",
                "shared_by": file.owner_id,
            }))
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::CREATED);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["share"]["shared_with"], peer.to_string());
    assert_eq!(body["share"]["permission"], "editor");
    assert_eq!(body["share"]["file_id"], file.id.to_string());
}

#[actix_web::test]
async fn re_sharing_with_the_same_permission_returns_the_existing_share() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let peer = Uuid::new_v4();
    let existing = sample_share(Uuid::new_v4(), file.id, peer);
    let d = deps(
        vec![],
        vec![
            dynamo_body(get_item_response(&file_item_json(&file))),
            dynamo_body(items_response(&[share_item_json(&existing)])),
        ],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .configure(routes),
    )
    .await;

    let resp = test::call_service(
        &app,
        test::TestRequest::post()
            .uri(&format!("/api/v1/files/{}/share", file.id))
            .set_json(serde_json::json!({
                "shared_with": peer,
                "permission": "viewer",
                "shared_by": peer,
            }))
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::OK, "not a fresh 201");
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["share"]["id"], existing.id.to_string());
    assert_eq!(
        d.dynamo_http.actual_requests().count(),
        2,
        "no write is issued when nothing changed"
    );
}

#[actix_web::test]
async fn re_sharing_with_a_different_permission_upgrades_it_in_place() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let peer = Uuid::new_v4();
    let existing = sample_share(Uuid::new_v4(), file.id, peer);
    let d = deps(
        vec![],
        vec![
            dynamo_body(get_item_response(&file_item_json(&file))),
            dynamo_body(items_response(&[share_item_json(&existing)])),
            dynamo_ok(),
        ],
    )
    .await;
    let app = test::init_service(
        App::new()
            .app_data(d.meta.clone())
            .app_data(d.events.clone())
            .configure(routes),
    )
    .await;

    let resp = test::call_service(
        &app,
        test::TestRequest::post()
            .uri(&format!("/api/v1/files/{}/share", file.id))
            .set_json(serde_json::json!({
                "shared_with": peer,
                "permission": "editor",
                "shared_by": peer,
            }))
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::OK);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(
        body["share"]["id"],
        existing.id.to_string(),
        "the share keeps its identity"
    );
    assert_eq!(body["share"]["permission"], "editor");
    assert_eq!(
        body["share"]["created_at"],
        serde_json::to_value(existing.created_at).expect("serializable"),
        "the original creation time is preserved"
    );
}

#[actix_web::test]
async fn removing_a_share_deletes_it_and_404s_when_there_is_none() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let peer = Uuid::new_v4();
    let existing = sample_share(Uuid::new_v4(), file.id, peer);
    let d = deps(
        vec![],
        vec![
            dynamo_body(get_item_response(&file_item_json(&file))),
            dynamo_body(items_response(&[share_item_json(&existing)])),
            dynamo_ok(),
            dynamo_body(get_item_response(&file_item_json(&file))),
            dynamo_body(items_response(&[])),
        ],
    )
    .await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let resp = test::call_service(
        &app,
        test::TestRequest::delete()
            .uri(&format!("/api/v1/files/{}/share/{peer}", file.id))
            .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::NO_CONTENT);

    let resp = test::call_service(
        &app,
        test::TestRequest::delete()
            .uri(&format!("/api/v1/files/{}/share/{peer}", file.id))
            .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::NOT_FOUND);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["error"], "share_not_found");
}

#[actix_web::test]
async fn removing_a_share_validates_both_ids() {
    let d = deps(vec![], vec![]).await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let resp = test::call_service(
        &app,
        test::TestRequest::delete()
            .uri(&format!("/api/v1/files/{}/share/nope", Uuid::new_v4()))
            .to_request(),
    )
    .await;

    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    let body: Value = test::read_body_json(resp).await;
    assert!(body["message"]
        .as_str()
        .expect("message")
        .contains("invalid user id"));
}

// ── Folders ────────────────────────────────────────────────────────────

#[actix_web::test]
async fn folders_can_be_created_read_updated_listed_and_deleted() {
    let owner = Uuid::new_v4();
    let folder = sample_folder(Uuid::new_v4(), owner);
    let d = deps(
        vec![],
        vec![
            dynamo_ok(),
            dynamo_body(get_item_response(&folder_item_json(&folder))),
            dynamo_ok(),
            dynamo_body(get_item_response(&folder_item_json(&folder))),
            dynamo_body(items_response(&[folder_item_json(&folder)])),
            dynamo_ok(),
        ],
    )
    .await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let resp = test::call_service(
        &app,
        test::TestRequest::post()
            .uri("/api/v1/folders")
            .set_json(serde_json::json!({ "name": "Finance", "owner_id": owner }))
            .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::CREATED);
    let created: Value = test::read_body_json(resp).await;
    assert_eq!(created["name"], "Finance");
    assert_eq!(created["owner_id"], owner.to_string());

    let read: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri(&format!("/api/v1/folders/{}", folder.id))
            .to_request(),
    )
    .await;
    assert_eq!(read["id"], folder.id.to_string());

    let updated: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::put()
            .uri(&format!("/api/v1/folders/{}", folder.id))
            .set_json(serde_json::json!({ "name": "Finance" }))
            .to_request(),
    )
    .await;
    assert_eq!(updated["id"], folder.id.to_string());

    let listed: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/folders")
            .insert_header(("X-User-ID", owner.to_string()))
            .to_request(),
    )
    .await;
    assert_eq!(listed["folders"].as_array().expect("folders").len(), 1);

    let resp = test::call_service(
        &app,
        test::TestRequest::delete()
            .uri(&format!("/api/v1/folders/{}", folder.id))
            .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::NO_CONTENT);
}

// ── Activity feed ──────────────────────────────────────────────────────

#[actix_web::test]
async fn activity_merges_uploads_and_shares_newest_first() {
    let owner = Uuid::new_v4();
    let mut older = sample_file(Uuid::new_v4(), owner);
    older.name = "older.pdf".into();
    older.created_at = fixed_time() - chrono::Duration::days(1);
    let newer = sample_file(Uuid::new_v4(), owner);
    let mut share = sample_share(Uuid::new_v4(), newer.id, owner);
    share.created_at = fixed_time() + chrono::Duration::hours(1);
    let orphan_share = sample_share(Uuid::new_v4(), Uuid::new_v4(), owner);

    let d = deps(
        vec![],
        vec![
            dynamo_body(items_response(&[
                file_item_json(&older),
                file_item_json(&newer),
            ])),
            dynamo_body(items_response(&[
                share_item_json(&share),
                share_item_json(&orphan_share),
            ])),
        ],
    )
    .await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/files/activity")
            .insert_header(("X-User-ID", owner.to_string()))
            .to_request(),
    )
    .await;

    let items = body["items"].as_array().expect("items");
    assert_eq!(items.len(), 4);
    assert_eq!(items[0]["type"], "share");
    assert_eq!(
        items[0]["description"], "Shared report.pdf",
        "the newest entry is the share, and it resolves the file name"
    );
    assert!(
        items.iter().any(|i| i["description"] == "Shared a file"),
        "a share pointing at an unknown file degrades gracefully: {items:?}"
    );
    assert_eq!(
        items[3]["resource_name"], "older.pdf",
        "the day-old upload sorts last"
    );
    assert!(items
        .iter()
        .all(|i| i["actor_name"] == "You" && i["resource_type"] == "file"));
}

#[actix_web::test]
async fn activity_truncates_to_the_requested_limit_and_needs_a_user() {
    let owner = Uuid::new_v4();
    let files: Vec<String> = (0..5)
        .map(|_| file_item_json(&sample_file(Uuid::new_v4(), owner)))
        .collect();
    let d = deps(
        vec![],
        vec![
            dynamo_body(items_response(&files)),
            dynamo_body(items_response(&[])),
        ],
    )
    .await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/files/activity?limit=2")
            .insert_header(("X-User-ID", owner.to_string()))
            .to_request(),
    )
    .await;
    assert_eq!(body["items"].as_array().expect("items").len(), 2);

    let resp = test::call_service(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/files/activity")
            .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::BAD_REQUEST);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["message"], "Bad request: missing owner context");
}

#[actix_web::test]
async fn activity_degrades_to_an_empty_feed_when_dynamo_is_down() {
    let d = deps(vec![], vec![dynamo_server_error(), dynamo_server_error()]).await;
    let app = test::init_service(App::new().app_data(d.meta.clone()).configure(routes)).await;

    let body: Value = test::call_and_read_body_json(
        &app,
        test::TestRequest::get()
            .uri("/api/v1/files/activity")
            .insert_header(("X-User-ID", Uuid::new_v4().to_string()))
            .to_request(),
    )
    .await;

    assert_eq!(body["items"].as_array().expect("items").len(), 0);
}
