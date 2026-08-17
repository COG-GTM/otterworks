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

/// Every test that reads or writes an AWS/config environment variable must go
/// through here (or [`with_env_blocking`]): the assertions in `storage.rs` need
/// `AWS_ENDPOINT_URL` cleared while `config.rs` sets it, and only the shared
/// `ENV_LOCK` keeps those from racing. A bare `std::env::set_var` -- or a client
/// built from the AWS default provider chain outside this helper -- reintroduces
/// cross-test flakiness.
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
///
/// Call it from a plain `#[test]` only: `block_on` panics with "Cannot start a
/// runtime from within a runtime" under `#[tokio::test]`/`#[actix_rt::test]`.
/// `ENV_LOCK` is a plain (non-reentrant) `Mutex`, so nesting `with_env` inside
/// the body deadlocks.
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
/// default provider chain. Keeps those paths entirely offline *and* independent
/// of the developer's machine: endpoint overrides and the shared config files
/// are neutralised too, so a shell with LocalStack exported cannot change the
/// URLs these tests assert on.
pub(crate) fn offline_aws_env() -> Vec<(&'static str, Option<&'static str>)> {
    vec![
        ("AWS_ACCESS_KEY_ID", Some("test-access-key")),
        ("AWS_SECRET_ACCESS_KEY", Some("test-secret-key")),
        ("AWS_SESSION_TOKEN", None),
        ("AWS_PROFILE", None),
        ("AWS_EC2_METADATA_DISABLED", Some("true")),
        ("AWS_ENDPOINT_URL", None),
        ("AWS_ENDPOINT_URL_S3", None),
        ("AWS_ENDPOINT_URL_DYNAMODB", None),
        ("AWS_ENDPOINT_URL_SNS", None),
        ("AWS_USE_FIPS_ENDPOINT", None),
        ("AWS_USE_DUALSTACK_ENDPOINT", None),
        // Point at a file that exists and defines nothing, so `~/.aws/config`
        // cannot supply a region, endpoint or profile either.
        ("AWS_CONFIG_FILE", Some("/dev/null")),
        ("AWS_SHARED_CREDENTIALS_FILE", Some("/dev/null")),
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
        // `S3Client::new` sets this, so the fake addresses objects the same way
        // the deployed service does (path style, as LocalStack/MinIO require).
        .force_path_style(true)
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

/// Assert the code under test made exactly `expected` HTTP calls through this
/// replay client. Counts requests only -- it says nothing about how many
/// responses were primed -- so it catches both a skipped call and a retry.
pub(crate) fn assert_calls(http: &StaticReplayClient, expected: usize) {
    assert_eq!(
        http.actual_requests().count(),
        expected,
        "unexpected number of requests through this client"
    );
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

/// Decode an `application/x-www-form-urlencoded` body -- the wire format of the
/// SNS query protocol -- into its parameters. A `%` not followed by two hex
/// digits is left as-is rather than panicking.
pub(crate) fn form_params(body: &str) -> std::collections::HashMap<String, String> {
    body.split('&')
        .filter_map(|pair| pair.split_once('='))
        .map(|(k, v)| (percent_decode(k), percent_decode(v)))
        .collect()
}

fn percent_decode(raw: &str) -> String {
    let bytes = raw.replace('+', " ").into_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        let decoded = if bytes[i] == b'%' && i + 2 < bytes.len() {
            std::str::from_utf8(&bytes[i + 1..i + 3])
                .ok()
                .and_then(|hex| u8::from_str_radix(hex, 16).ok())
        } else {
            None
        };
        match decoded {
            Some(byte) => {
                out.push(byte);
                i += 3;
            }
            None => {
                out.push(bytes[i]);
                i += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
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

/// Rewrite part of a fixture, asserting the pattern was there. A silent no-op
/// replacement would leave the test asserting against the unmodified item.
pub(crate) fn rewrite(json: &str, from: &str, to: &str) -> String {
    assert!(json.contains(from), "fixture has no {from:?} to replace");
    json.replace(from, to)
}

/// The same file fixture, flagged as trashed.
pub(crate) fn trashed(file_json: &str) -> String {
    rewrite(
        file_json,
        r#""is_trashed":{"BOOL":false}"#,
        r#""is_trashed":{"BOOL":true}"#,
    )
}

/// The same fixture with its `fixed_time()` timestamps moved to `rfc3339`.
pub(crate) fn dated(json: &str, rfc3339: &str) -> String {
    rewrite(json, &fixed_time().to_rfc3339(), rfc3339)
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

/// Outcome of inspecting the front of the stub's receive buffer.
enum Frame {
    /// A complete RESP command occupying this many bytes.
    Complete(usize),
    /// A well-formed prefix: more bytes are needed.
    Incomplete,
    /// Not a RESP array. The stub closes the connection so the client fails
    /// fast instead of awaiting a reply that will never come.
    Malformed,
}

/// Classify the front of `buf` as one RESP command (`*N` followed by N bulk
/// strings), a partial command, or garbage.
fn resp_frame(buf: &[u8]) -> Frame {
    /// `Ok(None)` means the line has not fully arrived yet.
    fn line<'a>(buf: &'a [u8], pos: &mut usize) -> Result<Option<&'a str>, ()> {
        let rest = &buf[*pos..];
        let Some(end) = rest.windows(2).position(|w| w == b"\r\n") else {
            return Ok(None);
        };
        *pos += end + 2;
        std::str::from_utf8(&rest[..end]).map(Some).map_err(|_| ())
    }

    fn header(l: &str, prefix: char) -> Result<usize, ()> {
        l.strip_prefix(prefix)
            .ok_or(())?
            .parse::<usize>()
            .map_err(|_| ())
    }

    let mut pos = 0;
    let argc = match line(buf, &mut pos).map(|l| l.map(|l| header(l, '*'))) {
        Ok(Some(Ok(argc))) => argc,
        Ok(None) => return Frame::Incomplete,
        _ => return Frame::Malformed,
    };
    for _ in 0..argc {
        let len = match line(buf, &mut pos).map(|l| l.map(|l| header(l, '$'))) {
            Ok(Some(Ok(len))) => len,
            Ok(None) => return Frame::Incomplete,
            _ => return Frame::Malformed,
        };
        if buf.len() < pos + len + 2 {
            return Frame::Incomplete;
        }
        pos += len + 2;
    }
    Frame::Complete(pos)
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
            // Connections are owned by the accept loop's `JoinSet`, so aborting
            // the loop on drop tears down every parked reader with it.
            let mut connections = tokio::task::JoinSet::new();
            let mut consecutive_errors = 0;
            loop {
                // A transient accept error (EMFILE under parallel tests) must not
                // kill the stub: keep serving so later connections still succeed.
                // A persistent one gives up instead of spinning, so the client
                // sees a connection refusal rather than a hung runtime slot.
                let Ok((mut socket, _)) = listener.accept().await else {
                    consecutive_errors += 1;
                    if consecutive_errors > 16 {
                        return;
                    }
                    // Back off rather than yield-spin: the usual cause is fd
                    // exhaustion, which needs another task to make progress and
                    // release one. 16 x 10ms also keeps the give-up path from
                    // firing in the microseconds it takes to burn the retries.
                    tokio::time::sleep(std::time::Duration::from_millis(10)).await;
                    continue;
                };
                consecutive_errors = 0;
                // Reap connections that have already hung up, so a stub kept
                // alive across many client connections does not grow the set
                // for the whole test.
                while connections.try_join_next().is_some() {}
                connections.spawn(async move {
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
                        let mut malformed = false;
                        loop {
                            match resp_frame(&pending) {
                                Frame::Complete(len) => {
                                    pending.drain(..len);
                                    replies.push_str(&format!(":{integer_reply}\r\n"));
                                }
                                Frame::Incomplete => break,
                                Frame::Malformed => {
                                    malformed = true;
                                    break;
                                }
                            }
                        }
                        if !replies.is_empty()
                            && socket.write_all(replies.as_bytes()).await.is_err()
                        {
                            break;
                        }
                        // Hang up instead of leaving the client awaiting a reply
                        // to something this stub cannot parse.
                        if malformed {
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

#[cfg(test)]
mod form_params_tests {
    use super::*;

    #[test]
    fn decodes_escapes_and_leaves_a_truncated_escape_alone() {
        let params =
            form_params("Action=Publish&Message=%7B%22a%22%3A1%7D&Note=a+b&Odd=100%25&Cut=%4");

        assert_eq!(params["Action"], "Publish");
        assert_eq!(params["Message"], r#"{"a":1}"#);
        assert_eq!(params["Note"], "a b");
        assert_eq!(params["Odd"], "100%", "a trailing escape decodes normally");
        assert_eq!(
            params["Cut"], "%4",
            "an escape cut short is kept verbatim rather than panicking"
        );
    }
}

#[cfg(test)]
mod fixture_rewrite_tests {
    use super::*;

    #[test]
    fn trashed_and_dated_rewrite_the_file_fixture() {
        let file = file_item_json(uuid_from(1), uuid_from(2), None);

        assert!(trashed(&file).contains(r#""is_trashed":{"BOOL":true}"#));
        assert!(dated(&file, "2020-01-01T00:00:00+00:00").contains("2020-01-01T00:00:00+00:00"));
        assert!(
            !dated(&file, "2020-01-01T00:00:00+00:00").contains(&fixed_time().to_rfc3339()),
            "every timestamp moves, so nothing is left at the fixed time"
        );
    }

    #[test]
    #[should_panic(expected = "fixture has no")]
    fn rewriting_an_absent_pattern_fails_loudly() {
        // A silent no-op here would leave a test asserting against the
        // unmodified fixture, which is the failure mode this guards.
        rewrite(r#"{"a":1}"#, "not-present", "x");
    }
}

#[cfg(test)]
mod redis_stub_tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    #[test]
    fn resp_frame_separates_complete_partial_and_malformed_input() {
        let exists = b"*2\r\n$6\r\nEXISTS\r\n$3\r\nkey\r\n";
        assert!(matches!(resp_frame(exists), Frame::Complete(25)));

        // An argument whose bytes start with '*' is skipped by its length,
        // not mistaken for a second command header.
        let starry = b"*2\r\n$6\r\nEXISTS\r\n$3\r\n*ab\r\n";
        assert!(matches!(resp_frame(starry), Frame::Complete(25)));

        for partial in [
            &exists[..2],  // header not terminated
            &exists[..10], // argument body still arriving
            &exists[..exists.len() - 1],
        ] {
            assert!(
                matches!(resp_frame(partial), Frame::Incomplete),
                "{:?} is a prefix, not a whole command",
                std::str::from_utf8(partial).unwrap()
            );
        }

        for garbage in [b"PING\r\n".as_slice(), b"*x\r\n", b"*1\r\nPING\r\n"] {
            assert!(
                matches!(resp_frame(garbage), Frame::Malformed),
                "{:?} is not a RESP array",
                std::str::from_utf8(garbage).unwrap()
            );
        }
    }

    #[tokio::test]
    async fn dropping_the_stub_tears_down_live_connections() {
        let stub = RedisStub::start(0).await;
        let mut sock = tokio::net::TcpStream::connect(stub.url.trim_start_matches("redis://"))
            .await
            .unwrap();
        drop(stub);

        // The connection task is parked in `read`; aborting the accept loop must
        // take it with it rather than leaking it for the runtime's lifetime.
        let mut buf = [0u8; 4];
        let closed = tokio::time::timeout(std::time::Duration::from_secs(5), sock.read(&mut buf))
            .await
            .expect("the socket closes instead of staying open");
        assert!(matches!(closed, Ok(0) | Err(_)), "{closed:?}");
    }

    #[tokio::test]
    async fn stub_answers_each_whole_command_and_hangs_up_on_garbage() {
        let stub = RedisStub::start(1).await;
        let addr = stub.url.trim_start_matches("redis://").to_string();

        let mut sock = tokio::net::TcpStream::connect(&addr).await.unwrap();
        // Two pipelined commands, delivered in three writes that split them at
        // arbitrary points: still exactly two replies, in order.
        for part in [
            "*2\r\n$6\r\nEXISTS\r\n$1\r\na\r\n*2\r\n$6\r\nEX",
            "ISTS\r\n$1\r\n",
            "b\r\n",
        ] {
            sock.write_all(part.as_bytes()).await.unwrap();
        }
        let mut buf = [0u8; 16];
        let mut seen = Vec::new();
        while seen.len() < 8 {
            let n = sock.read(&mut buf).await.unwrap();
            assert_ne!(n, 0, "the stub closed on well-formed input");
            seen.extend_from_slice(&buf[..n]);
        }
        assert_eq!(seen, b":1\r\n:1\r\n");

        let mut garbage_sock = tokio::net::TcpStream::connect(&addr).await.unwrap();
        garbage_sock.write_all(b"PING\r\n").await.unwrap();
        assert_eq!(
            garbage_sock.read(&mut buf).await.unwrap(),
            0,
            "unparseable input closes the connection instead of hanging the client"
        );
    }
}
