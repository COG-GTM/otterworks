//! Shared fakes for the file-service integration tests.
//!
//! Every AWS client is built from a `StaticReplayClient`, so the tests exercise the real
//! SDK serialization/deserialization path without touching the network, LocalStack or AWS.

#![allow(dead_code)]

use aws_smithy_runtime::client::http::test_util::{ReplayEvent, StaticReplayClient};
use aws_smithy_types::body::SdkBody;
use chrono::{DateTime, Utc};
use file_service::metadata::MetadataClient;
use file_service::storage::S3Client;
use serde_json::{json, Value};
use uuid::Uuid;

pub const FILES_TABLE: &str = "test-files";
pub const FOLDERS_TABLE: &str = "test-folders";
pub const VERSIONS_TABLE: &str = "test-versions";
pub const SHARES_TABLE: &str = "test-shares";
pub const BUCKET: &str = "test-bucket";

/// A fixed instant so nothing in the suite depends on the wall clock.
pub fn fixed_time() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2024-05-06T07:08:09Z")
        .unwrap()
        .with_timezone(&Utc)
}

fn dummy_request(uri: &str) -> http::Request<SdkBody> {
    http::Request::builder()
        .method("POST")
        .uri(uri)
        .body(SdkBody::empty())
        .unwrap()
}

/// A successful DynamoDB (AWS JSON 1.0) response.
pub fn dynamo_ok(body: Value) -> ReplayEvent {
    ReplayEvent::new(
        dummy_request("https://dynamodb.us-east-1.amazonaws.com/"),
        http::Response::builder()
            .status(200)
            .header("content-type", "application/x-amz-json-1.0")
            .body(SdkBody::from(body.to_string()))
            .unwrap(),
    )
}

/// A modelled DynamoDB error, e.g. `ValidationException`.
pub fn dynamo_err(error_type: &str) -> ReplayEvent {
    let body = json!({
        "__type": format!("com.amazonaws.dynamodb.v20120810#{error_type}"),
        "message": "injected failure",
    });
    ReplayEvent::new(
        dummy_request("https://dynamodb.us-east-1.amazonaws.com/"),
        http::Response::builder()
            .status(400)
            .header("content-type", "application/x-amz-json-1.0")
            .header("x-amzn-errortype", error_type)
            .body(SdkBody::from(body.to_string()))
            .unwrap(),
    )
}

/// A DynamoDB `Scan`/`Query` page; `last_key` set means "another page follows".
pub fn scan_page(items: Vec<Value>, last_key: Option<Value>) -> ReplayEvent {
    let count = items.len();
    let mut body = json!({ "Items": items, "Count": count, "ScannedCount": count });
    if let Some(key) = last_key {
        body["LastEvaluatedKey"] = key;
    }
    dynamo_ok(body)
}

pub fn key_of(id: &Uuid) -> Value {
    json!({ "id": { "S": id.to_string() } })
}

pub fn metadata_client(events: Vec<ReplayEvent>) -> (MetadataClient, StaticReplayClient) {
    let http = StaticReplayClient::new(events);
    let conf = aws_sdk_dynamodb::Config::builder()
        .behavior_version(aws_sdk_dynamodb::config::BehaviorVersion::latest())
        .region(aws_sdk_dynamodb::config::Region::new("us-east-1"))
        .credentials_provider(aws_sdk_dynamodb::config::Credentials::for_tests())
        .retry_config(aws_sdk_dynamodb::config::retry::RetryConfig::disabled())
        .http_client(http.clone())
        .build();
    let client = MetadataClient {
        client: aws_sdk_dynamodb::Client::from_conf(conf),
        files_table: FILES_TABLE.to_string(),
        folders_table: FOLDERS_TABLE.to_string(),
        versions_table: VERSIONS_TABLE.to_string(),
        shares_table: SHARES_TABLE.to_string(),
    };
    (client, http)
}

/// A successful S3 response with an arbitrary body.
pub fn s3_ok(body: &'static str) -> ReplayEvent {
    ReplayEvent::new(
        dummy_request("https://test-bucket.s3.us-east-1.amazonaws.com/"),
        http::Response::builder()
            .status(200)
            .body(SdkBody::from(body))
            .unwrap(),
    )
}

/// An S3 error response (`NoSuchKey`, `NoSuchBucket`, ...).
pub fn s3_err(status: u16, code: &str) -> ReplayEvent {
    let body = format!("<Error><Code>{code}</Code><Message>injected failure</Message></Error>");
    ReplayEvent::new(
        dummy_request("https://test-bucket.s3.us-east-1.amazonaws.com/"),
        http::Response::builder()
            .status(status)
            .body(SdkBody::from(body))
            .unwrap(),
    )
}

pub fn s3_client(events: Vec<ReplayEvent>) -> (S3Client, StaticReplayClient) {
    let http = StaticReplayClient::new(events);
    let conf = aws_sdk_s3::Config::builder()
        .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
        .region(aws_sdk_s3::config::Region::new("us-east-1"))
        .credentials_provider(aws_sdk_s3::config::Credentials::for_tests())
        .retry_config(aws_sdk_s3::config::retry::RetryConfig::disabled())
        .http_client(http.clone())
        // Mirrors the production client built in `S3Client::new`.
        .force_path_style(true)
        .build();
    let client = S3Client {
        client: aws_sdk_s3::Client::from_conf(conf),
        bucket: BUCKET.to_string(),
    };
    (client, http)
}

/// A DynamoDB client that answers from `route(table_name, request_body)`.
///
/// Needed where the handler fires several requests concurrently (`list_activity`),
/// which makes the ordered `StaticReplayClient` non-deterministic.
pub fn routed_metadata_client(
    route: impl Fn(&str, &Value) -> Value + Send + Sync + 'static,
) -> MetadataClient {
    let http = aws_smithy_http_client::test_util::infallible_client_fn(move |req| {
        let body: Value = serde_json::from_slice(req.body().bytes().unwrap_or_default()).unwrap();
        let table = body["TableName"].as_str().unwrap_or_default().to_string();
        http::Response::builder()
            .status(200)
            .header("content-type", "application/x-amz-json-1.0")
            .body(SdkBody::from(route(&table, &body).to_string()))
            .unwrap()
    });
    let conf = aws_sdk_dynamodb::Config::builder()
        .behavior_version(aws_sdk_dynamodb::config::BehaviorVersion::latest())
        .region(aws_sdk_dynamodb::config::Region::new("us-east-1"))
        .credentials_provider(aws_sdk_dynamodb::config::Credentials::for_tests())
        .retry_config(aws_sdk_dynamodb::config::retry::RetryConfig::disabled())
        .http_client(http)
        .build();
    MetadataClient {
        client: aws_sdk_dynamodb::Client::from_conf(conf),
        files_table: FILES_TABLE.to_string(),
        folders_table: FOLDERS_TABLE.to_string(),
        versions_table: VERSIONS_TABLE.to_string(),
        shares_table: SHARES_TABLE.to_string(),
    }
}

/// A publisher with no SNS topic: the handlers' fire-and-forget events become no-ops.
pub async fn silent_publisher() -> file_service::events::EventPublisher {
    file_service::events::EventPublisher::new(
        &file_service::config::SnsConfig { topic_arn: None },
        &aws_config_for_tests(),
    )
    .await
}

pub fn aws_config_for_tests() -> file_service::config::AwsConfig {
    file_service::config::AwsConfig {
        region: "us-east-1".into(),
        endpoint_url: None,
        s3_bucket: BUCKET.into(),
        dynamodb_table: FILES_TABLE.into(),
        dynamodb_folders_table: FOLDERS_TABLE.into(),
        dynamodb_versions_table: VERSIONS_TABLE.into(),
        dynamodb_shares_table: SHARES_TABLE.into(),
    }
}

// -- Fake Redis (only the chaos-flag `EXISTS` lookup is exercised) --

/// Split a RESP buffer into complete commands, returning the bytes consumed.
fn parse_resp_commands(buffer: &[u8]) -> (Vec<Vec<String>>, usize) {
    let text = String::from_utf8_lossy(buffer);
    let lines: Vec<&str> = text.split("\r\n").collect();
    let mut commands = Vec::new();
    let mut line = 0;
    let mut consumed = 0;
    while line < lines.len() {
        let Some(argc) = lines[line]
            .strip_prefix('*')
            .and_then(|n| n.parse::<usize>().ok())
        else {
            break;
        };
        // Every argument is a `$len` header line plus the data line.
        let end = line + 1 + argc * 2;
        if end > lines.len() {
            break;
        }
        commands.push(
            (0..argc)
                .map(|arg| lines[line + 2 + arg * 2].to_string())
                .collect(),
        );
        consumed += lines[line..end].iter().map(|l| l.len() + 2).sum::<usize>();
        line = end;
    }
    (commands, consumed)
}

/// A minimal RESP server that answers `EXISTS` with `flag_set` and everything else with `+OK`.
///
/// `redis::aio::ConnectionManager` requires a reachable server at construction time, so the
/// chaos-flag lookup in `upload_file` cannot be faked at a higher level.
pub async fn fake_redis(flag_set: bool) -> redis::aio::ConnectionManager {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();

    tokio::spawn(async move {
        while let Ok((mut socket, _)) = listener.accept().await {
            tokio::spawn(async move {
                let mut chunk = [0u8; 4096];
                let mut buffer: Vec<u8> = Vec::new();
                loop {
                    match socket.read(&mut chunk).await {
                        Ok(0) | Err(_) => break,
                        Ok(read) => buffer.extend_from_slice(&chunk[..read]),
                    }
                    let (commands, consumed) = parse_resp_commands(&buffer);
                    buffer.drain(..consumed);
                    let mut reply = String::new();
                    for command in commands {
                        let verb = command
                            .first()
                            .map(|v| v.to_uppercase())
                            .unwrap_or_default();
                        reply.push_str(match verb.as_str() {
                            "EXISTS" if flag_set => ":1\r\n",
                            "EXISTS" => ":0\r\n",
                            "PING" => "+PONG\r\n",
                            _ => "+OK\r\n",
                        });
                    }
                    if socket.write_all(reply.as_bytes()).await.is_err() {
                        break;
                    }
                }
            });
        }
    });

    redis::aio::ConnectionManager::new(redis::Client::open(format!("redis://{addr}")).unwrap())
        .await
        .expect("fake redis should accept the connection")
}

// -- DynamoDB item builders (wire format) --

pub fn file_item(
    id: &Uuid,
    owner: &Uuid,
    name: &str,
    folder: Option<&Uuid>,
    trashed: bool,
) -> Value {
    let ts = fixed_time().to_rfc3339();
    let mut item = json!({
        "id": { "S": id.to_string() },
        "name": { "S": name },
        "mime_type": { "S": "text/plain" },
        "size_bytes": { "N": "1024" },
        "s3_key": { "S": format!("files/{owner}/{id}") },
        "owner_id": { "S": owner.to_string() },
        "version": { "N": "1" },
        "is_trashed": { "BOOL": trashed },
        "created_at": { "S": ts },
        "updated_at": { "S": ts },
    });
    if let Some(folder) = folder {
        item["folder_id"] = json!({ "S": folder.to_string() });
    }
    item
}

pub fn folder_item(id: &Uuid, owner: &Uuid, name: &str, parent: Option<&Uuid>) -> Value {
    let ts = fixed_time().to_rfc3339();
    let mut item = json!({
        "id": { "S": id.to_string() },
        "name": { "S": name },
        "owner_id": { "S": owner.to_string() },
        "created_at": { "S": ts },
        "updated_at": { "S": ts },
    });
    if let Some(parent) = parent {
        item["parent_id"] = json!({ "S": parent.to_string() });
    }
    item
}

pub fn version_item(file_id: &Uuid, owner: &Uuid, version: u32) -> Value {
    json!({
        "file_id": { "S": file_id.to_string() },
        "version": { "N": version.to_string() },
        "s3_key": { "S": format!("files/{owner}/{file_id}") },
        "size_bytes": { "N": "1024" },
        "created_by": { "S": owner.to_string() },
        "created_at": { "S": fixed_time().to_rfc3339() },
    })
}

pub fn share_item(
    id: &Uuid,
    file_id: &Uuid,
    shared_with: &Uuid,
    shared_by: &Uuid,
    permission: &str,
) -> Value {
    json!({
        "id": { "S": id.to_string() },
        "file_id": { "S": file_id.to_string() },
        "shared_with": { "S": shared_with.to_string() },
        "permission": { "S": permission },
        "shared_by": { "S": shared_by.to_string() },
        "created_at": { "S": fixed_time().to_rfc3339() },
    })
}
