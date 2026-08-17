//! Test-only helpers: fake AWS HTTP boundaries and an in-process Redis stub.
//!
//! Everything here is behind `#[cfg(test)]` and never compiled into the binary.
//! Tests stay hermetic: no live AWS, no LocalStack, no Redis server, no clock.

use aws_smithy_runtime::client::http::test_util::{ReplayEvent, StaticReplayClient};
use aws_smithy_types::body::SdkBody;
use chrono::{DateTime, TimeZone, Utc};
use std::sync::Mutex;
use uuid::Uuid;

use crate::config::AwsConfig;
use crate::metadata::MetadataClient;
use crate::storage::S3Client;

/// `std::env` is process-global and `cargo test` is multi-threaded, so every
/// test that touches the environment is serialized and restores what it found.
static ENV_LOCK: Mutex<()> = Mutex::new(());

/// Restores the captured environment on drop, so a panicking test body (a
/// failed assertion) cannot leak its mutations into the tests that follow.
struct EnvRestore(Vec<(String, Option<String>)>);

impl Drop for EnvRestore {
    fn drop(&mut self) {
        for (k, v) in self.0.drain(..) {
            match v {
                Some(v) => std::env::set_var(&k, v),
                None => std::env::remove_var(&k),
            }
        }
    }
}

pub(crate) fn with_env<T>(vars: &[(&str, Option<&str>)], f: impl FnOnce() -> T) -> T {
    let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let _restore = EnvRestore(
        vars.iter()
            .map(|(k, _)| ((*k).to_string(), std::env::var(k).ok()))
            .collect(),
    );
    for (k, v) in vars {
        match v {
            Some(v) => std::env::set_var(k, v),
            None => std::env::remove_var(k),
        }
    }
    f()
}

/// Run an async body inside `with_env` on a private current-thread runtime.
/// Keeps the (blocking) env guard off `.await` points.
pub(crate) fn with_env_blocking<F, T>(vars: &[(&str, Option<&str>)], fut: F) -> T
where
    F: std::future::Future<Output = T>,
{
    with_env(vars, || {
        tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap()
            .block_on(fut)
    })
}

/// Credentials + region for code paths that build a real AWS client from the
/// default provider chain. Keeps those paths entirely offline.
pub(crate) fn offline_aws_env() -> Vec<(&'static str, Option<&'static str>)> {
    vec![
        ("AWS_ACCESS_KEY_ID", Some("test-access-key")),
        ("AWS_SECRET_ACCESS_KEY", Some("test-secret-key")),
        ("AWS_SESSION_TOKEN", None),
        ("AWS_PROFILE", None),
        ("AWS_EC2_METADATA_DISABLED", Some("true")),
    ]
}

/// A fixed timestamp so no test depends on the wall clock.
pub(crate) fn fixed_time() -> DateTime<Utc> {
    Utc.with_ymd_and_hms(2024, 5, 17, 12, 30, 45).unwrap()
}

/// A deterministic UUID built from a single byte.
pub(crate) fn uuid_from(byte: u8) -> Uuid {
    Uuid::from_bytes([byte; 16])
}

pub(crate) fn aws_config_fixture() -> AwsConfig {
    AwsConfig {
        region: "us-east-1".into(),
        endpoint_url: None,
        s3_bucket: "test-bucket".into(),
        dynamodb_table: "files".into(),
        dynamodb_folders_table: "folders".into(),
        dynamodb_versions_table: "versions".into(),
        dynamodb_shares_table: "shares".into(),
    }
}

/// Build a replay client that answers each request, in order, with the given
/// (status, body) pair.
pub(crate) fn replay(responses: Vec<(u16, String)>) -> StaticReplayClient {
    let events = responses
        .into_iter()
        .map(|(status, body)| {
            ReplayEvent::new(
                http::Request::builder()
                    .method("POST")
                    .uri("https://example.test/")
                    .body(SdkBody::empty())
                    .unwrap(),
                http::Response::builder()
                    .status(status)
                    .header("content-type", "application/x-amz-json-1.0")
                    .body(SdkBody::from(body))
                    .unwrap(),
            )
        })
        .collect();
    StaticReplayClient::new(events)
}

pub(crate) fn ok_json(body: &str) -> (u16, String) {
    (200, body.to_string())
}

/// A DynamoDB error response (`__type` is how the SDK picks the error shape).
pub(crate) fn dynamo_error(status: u16, code: &str) -> (u16, String) {
    (
        status,
        format!(r#"{{"__type":"com.amazonaws.dynamodb.v20120810#{code}","message":"boom"}}"#),
    )
}

pub(crate) fn s3_client(http: StaticReplayClient) -> S3Client {
    let conf = aws_sdk_s3::Config::builder()
        .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
        .region(aws_sdk_s3::config::Region::new("us-east-1"))
        .credentials_provider(aws_sdk_s3::config::Credentials::for_tests())
        .retry_config(aws_sdk_s3::config::retry::RetryConfig::disabled())
        .http_client(http)
        .build();
    S3Client {
        client: aws_sdk_s3::Client::from_conf(conf),
        bucket: "test-bucket".to_string(),
    }
}

pub(crate) fn metadata_client(http: StaticReplayClient) -> MetadataClient {
    let conf = aws_sdk_dynamodb::Config::builder()
        .behavior_version(aws_sdk_dynamodb::config::BehaviorVersion::latest())
        .region(aws_sdk_dynamodb::config::Region::new("us-east-1"))
        .credentials_provider(aws_sdk_dynamodb::config::Credentials::for_tests())
        .retry_config(aws_sdk_dynamodb::config::retry::RetryConfig::disabled())
        .http_client(http)
        .build();
    MetadataClient {
        client: aws_sdk_dynamodb::Client::from_conf(conf),
        files_table: "files".into(),
        folders_table: "folders".into(),
        versions_table: "versions".into(),
        shares_table: "shares".into(),
    }
}

pub(crate) fn sns_client(http: StaticReplayClient) -> aws_sdk_sns::Client {
    let conf = aws_sdk_sns::Config::builder()
        .behavior_version(aws_sdk_sns::config::BehaviorVersion::latest())
        .region(aws_sdk_sns::config::Region::new("us-east-1"))
        .credentials_provider(aws_sdk_sns::config::Credentials::for_tests())
        .retry_config(aws_sdk_sns::config::retry::RetryConfig::disabled())
        .http_client(http)
        .build();
    aws_sdk_sns::Client::from_conf(conf)
}

pub(crate) fn sns_publish_ok() -> (u16, String) {
    (
        200,
        r#"<PublishResponse xmlns="http://sns.amazonaws.com/doc/2010-03-31/">
             <PublishResult><MessageId>11111111-2222-3333-4444-555555555555</MessageId></PublishResult>
           </PublishResponse>"#
            .to_string(),
    )
}

// -- DynamoDB item fixtures (JSON wire format) --

pub(crate) fn file_item_json(id: Uuid, owner: Uuid, folder: Option<Uuid>) -> String {
    let ts = fixed_time().to_rfc3339();
    let folder_attr = folder
        .map(|f| format!(r#","folder_id":{{"S":"{f}"}}"#))
        .unwrap_or_default();
    format!(
        r#"{{"id":{{"S":"{id}"}},"name":{{"S":"report.pdf"}},"mime_type":{{"S":"application/pdf"}},
            "size_bytes":{{"N":"2048"}},"s3_key":{{"S":"files/{owner}/{id}"}},
            "owner_id":{{"S":"{owner}"}},"version":{{"N":"1"}},"is_trashed":{{"BOOL":false}},
            "created_at":{{"S":"{ts}"}},"updated_at":{{"S":"{ts}"}}{folder_attr}}}"#
    )
}

pub(crate) fn folder_item_json(id: Uuid, owner: Uuid, parent: Option<Uuid>) -> String {
    let ts = fixed_time().to_rfc3339();
    let parent_attr = parent
        .map(|p| format!(r#","parent_id":{{"S":"{p}"}}"#))
        .unwrap_or_default();
    format!(
        r#"{{"id":{{"S":"{id}"}},"name":{{"S":"Finance"}},"owner_id":{{"S":"{owner}"}},
            "created_at":{{"S":"{ts}"}},"updated_at":{{"S":"{ts}"}}{parent_attr}}}"#
    )
}

pub(crate) fn version_item_json(file_id: Uuid, owner: Uuid, version: u32) -> String {
    let ts = fixed_time().to_rfc3339();
    format!(
        r#"{{"file_id":{{"S":"{file_id}"}},"version":{{"N":"{version}"}},
            "s3_key":{{"S":"files/{owner}/{file_id}"}},"size_bytes":{{"N":"2048"}},
            "created_by":{{"S":"{owner}"}},"created_at":{{"S":"{ts}"}}}}"#
    )
}

pub(crate) fn share_item_json(
    id: Uuid,
    file_id: Uuid,
    shared_with: Uuid,
    shared_by: Uuid,
    permission: &str,
) -> String {
    let ts = fixed_time().to_rfc3339();
    format!(
        r#"{{"id":{{"S":"{id}"}},"file_id":{{"S":"{file_id}"}},"shared_with":{{"S":"{shared_with}"}},
            "permission":{{"S":"{permission}"}},"shared_by":{{"S":"{shared_by}"}},
            "created_at":{{"S":"{ts}"}}}}"#
    )
}

pub(crate) fn get_item_response(item_json: &str) -> (u16, String) {
    ok_json(&format!(r#"{{"Item":{item_json}}}"#))
}

pub(crate) fn empty_get_item_response() -> (u16, String) {
    ok_json("{}")
}

pub(crate) fn scan_response(items: &[String]) -> (u16, String) {
    ok_json(&format!(
        r#"{{"Items":[{}],"Count":{}}}"#,
        items.join(","),
        items.len()
    ))
}

pub(crate) fn query_response(items: &[String]) -> (u16, String) {
    scan_response(items)
}

pub(crate) fn write_ok() -> (u16, String) {
    ok_json("{}")
}

// -- In-process Redis stub --

/// Length of the first complete RESP command (`*N` followed by N bulk strings)
/// at the front of `buf`, or `None` while it is still incomplete.
fn resp_command_len(buf: &[u8]) -> Option<usize> {
    fn line<'a>(buf: &'a [u8], pos: &mut usize) -> Option<&'a str> {
        let rest = buf.get(*pos..)?;
        let end = rest.windows(2).position(|w| w == b"\r\n")?;
        *pos += end + 2;
        std::str::from_utf8(&rest[..end]).ok()
    }

    let mut pos = 0;
    let argc: usize = line(buf, &mut pos)?.strip_prefix('*')?.parse().ok()?;
    for _ in 0..argc {
        let len: usize = line(buf, &mut pos)?.strip_prefix('$')?.parse().ok()?;
        if buf.len() < pos + len + 2 {
            return None;
        }
        pos += len + 2;
    }
    Some(pos)
}

/// A minimal RESP server that answers every command with the same integer
/// reply. Used to build a real `ConnectionManager` without a Redis server:
/// `1` makes the chaos flag look present, `0` absent.
///
/// Only integer-reply commands (`EXISTS`, as used by `chaos_active`) are
/// modelled. A handler that starts issuing `GET`/`SETEX` needs a stub that
/// dispatches on the command name, not this one.
pub(crate) struct RedisStub {
    pub(crate) url: String,
    handle: tokio::task::JoinHandle<()>,
}

impl Drop for RedisStub {
    fn drop(&mut self) {
        self.handle.abort();
    }
}

impl RedisStub {
    pub(crate) async fn start(integer_reply: i64) -> Self {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let handle = tokio::spawn(async move {
            while let Ok((mut socket, _)) = listener.accept().await {
                tokio::spawn(async move {
                    let mut chunk = [0u8; 4096];
                    let mut pending: Vec<u8> = Vec::new();
                    loop {
                        match socket.read(&mut chunk).await {
                            Ok(0) | Err(_) => break,
                            Ok(n) => pending.extend_from_slice(&chunk[..n]),
                        }
                        // Reply once per *fully received* command, so a partial
                        // read or an argument whose bytes start with '*' cannot
                        // desynchronise the stream.
                        let mut replies = String::new();
                        while let Some(len) = resp_command_len(&pending) {
                            pending.drain(..len);
                            replies.push_str(&format!(":{integer_reply}\r\n"));
                        }
                        if !replies.is_empty()
                            && socket.write_all(replies.as_bytes()).await.is_err()
                        {
                            break;
                        }
                    }
                });
            }
        });

        Self {
            url: format!("redis://{addr}"),
            handle,
        }
    }

    pub(crate) async fn connection_manager(&self) -> redis::aio::ConnectionManager {
        let client = redis::Client::open(self.url.clone()).unwrap();
        redis::aio::ConnectionManager::new(client).await.unwrap()
    }
}
