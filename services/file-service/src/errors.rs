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
mod errors_tests {
    use super::*;
    use actix_web::body::MessageBody;
    use actix_web::http::StatusCode;

    fn body_of(err: &ServiceError) -> serde_json::Value {
        let bytes = err.error_response().into_body().try_into_bytes().unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    #[test]
    fn maps_each_variant_to_its_status_and_error_type() {
        let cases = [
            (
                ServiceError::FileNotFound("f1".into()),
                StatusCode::NOT_FOUND,
                "file_not_found",
            ),
            (
                ServiceError::FolderNotFound("f2".into()),
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
                    actual_bytes: 11,
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
                ServiceError::S3Error("s3".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "storage_error",
            ),
            (
                ServiceError::DynamoError("ddb".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "metadata_error",
            ),
            (
                ServiceError::SnsError("sns".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "event_error",
            ),
            (
                ServiceError::Internal("boom".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "internal_error",
            ),
        ];

        for (err, expected_status, expected_type) in cases {
            let response = err.error_response();
            assert_eq!(response.status(), expected_status, "{err}");
            let body = body_of(&err);
            assert_eq!(body["error"], expected_type, "{err}");
            assert_eq!(body["message"], err.to_string(), "{err}");
        }
    }

    #[test]
    fn display_messages_include_their_context() {
        assert_eq!(
            ServiceError::FileNotFound("abc".into()).to_string(),
            "File not found: abc"
        );
        assert_eq!(
            ServiceError::FolderNotFound("abc".into()).to_string(),
            "Folder not found: abc"
        );
        assert_eq!(
            ServiceError::VersionNotFound("3".into()).to_string(),
            "Version not found: 3"
        );
        assert_eq!(
            ServiceError::ShareNotFound("s1".into()).to_string(),
            "Share not found: s1"
        );
        assert_eq!(
            ServiceError::BadRequest("nope".into()).to_string(),
            "Bad request: nope"
        );
        assert_eq!(
            ServiceError::Unauthorized("no token".into()).to_string(),
            "Unauthorized: no token"
        );
        assert_eq!(
            ServiceError::Forbidden("not yours".into()).to_string(),
            "Forbidden: not yours"
        );
        assert_eq!(
            ServiceError::S3Error("put".into()).to_string(),
            "S3 error: put"
        );
        assert_eq!(
            ServiceError::DynamoError("scan".into()).to_string(),
            "DynamoDB error: scan"
        );
        assert_eq!(
            ServiceError::SnsError("publish".into()).to_string(),
            "SNS error: publish"
        );
        assert_eq!(
            ServiceError::Internal("oops".into()).to_string(),
            "Internal error: oops"
        );
    }

    #[test]
    fn file_too_large_message_reports_both_sizes() {
        let err = ServiceError::FileTooLarge {
            max_bytes: 100,
            actual_bytes: 250,
        };
        assert_eq!(
            err.to_string(),
            "File too large: max 100 bytes, got 250 bytes"
        );
    }

    #[test]
    fn error_response_body_is_json_content_type() {
        let response = ServiceError::BadRequest("x".into()).error_response();
        assert_eq!(
            response
                .headers()
                .get("content-type")
                .and_then(|v| v.to_str().ok()),
            Some("application/json")
        );
    }

    #[test]
    fn error_response_struct_displays_error_and_message() {
        let payload = ErrorResponse {
            error: "bad_request".into(),
            message: "Bad request: missing name".into(),
        };
        assert_eq!(
            payload.to_string(),
            "bad_request: Bad request: missing name"
        );
        assert!(format!("{payload:?}").contains("ErrorResponse"));
    }

    #[test]
    fn service_error_is_debug() {
        let err = ServiceError::FileNotFound("abc".into());
        assert!(format!("{err:?}").contains("FileNotFound"));
    }
}
