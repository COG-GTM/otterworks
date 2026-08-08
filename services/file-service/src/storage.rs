use aws_sdk_s3::error::{ProvideErrorMetadata, SdkError};
use aws_sdk_s3::presigning::PresigningConfig;
use aws_smithy_types::error::display::DisplayErrorContext;
use bytes::Bytes;
use std::time::Duration;

use crate::config::AwsConfig;
use crate::errors::ServiceError;

/// Log the bucket, key and full SDK source chain of a failed S3 call and return an
/// `S3Error` naming the operation and S3 error code. The detail stays in the logs:
/// `ServiceError` messages are serialized into the client-facing error body, and the
/// bucket name and key layout (which embeds owner ids) are internal.
fn s3_error<E, R>(op: &str, bucket: &str, key: &str, err: SdkError<E, R>) -> ServiceError
where
    E: ProvideErrorMetadata + std::error::Error + Send + Sync + 'static,
    R: std::fmt::Debug + Send + Sync + 'static,
{
    let code = err.code().unwrap_or("unknown").to_string();
    tracing::error!(
        operation = %op,
        bucket = %bucket,
        key = %key,
        code = %code,
        error = %DisplayErrorContext(&err),
        "S3 operation failed"
    );
    ServiceError::S3Error(format!("{op} failed: code={code}"))
}

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
            .map_err(|e| s3_error("upload", &self.bucket, key, e))?;

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
            .map_err(|e| s3_error("download", &self.bucket, key, e))?;

        let body = resp.body.collect().await.map_err(|e| {
            tracing::error!(
                operation = "download",
                bucket = %self.bucket,
                key = %key,
                error = %DisplayErrorContext(&e),
                "S3 response body read failed"
            );
            ServiceError::S3Error("download failed: body read error".to_string())
        })?;

        Ok(body.into_bytes())
    }

    /// Generate a presigned download URL.
    pub async fn presigned_download_url(
        &self,
        key: &str,
        expires_in_secs: u64,
    ) -> Result<String, ServiceError> {
        let presigning = PresigningConfig::expires_in(Duration::from_secs(expires_in_secs))
            .map_err(|e| {
                tracing::error!(
                    operation = "presign",
                    bucket = %self.bucket,
                    key = %key,
                    expires_in_secs = %expires_in_secs,
                    error = %DisplayErrorContext(&e),
                    "S3 presign config rejected"
                );
                ServiceError::S3Error("presign failed: invalid presign config".to_string())
            })?;

        let presigned = self
            .client
            .get_object()
            .bucket(&self.bucket)
            .key(key)
            .presigned(presigning)
            .await
            .map_err(|e| s3_error("presign", &self.bucket, key, e))?;

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
            .map_err(|e| s3_error("delete", &self.bucket, key, e))?;

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
            .map_err(|e| {
                s3_error(
                    "copy",
                    &self.bucket,
                    &format!("{source_key} -> {dest_key}"),
                    e,
                )
            })?;

        tracing::info!(source = %source_key, dest = %dest_key, "Copied object in S3");
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use aws_sdk_s3::operation::put_object::PutObjectError;

    #[test]
    fn s3_error_keeps_bucket_and_key_out_of_the_client_message() {
        let err: SdkError<PutObjectError, ()> = SdkError::timeout_error("connect timed out");
        let ServiceError::S3Error(message) = s3_error("upload", "my-bucket", "files/a/b", err)
        else {
            panic!("expected an S3Error");
        };

        assert_eq!(message, "upload failed: code=unknown");
        assert!(!message.contains("my-bucket"), "{message}");
        assert!(!message.contains("files/a/b"), "{message}");
    }
}
