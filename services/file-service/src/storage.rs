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
mod tests {
    use super::*;
    use crate::models::test_support::s3_client;

    const S3_ERROR_BODY: &str = "<Error><Code>InternalError</Code><Message>boom</Message></Error>";

    fn fake_s3(
        responses: Vec<(u16, String)>,
    ) -> (
        S3Client,
        aws_smithy_runtime::client::http::test_util::StaticReplayClient,
    ) {
        let (client, http) = s3_client(responses);
        (
            S3Client {
                client,
                bucket: "test-bucket".to_string(),
            },
            http,
        )
    }

    fn aws_config(endpoint: Option<&str>) -> AwsConfig {
        AwsConfig {
            region: "us-east-1".into(),
            endpoint_url: endpoint.map(|e| e.to_string()),
            s3_bucket: "configured-bucket".into(),
            dynamodb_table: "files".into(),
            dynamodb_folders_table: "folders".into(),
            dynamodb_versions_table: "versions".into(),
            dynamodb_shares_table: "shares".into(),
        }
    }

    #[tokio::test]
    async fn new_takes_the_bucket_from_config() {
        let s3 = S3Client::new(&aws_config(None)).await;
        assert_eq!(s3.bucket, "configured-bucket");
    }

    #[tokio::test]
    async fn new_honours_a_custom_endpoint() {
        let s3 = S3Client::new(&aws_config(Some("http://localstack:4566"))).await;
        assert_eq!(s3.bucket, "configured-bucket");
        assert!(
            format!("{:?}", s3.client.config()).contains("localstack"),
            "the custom endpoint is threaded into the SDK config"
        );
    }

    #[tokio::test]
    async fn upload_object_puts_the_body_at_the_configured_bucket_and_key() {
        let (s3, http) = fake_s3(vec![(200, String::new())]);

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
        let (s3, _http) = fake_s3(vec![(500, S3_ERROR_BODY.to_string())]);

        let err = s3
            .upload_object("some/key", Bytes::from_static(b"hello"), "text/plain")
            .await
            .expect_err("500 should surface as ServiceError");

        assert!(matches!(err, ServiceError::S3Error(_)), "got {err:?}");
        assert!(err.to_string().starts_with("S3 error: upload failed"));
    }

    #[tokio::test]
    async fn download_object_returns_the_object_body() {
        let (s3, http) = fake_s3(vec![(200, "file-contents".to_string())]);

        let body = s3.download_object("some/key").await.expect("download");

        assert_eq!(body, Bytes::from_static(b"file-contents"));
        let sent = http.actual_requests().next().expect("one request");
        assert_eq!(sent.method(), "GET");
        assert!(sent.uri().contains("/some/key"), "{}", sent.uri());
    }

    #[tokio::test]
    async fn download_object_maps_s3_failure_to_a_service_error() {
        let (s3, _http) = fake_s3(vec![(404, S3_ERROR_BODY.to_string())]);

        let err = s3
            .download_object("missing/key")
            .await
            .expect_err("404 should surface as ServiceError");

        assert!(err.to_string().starts_with("S3 error: download failed"));
    }

    #[tokio::test]
    async fn presigned_download_url_points_at_the_object_and_expires() {
        let (s3, _http) = fake_s3(vec![]);

        let url = s3
            .presigned_download_url("some/key", 900)
            .await
            .expect("presign");

        assert!(url.contains("test-bucket"), "{url}");
        assert!(url.contains("some/key"), "{url}");
        assert!(url.contains("X-Amz-Expires=900"), "{url}");
        assert!(url.contains("X-Amz-Signature="), "{url}");
    }

    #[tokio::test]
    async fn presigned_download_url_rejects_an_expiry_beyond_the_s3_limit() {
        let (s3, _http) = fake_s3(vec![]);

        // S3 presigned URLs may not live longer than one week.
        let err = s3
            .presigned_download_url("some/key", 60 * 60 * 24 * 8)
            .await
            .expect_err("an 8-day expiry is rejected");

        assert!(
            err.to_string()
                .starts_with("S3 error: presign config error"),
            "{err}"
        );
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
    async fn delete_object_maps_s3_failure_to_a_service_error() {
        let (s3, _http) = fake_s3(vec![(500, S3_ERROR_BODY.to_string())]);

        let err = s3.delete_object("some/key").await.expect_err("500");

        assert!(err.to_string().starts_with("S3 error: delete failed"));
    }

    #[tokio::test]
    async fn copy_object_sends_a_bucket_qualified_copy_source() {
        let copy_result = "<CopyObjectResult><ETag>\"abc\"</ETag></CopyObjectResult>".to_string();
        let (s3, http) = fake_s3(vec![(200, copy_result)]);

        s3.copy_object("old/key", "new/key").await.expect("copy");

        let sent = http.actual_requests().next().expect("one request");
        assert_eq!(sent.method(), "PUT");
        assert!(sent.uri().contains("/new/key"), "{}", sent.uri());
        assert_eq!(
            sent.headers().get("x-amz-copy-source"),
            Some("test-bucket/old/key")
        );
    }

    #[tokio::test]
    async fn copy_object_maps_s3_failure_to_a_service_error() {
        let (s3, _http) = fake_s3(vec![(403, S3_ERROR_BODY.to_string())]);

        let err = s3.copy_object("old/key", "new/key").await.expect_err("403");

        assert!(err.to_string().starts_with("S3 error: copy failed"));
    }
}
