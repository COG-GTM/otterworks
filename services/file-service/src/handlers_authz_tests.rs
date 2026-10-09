//! Handler-level authorization tests against an in-process fake DynamoDB/S3
//! endpoint, so they need no LocalStack.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use actix_web::{http::StatusCode, test, web, App, HttpRequest, HttpResponse, HttpServer};
use serde_json::{json, Value};
use uuid::Uuid;

use crate::config::{AppConfig, AwsConfig, SnsConfig};
use crate::events::EventPublisher;
use crate::handlers;
use crate::metadata::MetadataClient;
use crate::storage::S3Client;

#[derive(Default)]
struct FakeState {
    files: HashMap<String, Value>,
    shares: Vec<Value>,
    writes: Vec<String>,
}

type Shared = Arc<Mutex<FakeState>>;

fn amz_json(status: StatusCode, body: Value) -> HttpResponse {
    HttpResponse::build(status)
        .content_type("application/x-amz-json-1.0")
        .body(body.to_string())
}

fn attr_s<'a>(item: &'a Value, key: &str) -> Option<&'a str> {
    item.get(key)?.get("S")?.as_str()
}

async fn fake_aws(req: HttpRequest, body: web::Bytes, state: web::Data<Shared>) -> HttpResponse {
    let target = req
        .headers()
        .get("X-Amz-Target")
        .and_then(|v| v.to_str().ok())
        .and_then(|t| t.rsplit('.').next())
        .map(String::from);
    let Some(op) = target else {
        // S3 (DeleteObject etc.)
        state
            .lock()
            .unwrap()
            .writes
            .push(format!("S3:{}", req.method()));
        return HttpResponse::NoContent().finish();
    };
    let input: Value = serde_json::from_slice(&body).unwrap_or(json!({}));
    let values = input
        .get("ExpressionAttributeValues")
        .cloned()
        .unwrap_or(json!({}));
    let mut st = state.lock().unwrap();
    match op.as_str() {
        "GetItem" => {
            let id = input["Key"]["id"]["S"].as_str().unwrap_or_default();
            match st.files.get(id) {
                Some(item) => amz_json(StatusCode::OK, json!({ "Item": item })),
                None => amz_json(StatusCode::OK, json!({})),
            }
        }
        "Scan" => {
            let fid = attr_s(&values, ":fid");
            let uid = attr_s(&values, ":uid");
            let items: Vec<Value> = st
                .shares
                .iter()
                .filter(|s| fid.map_or(true, |f| attr_s(s, "file_id") == Some(f)))
                .filter(|s| uid.map_or(true, |u| attr_s(s, "shared_with") == Some(u)))
                .cloned()
                .collect();
            let n = items.len();
            amz_json(
                StatusCode::OK,
                json!({ "Items": items, "Count": n, "ScannedCount": n }),
            )
        }
        "Query" => amz_json(
            StatusCode::OK,
            json!({ "Items": [], "Count": 0, "ScannedCount": 0 }),
        ),
        "UpdateItem" | "DeleteItem" | "PutItem" => {
            if let Some(owner) = attr_s(&values, ":owner") {
                let id = input["Key"]["id"]["S"].as_str().unwrap_or_default();
                let stored_owner = st.files.get(id).and_then(|f| attr_s(f, "owner_id"));
                if stored_owner != Some(owner) {
                    return amz_json(
                        StatusCode::BAD_REQUEST,
                        json!({
                            "__type": "com.amazonaws.dynamodb.v20120810#ConditionalCheckFailedException",
                            "message": "The conditional request failed"
                        }),
                    );
                }
            }
            let table = input["TableName"].as_str().unwrap_or_default().to_string();
            if op == "PutItem" && table == "shares" {
                st.shares.push(input["Item"].clone());
            }
            st.writes.push(format!("{op}:{table}"));
            amz_json(StatusCode::OK, json!({}))
        }
        _ => amz_json(StatusCode::OK, json!({})),
    }
}

struct Fixture {
    state: Shared,
    meta: MetadataClient,
    s3: S3Client,
    events: EventPublisher,
    owner: Uuid,
    viewer: Uuid,
    editor: Uuid,
    stranger: Uuid,
    file_id: Uuid,
}

fn file_item(id: &Uuid, owner: &Uuid) -> Value {
    json!({
        "id": {"S": id.to_string()},
        "name": {"S": "Q3 Financial Report.txt"},
        "mime_type": {"S": "text/plain"},
        "size_bytes": {"N": "42"},
        "s3_key": {"S": format!("files/{owner}/{id}")},
        "owner_id": {"S": owner.to_string()},
        "version": {"N": "1"},
        "is_trashed": {"BOOL": false},
        "created_at": {"S": "2026-01-01T00:00:00+00:00"},
        "updated_at": {"S": "2026-01-01T00:00:00+00:00"}
    })
}

fn share_item(file_id: &Uuid, with: &Uuid, by: &Uuid, permission: &str) -> Value {
    json!({
        "id": {"S": Uuid::new_v4().to_string()},
        "file_id": {"S": file_id.to_string()},
        "shared_with": {"S": with.to_string()},
        "permission": {"S": permission},
        "shared_by": {"S": by.to_string()},
        "created_at": {"S": "2026-01-01T00:00:00+00:00"}
    })
}

async fn fixture() -> Fixture {
    let (owner, viewer, editor, stranger, file_id) = (
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
    );
    let state: Shared = Arc::default();
    {
        let mut st = state.lock().unwrap();
        st.files
            .insert(file_id.to_string(), file_item(&file_id, &owner));
        st.shares
            .push(share_item(&file_id, &viewer, &owner, "viewer"));
        st.shares
            .push(share_item(&file_id, &editor, &owner, "editor"));
    }

    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = format!("http://{}", listener.local_addr().unwrap());
    let data = web::Data::new(state.clone());
    let server = HttpServer::new(move || {
        App::new()
            .app_data(data.clone())
            .app_data(web::PayloadConfig::new(1 << 20))
            .default_service(web::to(fake_aws))
    })
    .workers(1)
    .listen(listener)
    .unwrap()
    .run();
    actix_rt::spawn(server);

    let creds = aws_sdk_dynamodb::config::Credentials::new("test", "test", None, None, "test");
    let ddb_conf = aws_sdk_dynamodb::Config::builder()
        .behavior_version(aws_sdk_dynamodb::config::BehaviorVersion::latest())
        .region(aws_sdk_dynamodb::config::Region::new("us-east-1"))
        .credentials_provider(creds.clone())
        .endpoint_url(&endpoint)
        .build();
    let meta = MetadataClient {
        client: aws_sdk_dynamodb::Client::from_conf(ddb_conf),
        files_table: "files".into(),
        folders_table: "folders".into(),
        versions_table: "versions".into(),
        shares_table: "shares".into(),
    };
    let s3_conf = aws_sdk_s3::Config::builder()
        .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
        .region(aws_sdk_s3::config::Region::new("us-east-1"))
        .credentials_provider(creds)
        .endpoint_url(&endpoint)
        .force_path_style(true)
        .build();
    let s3 = S3Client {
        client: aws_sdk_s3::Client::from_conf(s3_conf),
        bucket: "otterworks-files".into(),
    };
    let aws = AwsConfig {
        region: "us-east-1".into(),
        endpoint_url: Some(endpoint.clone()),
        s3_bucket: "otterworks-files".into(),
        dynamodb_table: "files".into(),
        dynamodb_folders_table: "folders".into(),
        dynamodb_versions_table: "versions".into(),
        dynamodb_shares_table: "shares".into(),
    };
    let sns = SnsConfig {
        topic_arn: None,
        share_event_always_fail: false,
    };
    let events = EventPublisher::new(&sns, &aws).await;

    Fixture {
        state,
        meta,
        s3,
        events,
        owner,
        viewer,
        editor,
        stranger,
        file_id,
    }
}

macro_rules! app {
    ($fx:expr) => {
        test::init_service(
            App::new()
                .app_data(web::Data::new(AppConfig::from_env()))
                .app_data(web::Data::new($fx.s3.clone()))
                .app_data(web::Data::new($fx.meta.clone()))
                .app_data(web::Data::new($fx.events.clone()))
                .service(
                    web::scope("/api/v1/files")
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
                ),
        )
        .await
    };
}

/// Every per-id route, as (method, path suffix, json body).
fn per_id_requests(fx: &Fixture, target: &Uuid) -> Vec<(&'static str, String, Option<Value>)> {
    let base = format!("/api/v1/files/{}", fx.file_id);
    vec![
        ("GET", base.clone(), None),
        ("GET", format!("{base}/download"), None),
        ("GET", format!("{base}/versions"), None),
        (
            "PUT",
            format!("{base}/move"),
            Some(json!({ "folder_id": null })),
        ),
        (
            "PATCH",
            format!("{base}/rename"),
            Some(json!({ "name": "pwned.txt" })),
        ),
        ("POST", format!("{base}/trash"), None),
        ("POST", format!("{base}/restore"), None),
        (
            "POST",
            format!("{base}/share"),
            Some(json!({ "shared_with": target, "permission": "editor", "shared_by": fx.owner })),
        ),
        ("DELETE", format!("{base}/share/{}", fx.viewer), None),
        ("DELETE", base, None),
    ]
}

fn build(
    method: &str,
    path: &str,
    body: Option<Value>,
    caller: Option<&Uuid>,
) -> test::TestRequest {
    let mut req = match method {
        "GET" => test::TestRequest::get(),
        "PUT" => test::TestRequest::put(),
        "PATCH" => test::TestRequest::patch(),
        "POST" => test::TestRequest::post(),
        "DELETE" => test::TestRequest::delete(),
        other => panic!("unexpected method {other}"),
    }
    .uri(path);
    if let Some(caller) = caller {
        req = req.insert_header(("X-User-ID", caller.to_string()));
    }
    if let Some(body) = body {
        req = req.set_json(body);
    }
    req
}

fn writes(fx: &Fixture) -> Vec<String> {
    fx.state.lock().unwrap().writes.clone()
}

#[actix_rt::test]
async fn stranger_gets_404_on_every_per_id_route_and_nothing_is_written() {
    let fx = fixture().await;
    let app = app!(fx);
    for (method, path, body) in per_id_requests(&fx, &fx.stranger) {
        let resp = test::call_service(
            &app,
            build(method, &path, body, Some(&fx.stranger)).to_request(),
        )
        .await;
        assert_eq!(resp.status(), StatusCode::NOT_FOUND, "{method} {path}");
    }
    assert!(
        writes(&fx).is_empty(),
        "unexpected writes: {:?}",
        writes(&fx)
    );
}

#[actix_rt::test]
async fn missing_identity_is_rejected_before_any_lookup() {
    let fx = fixture().await;
    let app = app!(fx);
    for (method, path, body) in per_id_requests(&fx, &fx.stranger) {
        let resp = test::call_service(&app, build(method, &path, body, None).to_request()).await;
        assert_eq!(resp.status(), StatusCode::UNAUTHORIZED, "{method} {path}");
    }
    assert!(writes(&fx).is_empty());
}

#[actix_rt::test]
async fn owner_keeps_full_access() {
    let fx = fixture().await;
    let app = app!(fx);
    let base = format!("/api/v1/files/{}", fx.file_id);

    let resp = test::call_service(
        &app,
        build("GET", &base, None, Some(&fx.owner)).to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::OK);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["shared_with"].as_array().unwrap().len(), 2);

    let resp = test::call_service(
        &app,
        build("GET", &format!("{base}/download"), None, Some(&fx.owner)).to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::OK);

    let resp = test::call_service(
        &app,
        build(
            "PATCH",
            &format!("{base}/rename"),
            Some(json!({"name": "Q4.txt"})),
            Some(&fx.owner),
        )
        .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::OK);

    let resp = test::call_service(
        &app,
        build("DELETE", &base, None, Some(&fx.owner)).to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::NO_CONTENT);
    let w = writes(&fx);
    assert!(w.contains(&"UpdateItem:files".to_string()), "{w:?}");
    assert!(w.contains(&"DeleteItem:files".to_string()), "{w:?}");
    assert!(w.contains(&"S3:DELETE".to_string()), "{w:?}");
}

#[actix_rt::test]
async fn viewer_can_read_but_not_modify_or_reshare() {
    let fx = fixture().await;
    let app = app!(fx);
    let base = format!("/api/v1/files/{}", fx.file_id);

    let resp = test::call_service(
        &app,
        build("GET", &base, None, Some(&fx.viewer)).to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::OK);
    let body: Value = test::read_body_json(resp).await;
    let shares = body["shared_with"].as_array().unwrap();
    assert_eq!(shares.len(), 1, "viewer must only see their own share");
    assert_eq!(shares[0]["shared_with"], json!(fx.viewer));

    let resp = test::call_service(
        &app,
        build("GET", &format!("{base}/download"), None, Some(&fx.viewer)).to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::OK);

    for (method, path, body) in [
        (
            "PATCH",
            format!("{base}/rename"),
            Some(json!({"name": "x.txt"})),
        ),
        (
            "POST",
            format!("{base}/share"),
            Some(json!({"shared_with": fx.viewer, "permission": "editor", "shared_by": fx.owner})),
        ),
        ("DELETE", format!("{base}/share/{}", fx.editor), None),
        ("POST", format!("{base}/trash"), None),
        ("GET", format!("{base}/versions"), None),
        ("DELETE", base.clone(), None),
    ] {
        let resp = test::call_service(
            &app,
            build(method, &path, body, Some(&fx.viewer)).to_request(),
        )
        .await;
        assert_eq!(resp.status(), StatusCode::NOT_FOUND, "{method} {path}");
    }
    assert!(writes(&fx).is_empty(), "{:?}", writes(&fx));

    // A recipient may leave a share.
    let resp = test::call_service(
        &app,
        build(
            "DELETE",
            &format!("{base}/share/{}", fx.viewer),
            None,
            Some(&fx.viewer),
        )
        .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::NO_CONTENT);
    assert_eq!(writes(&fx), vec!["DeleteItem:shares".to_string()]);
}

#[actix_rt::test]
async fn editor_can_rename_but_not_manage() {
    let fx = fixture().await;
    let app = app!(fx);
    let base = format!("/api/v1/files/{}", fx.file_id);

    let resp = test::call_service(
        &app,
        build(
            "PATCH",
            &format!("{base}/rename"),
            Some(json!({"name": "y.txt"})),
            Some(&fx.editor),
        )
        .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::OK);

    for (method, path) in [("PUT", format!("{base}/move")), ("DELETE", base.clone())] {
        let body = (method == "PUT").then(|| json!({"folder_id": null}));
        let resp = test::call_service(
            &app,
            build(method, &path, body, Some(&fx.editor)).to_request(),
        )
        .await;
        assert_eq!(resp.status(), StatusCode::NOT_FOUND, "{method} {path}");
    }
}

#[actix_rt::test]
async fn share_records_the_authenticated_owner_as_sharer() {
    let fx = fixture().await;
    let app = app!(fx);
    let recipient = Uuid::new_v4();
    let resp = test::call_service(
        &app,
        build(
            "POST",
            &format!("/api/v1/files/{}/share", fx.file_id),
            Some(
                json!({"shared_with": recipient, "permission": "viewer", "shared_by": fx.stranger}),
            ),
            Some(&fx.owner),
        )
        .to_request(),
    )
    .await;
    assert_eq!(resp.status(), StatusCode::CREATED);
    let body: Value = test::read_body_json(resp).await;
    assert_eq!(body["share"]["shared_by"], json!(fx.owner));
}
