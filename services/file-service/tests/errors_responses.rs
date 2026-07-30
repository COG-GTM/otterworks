//! `ServiceError` -> HTTP status / error-type / message mapping.

use actix_web::body::MessageBody;
use actix_web::http::StatusCode;
use actix_web::ResponseError;
use file_service::errors::{ErrorResponse, ServiceError};

fn body_json(err: &ServiceError) -> serde_json::Value {
    let bytes = err
        .error_response()
        .into_body()
        .try_into_bytes()
        .expect("error body is always in-memory");
    serde_json::from_slice(&bytes).expect("error body is JSON")
}

#[test]
fn maps_each_variant_to_its_status_and_error_type() {
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

    for (err, expected_status, expected_type) in cases {
        assert_eq!(err.error_response().status(), expected_status, "{err}");
        let body = body_json(&err);
        assert_eq!(body["error"], expected_type, "{err}");
        assert_eq!(body["message"], err.to_string(), "{err}");
    }
}

#[test]
fn display_messages_include_their_payload() {
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
        ServiceError::S3Error("boom".into()).to_string(),
        "S3 error: boom"
    );
    assert_eq!(
        ServiceError::DynamoError("boom".into()).to_string(),
        "DynamoDB error: boom"
    );
    assert_eq!(
        ServiceError::SnsError("boom".into()).to_string(),
        "SNS error: boom"
    );
    assert_eq!(
        ServiceError::Internal("boom".into()).to_string(),
        "Internal error: boom"
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
    assert!(format!("{err:?}").contains("FileTooLarge"));
}

#[test]
fn error_response_displays_as_type_colon_message() {
    let resp = ErrorResponse {
        error: "bad_request".into(),
        message: "name cannot be empty".into(),
    };
    assert_eq!(resp.to_string(), "bad_request: name cannot be empty");
    assert!(format!("{resp:?}").contains("ErrorResponse"));
}
