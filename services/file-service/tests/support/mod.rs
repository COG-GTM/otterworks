//! Shared helpers for the file-service integration tests.
//!
//! Everything here is offline and deterministic: AWS is faked at the HTTP
//! boundary with `StaticReplayClient`, Redis is a loopback RESP stub, and no
//! test reads the wall clock for an assertion.

#![allow(dead_code)]

use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use aws_sdk_dynamodb::config::{BehaviorVersion, Credentials, Region};
use aws_smithy_runtime::client::http::test_util::{ReplayEvent, StaticReplayClient};
use aws_smithy_types::body::SdkBody;
use chrono::{DateTime, Utc};
use file_service::metadata::MetadataClient;
use file_service::models::{FileMetadata, FileShare, FileVersion, Folder, SharePermission};
use file_service::storage::S3Client;
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::TcpListener;
use uuid::Uuid;

/// `std::env` is process-global and `cargo test` is multi-threaded.
pub static ENV_LOCK: Mutex<()> = Mutex::new(());

/// Run `f` with `vars` applied to the process environment, restoring the
/// previous values (and releasing the lock) afterwards.
pub fn with_env<T>(vars: &[(&str, Option<&str>)], f: impl FnOnce() -> T) -> T {
    let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
    let saved: Vec<(String, Option<String>)> = vars
        .iter()
        .map(|(k, _)| ((*k).to_string(), std::env::var(k).ok()))
        .collect();
    for (k, v) in vars {
        match v {
            Some(v) => std::env::set_var(k, v),
            None => std::env::remove_var(k),
        }
    }
    let out = f();
    for (k, v) in saved {
        match v {
            Some(v) => std::env::set_var(&k, v),
            None => std::env::remove_var(&k),
        }
    }
    out
}

/// A fixed timestamp so no assertion depends on the clock.
pub fn fixed_time() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-01-02T03:04:05+00:00")
        .expect("valid rfc3339")
        .with_timezone(&Utc)
}

fn replay_client(responses: Vec<(u16, String)>) -> StaticReplayClient {
    let events = responses
        .into_iter()
        .map(|(status, body)| {
            ReplayEvent::new(
                http::Request::builder()
                    .method("POST")
                    .uri("https://replay.invalid/")
                    .body(SdkBody::empty())
                    .expect("valid placeholder request"),
                http::Response::builder()
                    .status(status)
                    .body(SdkBody::from(body))
                    .expect("valid replayed response"),
            )
        })
        .collect();
    StaticReplayClient::new(events)
}

/// An `S3Client` whose HTTP calls are answered, in order, by `responses`.
pub fn fake_s3(responses: Vec<(u16, String)>) -> (S3Client, StaticReplayClient) {
    let http = replay_client(responses);
    let conf = aws_sdk_s3::Config::builder()
        .behavior_version(BehaviorVersion::latest())
        .region(Region::new("us-east-1"))
        .credentials_provider(Credentials::for_tests())
        .http_client(http.clone())
        .build();
    (
        S3Client {
            client: aws_sdk_s3::Client::from_conf(conf),
            bucket: "test-bucket".to_string(),
        },
        http,
    )
}

/// A `MetadataClient` whose DynamoDB calls are answered, in order, by `responses`.
pub fn fake_metadata(responses: Vec<(u16, String)>) -> (MetadataClient, StaticReplayClient) {
    let http = replay_client(responses);
    let conf = aws_sdk_dynamodb::Config::builder()
        .behavior_version(BehaviorVersion::latest())
        .region(Region::new("us-east-1"))
        .credentials_provider(Credentials::for_tests())
        .http_client(http.clone())
        .build();
    (
        MetadataClient {
            client: aws_sdk_dynamodb::Client::from_conf(conf),
            files_table: "files-t".into(),
            folders_table: "folders-t".into(),
            versions_table: "versions-t".into(),
            shares_table: "shares-t".into(),
        },
        http,
    )
}

/// An empty `200 OK` DynamoDB response (PutItem / UpdateItem / DeleteItem).
pub fn dynamo_ok() -> (u16, String) {
    (200, "{}".to_string())
}

pub fn dynamo_body(body: String) -> (u16, String) {
    (200, body)
}

/// A DynamoDB `ConditionalCheckFailedException` error response.
pub fn dynamo_conditional_check_failed() -> (u16, String) {
    (
        400,
        r#"{"__type":"com.amazonaws.dynamodb.v20120810#ConditionalCheckFailedException","message":"The conditional request failed"}"#
            .to_string(),
    )
}

/// A generic DynamoDB server error.
pub fn dynamo_server_error() -> (u16, String) {
    (
        500,
        r#"{"__type":"com.amazonaws.dynamodb.v20120810#InternalServerError","message":"boom"}"#
            .to_string(),
    )
}

/// A generic S3 server error.
pub fn s3_server_error() -> (u16, String) {
    (
        500,
        "<Error><Code>InternalError</Code><Message>boom</Message></Error>".to_string(),
    )
}

pub fn s3_ok(body: &str) -> (u16, String) {
    (200, body.to_string())
}

pub fn sample_file(id: Uuid, owner: Uuid) -> FileMetadata {
    FileMetadata {
        id,
        name: "report.pdf".into(),
        mime_type: "application/pdf".into(),
        size_bytes: 1024,
        s3_key: format!("files/{owner}/{id}"),
        folder_id: None,
        owner_id: owner,
        version: 1,
        is_trashed: false,
        created_at: fixed_time(),
        updated_at: fixed_time(),
    }
}

pub fn sample_folder(id: Uuid, owner: Uuid) -> Folder {
    Folder {
        id,
        name: "Finance".into(),
        parent_id: None,
        owner_id: owner,
        created_at: fixed_time(),
        updated_at: fixed_time(),
    }
}

pub fn sample_version(file_id: Uuid, owner: Uuid) -> FileVersion {
    FileVersion {
        file_id,
        version: 2,
        s3_key: format!("files/{owner}/{file_id}"),
        size_bytes: 2048,
        created_by: owner,
        created_at: fixed_time(),
    }
}

pub fn sample_share(id: Uuid, file_id: Uuid, user: Uuid) -> FileShare {
    FileShare {
        id,
        file_id,
        shared_with: user,
        permission: SharePermission::Viewer,
        shared_by: user,
        created_at: fixed_time(),
    }
}

/// A DynamoDB item map (as JSON) for a file, matching what `put_file` writes.
pub fn file_item_json(file: &FileMetadata) -> String {
    let folder = match &file.folder_id {
        Some(f) => format!(r#","folder_id":{{"S":"{f}"}}"#),
        None => String::new(),
    };
    format!(
        r#"{{"id":{{"S":"{id}"}},"name":{{"S":"{name}"}},"mime_type":{{"S":"{mime}"}},"size_bytes":{{"N":"{size}"}},"s3_key":{{"S":"{key}"}},"owner_id":{{"S":"{owner}"}},"version":{{"N":"{version}"}},"is_trashed":{{"BOOL":{trashed}}},"created_at":{{"S":"{created}"}},"updated_at":{{"S":"{updated}"}}{folder}}}"#,
        id = file.id,
        name = file.name,
        mime = file.mime_type,
        size = file.size_bytes,
        key = file.s3_key,
        owner = file.owner_id,
        version = file.version,
        trashed = file.is_trashed,
        created = file.created_at.to_rfc3339(),
        updated = file.updated_at.to_rfc3339(),
    )
}

pub fn folder_item_json(folder: &Folder) -> String {
    let parent = match &folder.parent_id {
        Some(p) => format!(r#","parent_id":{{"S":"{p}"}}"#),
        None => String::new(),
    };
    format!(
        r#"{{"id":{{"S":"{id}"}},"name":{{"S":"{name}"}},"owner_id":{{"S":"{owner}"}},"created_at":{{"S":"{created}"}},"updated_at":{{"S":"{updated}"}}{parent}}}"#,
        id = folder.id,
        name = folder.name,
        owner = folder.owner_id,
        created = folder.created_at.to_rfc3339(),
        updated = folder.updated_at.to_rfc3339(),
    )
}

pub fn version_item_json(version: &FileVersion) -> String {
    format!(
        r#"{{"file_id":{{"S":"{file}"}},"version":{{"N":"{v}"}},"s3_key":{{"S":"{key}"}},"size_bytes":{{"N":"{size}"}},"created_by":{{"S":"{by}"}},"created_at":{{"S":"{created}"}}}}"#,
        file = version.file_id,
        v = version.version,
        key = version.s3_key,
        size = version.size_bytes,
        by = version.created_by,
        created = version.created_at.to_rfc3339(),
    )
}

pub fn share_item_json(share: &FileShare) -> String {
    format!(
        r#"{{"id":{{"S":"{id}"}},"file_id":{{"S":"{file}"}},"shared_with":{{"S":"{with}"}},"permission":{{"S":"{perm}"}},"shared_by":{{"S":"{by}"}},"created_at":{{"S":"{created}"}}}}"#,
        id = share.id,
        file = share.file_id,
        with = share.shared_with,
        perm = share.permission,
        by = share.shared_by,
        created = share.created_at.to_rfc3339(),
    )
}

// ── Loopback stubs ─────────────────────────────────────────────────────
//
// A couple of clients (`EventPublisher`'s SNS client, the Redis connection
// manager) hold their transport privately, so they cannot be handed a
// `StaticReplayClient`. They get a loopback server on 127.0.0.1 instead: still
// offline, still deterministic, and it records what the client sent.

/// A one-canned-response HTTP/1.1 server bound to an ephemeral loopback port.
pub struct HttpStub {
    pub addr: SocketAddr,
    requests: Arc<Mutex<Vec<String>>>,
}

impl HttpStub {
    pub fn endpoint(&self) -> String {
        format!("http://{}", self.addr)
    }

    /// The raw requests received so far, newest last.
    pub fn requests(&self) -> Vec<String> {
        self.requests
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone()
    }
}

fn reason(status: u16) -> &'static str {
    match status {
        200 => "OK",
        400 => "Bad Request",
        _ => "Internal Server Error",
    }
}

/// Serve `body` with `status` to every request until the test ends.
pub async fn spawn_http_stub(status: u16, body: &'static str) -> HttpStub {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind loopback");
    let addr = listener.local_addr().expect("local addr");
    let requests: Arc<Mutex<Vec<String>>> = Arc::new(Mutex::new(Vec::new()));
    let sink = Arc::clone(&requests);

    tokio::spawn(async move {
        while let Ok((mut sock, _)) = listener.accept().await {
            let sink = Arc::clone(&sink);
            tokio::spawn(async move {
                let mut buf = Vec::new();
                let mut chunk = [0u8; 4096];
                loop {
                    match sock.read(&mut chunk).await {
                        Ok(0) | Err(_) => break,
                        Ok(n) => buf.extend_from_slice(&chunk[..n]),
                    }
                    if let Some(head_end) = find_subslice(&buf, b"\r\n\r\n") {
                        let head = String::from_utf8_lossy(&buf[..head_end]).to_lowercase();
                        let want = head
                            .lines()
                            .find_map(|l| l.strip_prefix("content-length:"))
                            .and_then(|v| v.trim().parse::<usize>().ok())
                            .unwrap_or(0);
                        if buf.len() >= head_end + 4 + want {
                            break;
                        }
                    }
                }
                sink.lock()
                    .unwrap_or_else(|e| e.into_inner())
                    .push(String::from_utf8_lossy(&buf).into_owned());
                let response = format!(
                    "HTTP/1.1 {status} {}\r\nContent-Type: text/xml\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    reason(status),
                    body.len()
                );
                let _ = sock.write_all(response.as_bytes()).await;
                let _ = sock.shutdown().await;
            });
        }
    });

    HttpStub { addr, requests }
}

fn find_subslice(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack
        .windows(needle.len())
        .position(|window| window == needle)
}

/// A loopback Redis that answers `EXISTS` with `exists` and everything else
/// with `+OK`. Enough for the chaos-flag lookup in `upload_file`.
pub async fn spawn_redis_stub(exists: bool) -> SocketAddr {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("bind loopback");
    let addr = listener.local_addr().expect("local addr");

    tokio::spawn(async move {
        while let Ok((mut sock, _)) = listener.accept().await {
            tokio::spawn(async move {
                let mut buf: Vec<u8> = Vec::new();
                let mut chunk = [0u8; 1024];
                loop {
                    match sock.read(&mut chunk).await {
                        Ok(0) | Err(_) => return,
                        Ok(n) => buf.extend_from_slice(&chunk[..n]),
                    }
                    while let Some((args, consumed)) = parse_resp_command(&buf) {
                        buf.drain(..consumed);
                        let reply = match args.first().map(|a| a.to_uppercase()).as_deref() {
                            Some("EXISTS") => {
                                format!(":{}\r\n", i32::from(exists))
                            }
                            Some("PING") => "+PONG\r\n".to_string(),
                            _ => "+OK\r\n".to_string(),
                        };
                        if sock.write_all(reply.as_bytes()).await.is_err() {
                            return;
                        }
                    }
                }
            });
        }
    });

    addr
}

/// Parse one RESP array command, returning its arguments and the bytes consumed.
fn parse_resp_command(buf: &[u8]) -> Option<(Vec<String>, usize)> {
    if buf.first() != Some(&b'*') {
        return None;
    }
    let mut pos = 0;
    let line = |buf: &[u8], pos: &mut usize| -> Option<String> {
        let end = find_subslice(&buf[*pos..], b"\r\n")? + *pos;
        let out = String::from_utf8_lossy(&buf[*pos..end]).into_owned();
        *pos = end + 2;
        Some(out)
    };
    let count: usize = line(buf, &mut pos)?[1..].parse().ok()?;
    let mut args = Vec::with_capacity(count);
    for _ in 0..count {
        let header = line(buf, &mut pos)?;
        let len: usize = header[1..].parse().ok()?;
        if buf.len() < pos + len + 2 {
            return None;
        }
        args.push(String::from_utf8_lossy(&buf[pos..pos + len]).into_owned());
        pos += len + 2;
    }
    Some((args, pos))
}

/// Wrap DynamoDB item JSON in a `GetItem` response.
pub fn get_item_response(item: &str) -> String {
    format!(r#"{{"Item":{item}}}"#)
}

/// Wrap DynamoDB item JSON in a `Scan` / `Query` response.
pub fn items_response(items: &[String]) -> String {
    format!(
        r#"{{"Items":[{}],"Count":{},"ScannedCount":{}}}"#,
        items.join(","),
        items.len(),
        items.len()
    )
}
