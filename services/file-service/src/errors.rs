use actix_web::{HttpResponse, ResponseError};
use std::fmt;

#[derive(Debug, thiserror::Error)]
pub enum ServiceError {
    #[error("File not found: {0}")]
    FileNotFound(String),

    #[error("Folder not found: {0}")]
    FolderNotFound(String),

    #[error("Version not found: {0}")]
    VersionNotFound(String),

    #[error("Share not found: {0}")]
    ShareNotFound(String),

    #[error("Bad request: {0}")]
    BadRequest(String),

    #[error("File too large: max {max_bytes} bytes, got {actual_bytes} bytes")]
    FileTooLarge { max_bytes: u64, actual_bytes: u64 },

    #[error("Unauthorized: {0}")]
    Unauthorized(String),

    #[error("Forbidden: {0}")]
    Forbidden(String),

    #[error("S3 error: {0}")]
    S3Error(String),

    #[error("DynamoDB error: {0}")]
    DynamoError(String),

    #[error("SNS error: {0}")]
    SnsError(String),

    #[error("Internal error: {0}")]
    Internal(String),
}

impl ResponseError for ServiceError {
    fn error_response(&self) -> HttpResponse {
        let (status, error_type) = match self {
            ServiceError::FileNotFound(_) => {
                (actix_web::http::StatusCode::NOT_FOUND, "file_not_found")
            }
            ServiceError::FolderNotFound(_) => {
                (actix_web::http::StatusCode::NOT_FOUND, "folder_not_found")
            }
            ServiceError::VersionNotFound(_) => {
                (actix_web::http::StatusCode::NOT_FOUND, "version_not_found")
            }
            ServiceError::ShareNotFound(_) => {
                (actix_web::http::StatusCode::NOT_FOUND, "share_not_found")
            }
            ServiceError::BadRequest(_) => {
                (actix_web::http::StatusCode::BAD_REQUEST, "bad_request")
            }
            ServiceError::FileTooLarge { .. } => (
                actix_web::http::StatusCode::PAYLOAD_TOO_LARGE,
                "file_too_large",
            ),
            ServiceError::Unauthorized(_) => {
                (actix_web::http::StatusCode::UNAUTHORIZED, "unauthorized")
            }
            ServiceError::Forbidden(_) => (actix_web::http::StatusCode::FORBIDDEN, "forbidden"),
            ServiceError::S3Error(_) => (
                actix_web::http::StatusCode::INTERNAL_SERVER_ERROR,
                "storage_error",
            ),
            ServiceError::DynamoError(_) => (
                actix_web::http::StatusCode::INTERNAL_SERVER_ERROR,
                "metadata_error",
            ),
            ServiceError::SnsError(_) => (
                actix_web::http::StatusCode::INTERNAL_SERVER_ERROR,
                "event_error",
            ),
            ServiceError::Internal(_) => (
                actix_web::http::StatusCode::INTERNAL_SERVER_ERROR,
                "internal_error",
            ),
        };

        if status.is_server_error() {
            tracing::error!(error_type, error = %self, "Request failed with internal error");
        }

        HttpResponse::build(status).json(ErrorResponse {
            error: error_type.to_string(),
            message: self.client_message(),
        })
    }
}

impl ServiceError {
    /// Message safe to return to the caller. Backend failures carry raw AWS SDK /
    /// infrastructure detail, so only a generic message leaves the service.
    fn client_message(&self) -> String {
        match self {
            ServiceError::S3Error(_) => "Storage operation failed".to_string(),
            ServiceError::DynamoError(_) => "Metadata operation failed".to_string(),
            ServiceError::SnsError(_) => "Event publishing failed".to_string(),
            ServiceError::Internal(_) => "Internal server error".to_string(),
            _ => self.to_string(),
        }
    }
}

#[derive(Debug, serde::Serialize)]
pub struct ErrorResponse {
    pub error: String,
    pub message: String,
}

impl fmt::Display for ErrorResponse {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.error, self.message)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::body::to_bytes;

    async fn body_of(err: ServiceError) -> (u16, serde_json::Value) {
        let resp = err.error_response();
        let status = resp.status().as_u16();
        let bytes = to_bytes(resp.into_body()).await.unwrap();
        (status, serde_json::from_slice(&bytes).unwrap())
    }

    #[actix_web::test]
    async fn backend_errors_do_not_leak_internal_detail() {
        let detail = "dispatch failure: bucket otterworks-files at http://localstack:4566";
        let cases = [
            (ServiceError::S3Error(detail.into()), "storage_error"),
            (ServiceError::DynamoError(detail.into()), "metadata_error"),
            (ServiceError::SnsError(detail.into()), "event_error"),
            (ServiceError::Internal(detail.into()), "internal_error"),
        ];
        for (err, error_type) in cases {
            let (status, body) = body_of(err).await;
            assert_eq!(status, 500);
            assert_eq!(body["error"], error_type);
            let message = body["message"].as_str().unwrap();
            assert!(!message.contains("localstack"), "leaked detail: {message}");
            assert!(
                !message.contains("otterworks-files"),
                "leaked detail: {message}"
            );
        }
    }

    #[actix_web::test]
    async fn client_errors_keep_their_message() {
        let (status, body) = body_of(ServiceError::BadRequest("name cannot be empty".into())).await;
        assert_eq!(status, 400);
        assert_eq!(body["message"], "Bad request: name cannot be empty");
    }
}
