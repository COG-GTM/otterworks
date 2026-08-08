//! `storage::S3Client` against a replayed S3 HTTP boundary — no LocalStack, no
//! network, no credentials beyond `Credentials::for_tests()`.

mod support;

use bytes::Bytes;
use file_service::config::AwsConfig;
use file_service::errors::ServiceError;
use file_service::storage::S3Client;
use support::{fake_s3, s3_ok, s3_server_error};

const COPY_RESULT: &str = r#"<?xml version="1.0" encoding="UTF-8"?><CopyObjectResult><ETag>"abc"</ETag><LastModified>2026-01-02T03:04:05.000Z</LastModified></CopyObjectResult>"#;

#[tokio::test]
async fn upload_object_puts_the_body_at_the_configured_bucket_and_key() {
    let (s3, http) = fake_s3(vec![s3_ok("")]);

    s3.upload_object("some/key", Bytes::from_static(b"hello"), "text/plain")
        .await
        .expect("upload should succeed");

    let sent = http.actual_requests().next().expect("one request");
    assert_eq!(sent.method(), "PUT");
    assert!(sent.uri().contains("test-bucket"), "{}", sent.uri());
    assert!(sent.uri().contains("/some/key"), "{}", sent.uri());
    assert_eq!(
        sent.headers().get("content-type"),
        Some("text/plain"),
        "content type is forwarded to S3"
    );
}

#[tokio::test]
async fn upload_object_maps_s3_failure_to_a_storage_error() {
    let (s3, _http) = fake_s3(vec![s3_server_error()]);

    let err = s3
        .upload_object("some/key", Bytes::from_static(b"hello"), "text/plain")
        .await
        .expect_err("a 500 must surface as a ServiceError");

    assert!(matches!(err, ServiceError::S3Error(_)), "got {err:?}");
    assert!(err.to_string().contains("upload failed"), "{err}");
}

#[tokio::test]
async fn download_object_returns_the_object_body() {
    let (s3, http) = fake_s3(vec![s3_ok("file contents")]);

    let bytes = s3.download_object("some/key").await.expect("download");

    assert_eq!(&bytes[..], b"file contents");
    let sent = http.actual_requests().next().expect("one request");
    assert_eq!(sent.method(), "GET");
    assert!(sent.uri().contains("/some/key"), "{}", sent.uri());
}

#[tokio::test]
async fn download_object_maps_s3_failure_to_a_storage_error() {
    let (s3, _http) = fake_s3(vec![s3_server_error()]);

    let err = s3
        .download_object("some/key")
        .await
        .expect_err("a 500 must surface as a ServiceError");

    assert!(matches!(err, ServiceError::S3Error(_)), "got {err:?}");
    assert!(err.to_string().contains("download failed"), "{err}");
}

#[tokio::test]
async fn delete_object_issues_a_delete_for_the_key() {
    let (s3, http) = fake_s3(vec![(204, String::new())]);

    s3.delete_object("some/key").await.expect("delete");

    let sent = http.actual_requests().next().expect("one request");
    assert_eq!(sent.method(), "DELETE");
    assert!(sent.uri().contains("/some/key"), "{}", sent.uri());
}

#[tokio::test]
async fn delete_object_maps_s3_failure_to_a_storage_error() {
    let (s3, _http) = fake_s3(vec![s3_server_error()]);

    let err = s3
        .delete_object("some/key")
        .await
        .expect_err("a 500 must surface as a ServiceError");

    assert!(err.to_string().contains("delete failed"), "{err}");
}

#[tokio::test]
async fn copy_object_names_the_source_with_the_bucket_prefix() {
    let (s3, http) = fake_s3(vec![s3_ok(COPY_RESULT)]);

    s3.copy_object("v1/key", "v2/key").await.expect("copy");

    let sent = http.actual_requests().next().expect("one request");
    assert_eq!(sent.method(), "PUT");
    assert!(sent.uri().contains("/v2/key"), "{}", sent.uri());
    assert_eq!(
        sent.headers().get("x-amz-copy-source"),
        Some("test-bucket/v1/key"),
        "copy source is <bucket>/<key>"
    );
}

#[tokio::test]
async fn copy_object_maps_s3_failure_to_a_storage_error() {
    let (s3, _http) = fake_s3(vec![s3_server_error()]);

    let err = s3
        .copy_object("v1/key", "v2/key")
        .await
        .expect_err("a 500 must surface as a ServiceError");

    assert!(err.to_string().contains("copy failed"), "{err}");
}

#[tokio::test]
async fn presigned_download_url_is_signed_and_carries_the_requested_expiry() {
    let (s3, http) = fake_s3(vec![]);

    let url = s3
        .presigned_download_url("some/key", 3600)
        .await
        .expect("presigning is offline");

    assert!(url.contains("test-bucket"), "{url}");
    assert!(url.contains("/some/key"), "{url}");
    assert!(url.contains("X-Amz-Expires=3600"), "{url}");
    assert!(url.contains("X-Amz-Signature="), "{url}");
    assert_eq!(
        http.actual_requests().count(),
        0,
        "presigning must not call S3"
    );
}

#[tokio::test]
async fn presigned_download_url_rejects_an_expiry_beyond_the_sigv4_limit() {
    let (s3, _http) = fake_s3(vec![]);

    // SigV4 presigned URLs may not live longer than one week.
    let err = s3
        .presigned_download_url("some/key", 60 * 60 * 24 * 8)
        .await
        .expect_err("8 days is past the SigV4 maximum");

    assert!(err.to_string().contains("presign config error"), "{err}");
}

#[tokio::test]
async fn new_uses_the_configured_bucket_and_honours_a_custom_endpoint() {
    let aws = AwsConfig {
        region: "eu-west-2".into(),
        endpoint_url: Some("http://localhost:4566".into()),
        s3_bucket: "otterworks-files".into(),
        dynamodb_table: "t".into(),
        dynamodb_folders_table: "t".into(),
        dynamodb_versions_table: "t".into(),
        dynamodb_shares_table: "t".into(),
    };
    // Credentials are resolved lazily, at request time — constructing the client
    // touches neither the network nor the credential providers.
    let with_endpoint = S3Client::new(&aws).await;
    let mut plain = aws.clone();
    plain.endpoint_url = None;
    plain.s3_bucket = "other-bucket".into();
    let without_endpoint = S3Client::new(&plain).await;

    assert_eq!(with_endpoint.bucket, "otterworks-files");
    assert_eq!(without_endpoint.bucket, "other-bucket");
    for client in [&with_endpoint, &without_endpoint] {
        assert_eq!(
            client.client.config().region().map(|r| r.as_ref()),
            Some("eu-west-2"),
            "the configured region is applied"
        );
    }
}

#[tokio::test]
async fn clone_shares_the_bucket_configuration() {
    let (s3, _http) = fake_s3(vec![]);
    let clone = s3.clone();
    assert_eq!(clone.bucket, s3.bucket);
}
