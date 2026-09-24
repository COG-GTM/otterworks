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

    #[error("Not enough storage: {used} of {limit} bytes used")]
    QuotaExceeded { used: u64, limit: u64 },

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
            ServiceError::QuotaExceeded { .. } => (
                actix_web::http::StatusCode::PAYLOAD_TOO_LARGE,
                "quota_exceeded",
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

        let (code, used, limit) = match self {
            ServiceError::QuotaExceeded { used, limit } => {
                (Some("QUOTA_EXCEEDED".to_string()), Some(*used), Some(*limit))
            }
            _ => (None, None, None),
        };

        HttpResponse::build(status).json(ErrorResponse {
            error: error_type.to_string(),
            message: self.to_string(),
            code,
            used,
            limit,
        })
    }
}

#[derive(Debug, serde::Serialize)]
pub struct ErrorResponse {
    pub error: String,
    pub message: String,
    /// Machine-readable code, set for errors clients branch on.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub code: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub used: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub limit: Option<u64>,
}

impl fmt::Display for ErrorResponse {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.error, self.message)
    }
}
