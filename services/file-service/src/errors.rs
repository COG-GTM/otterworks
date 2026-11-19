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

        HttpResponse::build(status).json(ErrorResponse {
            error: error_type.to_string(),
            message: self.to_string(),
        })
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
    use actix_web::body::MessageBody;
    use actix_web::http::StatusCode;

    fn response_parts(err: ServiceError) -> (StatusCode, serde_json::Value) {
        let resp = err.error_response();
        let status = resp.status();
        let bytes = resp
            .into_body()
            .try_into_bytes()
            .expect("body is in memory");
        (
            status,
            serde_json::from_slice(&bytes).expect("body is JSON"),
        )
    }

    #[test]
    fn maps_each_variant_to_status_and_error_code() {
        let cases = [
            (
                ServiceError::FileNotFound("f".into()),
                StatusCode::NOT_FOUND,
                "file_not_found",
            ),
            (
                ServiceError::FolderNotFound("f".into()),
                StatusCode::NOT_FOUND,
                "folder_not_found",
            ),
            (
                ServiceError::VersionNotFound("v".into()),
                StatusCode::NOT_FOUND,
                "version_not_found",
            ),
            (
                ServiceError::ShareNotFound("s".into()),
                StatusCode::NOT_FOUND,
                "share_not_found",
            ),
            (
                ServiceError::BadRequest("b".into()),
                StatusCode::BAD_REQUEST,
                "bad_request",
            ),
            (
                ServiceError::FileTooLarge {
                    max_bytes: 10,
                    actual_bytes: 20,
                },
                StatusCode::PAYLOAD_TOO_LARGE,
                "file_too_large",
            ),
            (
                ServiceError::Unauthorized("u".into()),
                StatusCode::UNAUTHORIZED,
                "unauthorized",
            ),
            (
                ServiceError::Forbidden("f".into()),
                StatusCode::FORBIDDEN,
                "forbidden",
            ),
            (
                ServiceError::S3Error("s".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "storage_error",
            ),
            (
                ServiceError::DynamoError("d".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "metadata_error",
            ),
            (
                ServiceError::SnsError("s".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "event_error",
            ),
            (
                ServiceError::Internal("i".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "internal_error",
            ),
        ];

        for (err, expected_status, expected_code) in cases {
            let message = err.to_string();
            let (status, body) = response_parts(err);
            assert_eq!(status, expected_status, "{expected_code}");
            assert_eq!(body["error"], expected_code);
            assert_eq!(body["message"], message);
        }
    }

    #[test]
    fn file_too_large_message_reports_limits() {
        let (_, body) = response_parts(ServiceError::FileTooLarge {
            max_bytes: 100,
            actual_bytes: 250,
        });
        assert_eq!(
            body["message"],
            "File too large: max 100 bytes, got 250 bytes"
        );
    }
}
