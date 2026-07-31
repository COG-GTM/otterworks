use aws_sdk_s3::presigning::PresigningConfig;
use bytes::Bytes;
use std::time::Duration;

use crate::config::AwsConfig;
use crate::errors::ServiceError;

/// S3 client for file blob operations.
#[derive(Clone)]
pub struct S3Client {
    pub client: aws_sdk_s3::Client,
    pub bucket: String,
}

impl S3Client {
    pub async fn new(config: &AwsConfig) -> Self {
        let mut aws_config_builder = aws_config::defaults(aws_config::BehaviorVersion::latest())
            .region(aws_config::Region::new(config.region.clone()));

        if let Some(endpoint) = &config.endpoint_url {
            aws_config_builder = aws_config_builder.endpoint_url(endpoint);
        }

        let aws_config = aws_config_builder.load().await;
        let s3_config = aws_sdk_s3::config::Builder::from(&aws_config)
            .force_path_style(true)
            .build();
        let client = aws_sdk_s3::Client::from_conf(s3_config);

        Self {
            client,
            bucket: config.s3_bucket.clone(),
        }
    }

    /// Upload file content to S3.
    pub async fn upload_object(
        &self,
        key: &str,
        body: Bytes,
        content_type: &str,
    ) -> Result<(), ServiceError> {
        self.client
            .put_object()
            .bucket(&self.bucket)
            .key(key)
            .body(body.into())
            .content_type(content_type)
            .send()
            .await
            .map_err(|e| ServiceError::S3Error(format!("upload failed: {e}")))?;

        tracing::info!(key = %key, bucket = %self.bucket, "Uploaded object to S3");
        Ok(())
    }

    /// Download file content from S3.
    pub async fn download_object(&self, key: &str) -> Result<Bytes, ServiceError> {
        let resp = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| ServiceError::S3Error(format!("download failed: {e}")))?;

        let body = resp
            .body
            .collect()
            .await
            .map_err(|e| ServiceError::S3Error(format!("body read failed: {e}")))?;

        Ok(body.into_bytes())
    }

    /// Generate a presigned download URL.
    pub async fn presigned_download_url(
        &self,
        key: &str,
        expires_in_secs: u64,
    ) -> Result<String, ServiceError> {
        let presigning = PresigningConfig::expires_in(Duration::from_secs(expires_in_secs))
            .map_err(|e| ServiceError::S3Error(format!("presign config error: {e}")))?;

        let presigned = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .presigned(presigning)
            .await
            .map_err(|e| ServiceError::S3Error(format!("presign failed: {e}")))?;

        Ok(presigned.uri().to_string())
    }

    /// Delete an object from S3.
    pub async fn delete_object(&self, key: &str) -> Result<(), ServiceError> {
        self.client
            .delete_object()
            .bucket(&self.bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| ServiceError::S3Error(format!("delete failed: {e}")))?;

        tracing::info!(key = %key, "Deleted object from S3");
        Ok(())
    }

    /// Copy an object within S3 (used for versioning).
    pub async fn copy_object(&self, source_key: &str, dest_key: &str) -> Result<(), ServiceError> {
        let copy_source = format!("{}/{}", self.bucket, source_key);
        self.client
            .copy_object()
            .bucket(&self.bucket)
            .copy_source(&copy_source)
            .key(dest_key)
            .send()
            .await
            .map_err(|e| ServiceError::S3Error(format!("copy failed: {e}")))?;

        tracing::info!(source = %source_key, dest = %dest_key, "Copied object in S3");
        Ok(())
    }
}

#[cfg(test)]
mod storage_tests {
    use super::*;
    use crate::test_support::{
        aws_config_fixture, offline_aws_env, replay, s3_client, with_env_blocking,
    };

    const S3_ERROR_BODY: &str = "<Error><Code>InternalError</Code><Message>boom</Message></Error>";

    fn ok(body: &str) -> (u16, String) {
        (200, body.to_string())
    }

    fn server_error() -> (u16, String) {
        (500, S3_ERROR_BODY.to_string())
    }

    #[test]
    fn new_targets_the_configured_region_and_bucket() {
        let mut config = aws_config_fixture();
        config.region = "eu-west-1".into();
        config.s3_bucket = "configured-bucket".into();

        let (bucket, url) = with_env_blocking(&offline_aws_env(), async {
            let client = S3Client::new(&config).await;
            let url = client
                .presigned_download_url("some/key", 60)
                .await
                .expect("presigning is offline");
            (client.bucket.clone(), url)
        });

        assert_eq!(bucket, "configured-bucket");
        assert!(
            url.starts_with("https://s3.eu-west-1.amazonaws.com/configured-bucket/some/key"),
            "path-style URL against the configured region: {url}"
        );
    }

    #[test]
    fn new_honours_a_custom_endpoint_url() {
        let mut config = aws_config_fixture();
        config.endpoint_url = Some("http://localstack:4566".into());

        let url = with_env_blocking(&offline_aws_env(), async {
            let client = S3Client::new(&config).await;
            client
                .presigned_download_url("some/key", 60)
                .await
                .expect("presigning is offline")
        });

        assert!(
            url.starts_with("http://localstack:4566/test-bucket/some/key"),
            "requests are addressed to the override endpoint: {url}"
        );
    }

    #[tokio::test]
    async fn upload_object_puts_the_body_at_the_configured_bucket_and_key() {
        let http = replay(vec![ok("")]);
        let s3 = s3_client(http.clone());

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
    async fn upload_object_maps_s3_failure_to_a_service_error() {
        let s3 = s3_client(replay(vec![server_error()]));

        let err = s3
            .upload_object("some/key", Bytes::from_static(b"hello"), "text/plain")
            .await
            .expect_err("500 should surface as ServiceError");

        assert!(matches!(err, ServiceError::S3Error(_)), "got {err:?}");
        assert!(err.to_string().contains("upload failed"), "{err}");
    }

    #[tokio::test]
    async fn download_object_returns_the_object_body() {
        let http = replay(vec![ok("file-contents")]);
        let s3 = s3_client(http.clone());

        let body = s3.download_object("some/key").await.expect("download");

        assert_eq!(body, Bytes::from_static(b"file-contents"));
        let sent = http.actual_requests().next().expect("one request");
        assert_eq!(sent.method(), "GET");
        assert!(sent.uri().contains("/some/key"), "{}", sent.uri());
    }

    #[tokio::test]
    async fn download_object_maps_s3_failure_to_a_service_error() {
        let s3 = s3_client(replay(vec![server_error()]));

        let err = s3
            .download_object("missing/key")
            .await
            .expect_err("500 should surface as ServiceError");

        assert!(matches!(err, ServiceError::S3Error(_)), "got {err:?}");
        assert!(err.to_string().contains("download failed"), "{err}");
    }

    #[tokio::test]
    async fn presigned_download_url_points_at_the_object_and_expires() {
        let s3 = s3_client(replay(vec![]));

        let url = s3
            .presigned_download_url("some/key", 900)
            .await
            .expect("presigning is offline");

        assert!(url.contains("test-bucket"), "{url}");
        assert!(url.contains("/some/key"), "{url}");
        assert!(url.contains("X-Amz-Expires=900"), "{url}");
        assert!(url.contains("X-Amz-Signature="), "{url}");
    }

    #[tokio::test]
    async fn presigned_download_url_rejects_an_expiry_beyond_one_week() {
        let s3 = s3_client(replay(vec![]));

        let err = s3
            .presigned_download_url("some/key", 60 * 60 * 24 * 8)
            .await
            .expect_err("more than 7 days is not a valid presign duration");

        assert!(matches!(err, ServiceError::S3Error(_)), "got {err:?}");
        assert!(err.to_string().contains("presign config error"), "{err}");
    }

    #[tokio::test]
    async fn delete_object_issues_a_delete_for_the_key() {
        let http = replay(vec![(204, String::new())]);
        let s3 = s3_client(http.clone());

        s3.delete_object("some/key").await.expect("delete");

        let sent = http.actual_requests().next().expect("one request");
        assert_eq!(sent.method(), "DELETE");
        assert!(sent.uri().contains("/some/key"), "{}", sent.uri());
    }

    #[tokio::test]
    async fn delete_object_maps_s3_failure_to_a_service_error() {
        let s3 = s3_client(replay(vec![server_error()]));

        let err = s3
            .delete_object("some/key")
            .await
            .expect_err("500 should surface as ServiceError");

        assert!(matches!(err, ServiceError::S3Error(_)), "got {err:?}");
        assert!(err.to_string().contains("delete failed"), "{err}");
    }

    #[tokio::test]
    async fn copy_object_sends_a_bucket_qualified_copy_source() {
        let http = replay(vec![ok(
            "<CopyObjectResult><ETag>\"abc\"</ETag></CopyObjectResult>",
        )]);
        let s3 = s3_client(http.clone());

        s3.copy_object("v1/key", "v2/key").await.expect("copy");

        let sent = http.actual_requests().next().expect("one request");
        assert_eq!(sent.method(), "PUT");
        assert!(sent.uri().contains("/v2/key"), "{}", sent.uri());
        assert_eq!(
            sent.headers().get("x-amz-copy-source"),
            Some("test-bucket/v1/key"),
            "copy source is prefixed with the bucket"
        );
    }

    #[tokio::test]
    async fn copy_object_maps_s3_failure_to_a_service_error() {
        let s3 = s3_client(replay(vec![server_error()]));

        let err = s3
            .copy_object("v1/key", "v2/key")
            .await
            .expect_err("500 should surface as ServiceError");

        assert!(matches!(err, ServiceError::S3Error(_)), "got {err:?}");
        assert!(err.to_string().contains("copy failed"), "{err}");
    }

    #[tokio::test]
    async fn s3_client_is_cloneable_and_keeps_its_bucket() {
        let s3 = s3_client(replay(vec![]));
        let clone = s3.clone();
        assert_eq!(clone.bucket, s3.bucket);
    }
}
