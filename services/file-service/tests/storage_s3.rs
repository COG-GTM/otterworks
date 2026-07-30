//! `S3Client` against a faked S3 HTTP boundary — no LocalStack, no network.

mod common;

use bytes::Bytes;
use common::*;
use file_service::errors::ServiceError;

#[tokio::test]
async fn upload_object_puts_the_body_in_the_configured_bucket() {
    let (s3, http) = s3_client(vec![s3_ok("")]);

    s3.upload_object(
        "files/owner/a.txt",
        Bytes::from_static(b"hello"),
        "text/plain",
    )
    .await
    .unwrap();

    let sent = http.actual_requests().next().expect("one request");
    assert_eq!(sent.method(), "PUT");
    assert!(sent.uri().contains(BUCKET), "{}", sent.uri());
    assert!(sent.uri().contains("files/owner/a.txt"), "{}", sent.uri());
    assert_eq!(sent.headers().get("content-type"), Some("text/plain"));
    assert_eq!(sent.body().bytes(), Some(&b"hello"[..]));
}

#[tokio::test]
async fn upload_object_maps_s3_failures() {
    let (s3, _http) = s3_client(vec![s3_err(500, "InternalError")]);

    let err = s3
        .upload_object("k", Bytes::from_static(b"hi"), "text/plain")
        .await
        .expect_err("a 500 is an error");

    match err {
        ServiceError::S3Error(message) => assert!(message.starts_with("upload failed")),
        other => panic!("expected S3Error, got {other:?}"),
    }
}

#[tokio::test]
async fn download_object_returns_the_body() {
    let (s3, http) = s3_client(vec![s3_ok("file contents")]);

    let body = s3.download_object("files/owner/a.txt").await.unwrap();

    assert_eq!(body, Bytes::from_static(b"file contents"));
    let sent = http.actual_requests().next().expect("one request");
    assert_eq!(sent.method(), "GET");
    assert!(sent.uri().contains("files/owner/a.txt"), "{}", sent.uri());
}

#[tokio::test]
async fn download_object_maps_a_missing_key() {
    let (s3, _http) = s3_client(vec![s3_err(404, "NoSuchKey")]);

    let err = s3.download_object("missing").await.expect_err("404");

    match err {
        ServiceError::S3Error(message) => assert!(message.starts_with("download failed")),
        other => panic!("expected S3Error, got {other:?}"),
    }
}

#[tokio::test]
async fn presigned_download_url_is_signed_and_needs_no_request() {
    let (s3, http) = s3_client(vec![]);

    let url = s3
        .presigned_download_url("files/owner/a.txt", 900)
        .await
        .unwrap();

    assert!(url.contains(BUCKET), "{url}");
    assert!(url.contains("files/owner/a.txt"), "{url}");
    assert!(url.contains("X-Amz-Signature="), "{url}");
    assert!(url.contains("X-Amz-Expires=900"), "{url}");
    assert_eq!(http.actual_requests().count(), 0, "presigning is offline");
}

#[tokio::test]
async fn presigned_download_url_rejects_an_out_of_range_expiry() {
    let (s3, _http) = s3_client(vec![]);

    // S3 caps presigned URLs at one week.
    let err = s3
        .presigned_download_url("k", 60 * 60 * 24 * 8)
        .await
        .expect_err("eight days is too long");

    match err {
        ServiceError::S3Error(message) => assert!(message.starts_with("presign config error")),
        other => panic!("expected S3Error, got {other:?}"),
    }
}

#[tokio::test]
async fn delete_object_sends_a_delete() {
    let (s3, http) = s3_client(vec![s3_ok("")]);

    s3.delete_object("files/owner/a.txt").await.unwrap();

    let sent = http.actual_requests().next().expect("one request");
    assert_eq!(sent.method(), "DELETE");
    assert!(sent.uri().contains("files/owner/a.txt"), "{}", sent.uri());
}

#[tokio::test]
async fn delete_object_maps_s3_failures() {
    let (s3, _http) = s3_client(vec![s3_err(403, "AccessDenied")]);

    let err = s3.delete_object("k").await.expect_err("403");

    match err {
        ServiceError::S3Error(message) => assert!(message.starts_with("delete failed")),
        other => panic!("expected S3Error, got {other:?}"),
    }
}

#[tokio::test]
async fn copy_object_prefixes_the_source_with_the_bucket() {
    let (s3, http) = s3_client(vec![s3_ok(
        "<CopyObjectResult><ETag>\"abc\"</ETag></CopyObjectResult>",
    )]);

    s3.copy_object("files/owner/v1", "files/owner/v2")
        .await
        .unwrap();

    let sent = http.actual_requests().next().expect("one request");
    assert_eq!(sent.method(), "PUT");
    assert_eq!(
        sent.headers().get("x-amz-copy-source"),
        Some("test-bucket/files/owner/v1")
    );
    assert!(sent.uri().contains("files/owner/v2"), "{}", sent.uri());
}

#[tokio::test]
async fn copy_object_maps_s3_failures() {
    let (s3, _http) = s3_client(vec![s3_err(404, "NoSuchKey")]);

    let err = s3.copy_object("a", "b").await.expect_err("404");

    match err {
        ServiceError::S3Error(message) => assert!(message.starts_with("copy failed")),
        other => panic!("expected S3Error, got {other:?}"),
    }
}

#[tokio::test]
async fn new_uses_the_configured_bucket_and_endpoint() {
    let aws = file_service::config::AwsConfig {
        region: "us-east-1".into(),
        endpoint_url: None,
        s3_bucket: "configured-bucket".into(),
        dynamodb_table: "t".into(),
        dynamodb_folders_table: "f".into(),
        dynamodb_versions_table: "v".into(),
        dynamodb_shares_table: "s".into(),
    };

    let default_endpoint = file_service::storage::S3Client::new(&aws).await;
    assert_eq!(default_endpoint.bucket, "configured-bucket");

    let custom_endpoint = file_service::storage::S3Client::new(&file_service::config::AwsConfig {
        endpoint_url: Some("http://localstack:4566".into()),
        ..aws
    })
    .await;
    // Clone is used to hand the client to every actix worker.
    assert_eq!(custom_endpoint.clone().bucket, "configured-bucket");
}
