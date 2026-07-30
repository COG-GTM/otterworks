//! `events::EventPublisher` — event shape, the "no topic configured" no-op,
//! and the SNS publish path against a loopback HTTP stub.

mod support;

use file_service::config::{AwsConfig, SnsConfig};
use file_service::errors::ServiceError;
use file_service::events::{EventPublisher, FileEvent};
use serde_json::Value;
use support::spawn_http_stub;
use uuid::Uuid;

const PUBLISH_OK: &str = r#"<PublishResponse xmlns="http://sns.amazonaws.com/doc/2010-03-31/"><PublishResult><MessageId>a1</MessageId></PublishResult><ResponseMetadata><RequestId>r1</RequestId></ResponseMetadata></PublishResponse>"#;
const PUBLISH_FAILED: &str = r#"<ErrorResponse xmlns="http://sns.amazonaws.com/doc/2010-03-31/"><Error><Type>Sender</Type><Code>NotFound</Code><Message>Topic does not exist</Message></Error></ErrorResponse>"#;

/// The SDK resolves credentials from the environment at request time; this
/// keeps the loopback tests off the credential-provider chain (and off IMDS).
fn use_test_credentials() {
    std::env::set_var("AWS_ACCESS_KEY_ID", "test");
    std::env::set_var("AWS_SECRET_ACCESS_KEY", "test");
    std::env::set_var("AWS_EC2_METADATA_DISABLED", "true");
}

fn aws_config(endpoint: Option<String>) -> AwsConfig {
    AwsConfig {
        region: "us-east-1".into(),
        endpoint_url: endpoint,
        s3_bucket: "b".into(),
        dynamodb_table: "t".into(),
        dynamodb_folders_table: "t".into(),
        dynamodb_versions_table: "t".into(),
        dynamodb_shares_table: "t".into(),
    }
}

async fn publisher(topic_arn: Option<&str>, endpoint: Option<String>) -> EventPublisher {
    use_test_credentials();
    EventPublisher::new(
        &SnsConfig {
            topic_arn: topic_arn.map(str::to_string),
        },
        &aws_config(endpoint),
    )
    .await
}

/// Pull the `Message` parameter out of a captured SNS query-protocol request.
fn published_message(raw: &str) -> Value {
    let body = raw.split("\r\n\r\n").nth(1).expect("request has a body");
    let encoded = body
        .split('&')
        .find_map(|p| p.strip_prefix("Message="))
        .expect("Publish carries a Message parameter");
    let decoded = percent_decode(encoded);
    serde_json::from_str(&decoded).expect("the message is the JSON event")
}

fn publish_params(raw: &str) -> Vec<(String, String)> {
    let body = raw.split("\r\n\r\n").nth(1).expect("request has a body");
    body.split('&')
        .filter_map(|p| p.split_once('='))
        .map(|(k, v)| (k.to_string(), percent_decode(v)))
        .collect()
}

fn percent_decode(input: &str) -> String {
    let bytes = input.replace('+', " ").into_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).expect("ascii");
            out.push(u8::from_str_radix(hex, 16).expect("valid percent escape"));
            i += 3;
        } else {
            out.push(bytes[i]);
            i += 1;
        }
    }
    String::from_utf8(out).expect("utf-8")
}

// ── No topic configured: publishing is a no-op ─────────────────────────

#[tokio::test]
async fn every_event_is_a_no_op_when_no_topic_is_configured() {
    // The endpoint is unroutable on purpose: if any of these tried to publish,
    // the test would fail rather than silently succeed.
    let publisher = publisher(None, Some("http://127.0.0.1:1".into())).await;
    let file = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4();

    publisher
        .file_uploaded(&file, &owner, Some(&folder), "a.txt", "text/plain", 3)
        .await
        .expect("uploaded");
    publisher
        .file_deleted(&file, &owner)
        .await
        .expect("deleted");
    publisher
        .file_shared(&file, &owner, &Uuid::new_v4())
        .await
        .expect("shared");
    publisher
        .file_trashed(&file, &owner)
        .await
        .expect("trashed");
    publisher
        .file_restored(&file, &owner, None, "a.txt", "text/plain", 3)
        .await
        .expect("restored");
    publisher
        .file_updated(&file, &owner, None, "b.txt", "text/plain", 4)
        .await
        .expect("updated");
    publisher
        .file_moved(&file, &owner, Some(&folder))
        .await
        .expect("moved");
}

// ── Publishing to a standard topic ─────────────────────────────────────

#[tokio::test]
async fn file_uploaded_publishes_the_full_event_payload() {
    let stub = spawn_http_stub(200, PUBLISH_OK).await;
    let publisher = publisher(Some("arn:aws:sns:us-east-1:1:files"), Some(stub.endpoint())).await;
    let file = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4();

    publisher
        .file_uploaded(
            &file,
            &owner,
            Some(&folder),
            "report.pdf",
            "application/pdf",
            2048,
        )
        .await
        .expect("publish");

    let raw = stub.requests();
    assert_eq!(raw.len(), 1, "exactly one Publish call");
    let event = published_message(&raw[0]);
    assert_eq!(event["eventType"], "file_uploaded");
    assert_eq!(event["fileId"], file.to_string());
    assert_eq!(event["ownerId"], owner.to_string());
    assert_eq!(event["folderId"], folder.to_string());
    assert_eq!(event["name"], "report.pdf");
    assert_eq!(event["mimeType"], "application/pdf");
    assert_eq!(event["sizeBytes"], 2048);
    assert!(event["sharedWithUserId"].is_null());
    assert!(
        event["timestamp"].as_str().expect("timestamp").len() >= 20,
        "an RFC-3339 timestamp is stamped on the event"
    );

    let params = publish_params(&raw[0]);
    assert!(params
        .iter()
        .any(|(k, v)| k == "TopicArn" && v == "arn:aws:sns:us-east-1:1:files"));
    assert!(
        !params.iter().any(|(k, _)| k == "MessageGroupId"),
        "MessageGroupId is only valid on FIFO topics"
    );
}

#[tokio::test]
async fn each_domain_event_carries_its_own_type_and_fields() {
    let stub = spawn_http_stub(200, PUBLISH_OK).await;
    let publisher = publisher(Some("arn:aws:sns:us-east-1:1:files"), Some(stub.endpoint())).await;
    let file = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let peer = Uuid::new_v4();

    publisher
        .file_deleted(&file, &owner)
        .await
        .expect("deleted");
    publisher
        .file_shared(&file, &owner, &peer)
        .await
        .expect("shared");
    publisher
        .file_trashed(&file, &owner)
        .await
        .expect("trashed");
    publisher
        .file_restored(&file, &owner, None, "a.txt", "text/plain", 7)
        .await
        .expect("restored");
    publisher
        .file_updated(&file, &owner, None, "b.txt", "text/plain", 9)
        .await
        .expect("updated");
    publisher
        .file_moved(&file, &owner, None)
        .await
        .expect("moved");

    let events: Vec<Value> = stub
        .requests()
        .iter()
        .map(|r| published_message(r))
        .collect();
    let types: Vec<&str> = events
        .iter()
        .map(|e| e["eventType"].as_str().expect("eventType"))
        .collect();
    assert_eq!(
        types,
        vec![
            "file_deleted",
            "file_shared",
            "file_trashed",
            "file_restored",
            "file_updated",
            "file_moved"
        ]
    );

    assert_eq!(events[1]["sharedWithUserId"], peer.to_string());
    assert!(
        events[0].get("name").is_none(),
        "delete events omit the file attributes entirely"
    );
    assert_eq!(events[3]["sizeBytes"], 7);
    assert_eq!(events[4]["name"], "b.txt");
    assert!(events[5]["folderId"].is_null(), "moved to the drive root");
}

#[tokio::test]
async fn a_fifo_topic_gets_a_group_and_deduplication_id() {
    let stub = spawn_http_stub(200, PUBLISH_OK).await;
    let publisher = publisher(
        Some("arn:aws:sns:us-east-1:1:files.fifo"),
        Some(stub.endpoint()),
    )
    .await;
    let file = Uuid::new_v4();

    publisher
        .file_trashed(&file, &Uuid::new_v4())
        .await
        .expect("publish");

    let raw = stub.requests();
    let params = publish_params(&raw[0]);
    let group = params
        .iter()
        .find(|(k, _)| k == "MessageGroupId")
        .expect("FIFO topics require a MessageGroupId");
    assert_eq!(group.1, "file_trashed");
    let dedup = params
        .iter()
        .find(|(k, _)| k == "MessageDeduplicationId")
        .expect("FIFO topics require a MessageDeduplicationId");
    let event = published_message(&raw[0]);
    assert_eq!(
        dedup.1,
        format!("{}_{}", file, event["timestamp"].as_str().expect("ts")),
        "dedup id is <fileId>_<timestamp>"
    );
}

#[tokio::test]
async fn a_failed_publish_surfaces_as_an_sns_error() {
    let stub = spawn_http_stub(400, PUBLISH_FAILED).await;
    let publisher = publisher(Some("arn:aws:sns:us-east-1:1:gone"), Some(stub.endpoint())).await;

    let err = publisher
        .file_deleted(&Uuid::new_v4(), &Uuid::new_v4())
        .await
        .expect_err("SNS rejected the publish");

    assert!(matches!(err, ServiceError::SnsError(_)), "{err:?}");
}

// ── Event shape ────────────────────────────────────────────────────────

#[tokio::test]
async fn file_event_serializes_to_camel_case_and_skips_empty_attributes() {
    let event = FileEvent {
        event_type: "file_moved".into(),
        file_id: "f".into(),
        owner_id: "o".into(),
        folder_id: None,
        shared_with: None,
        timestamp: "2026-01-02T03:04:05+00:00".into(),
        name: None,
        mime_type: None,
        size_bytes: None,
    };

    let json: Value = serde_json::from_str(&serde_json::to_string(&event).expect("serialize"))
        .expect("valid JSON");

    assert_eq!(json["eventType"], "file_moved");
    assert_eq!(json["fileId"], "f");
    assert_eq!(json["ownerId"], "o");
    assert!(json["folderId"].is_null(), "folderId is always present");
    assert!(json["sharedWithUserId"].is_null());
    assert!(json.get("name").is_none());
    assert!(json.get("mimeType").is_none());
    assert!(json.get("sizeBytes").is_none());
    assert!(format!("{event:?}").contains("file_moved"));
}

#[tokio::test]
async fn the_publisher_is_cloneable() {
    let publisher = publisher(None, None).await;
    let clone = publisher.clone();
    clone
        .file_deleted(&Uuid::new_v4(), &Uuid::new_v4())
        .await
        .expect("a clone shares the no-topic configuration");
}
