//! Pure unit tests for error mapping and model (de)serialization.

use actix_web::ResponseError;

use serde_json::json;

use crate::errors::ServiceError;
use crate::models::{ShareFileRequest, SharePermission};

#[test]
fn every_error_variant_maps_to_its_documented_status_and_type() {
    let cases = [
        (
            ServiceError::FileNotFound("x".into()),
            404,
            "file_not_found",
        ),
        (
            ServiceError::FolderNotFound("x".into()),
            404,
            "folder_not_found",
        ),
        (
            ServiceError::VersionNotFound("x".into()),
            404,
            "version_not_found",
        ),
        (
            ServiceError::ShareNotFound("x".into()),
            404,
            "share_not_found",
        ),
        (ServiceError::BadRequest("x".into()), 400, "bad_request"),
        (
            ServiceError::FileTooLarge {
                max_bytes: 1,
                actual_bytes: 2,
            },
            413,
            "file_too_large",
        ),
        (ServiceError::Unauthorized("x".into()), 401, "unauthorized"),
        (ServiceError::Forbidden("x".into()), 403, "forbidden"),
        (ServiceError::S3Error("x".into()), 500, "storage_error"),
        (ServiceError::DynamoError("x".into()), 500, "metadata_error"),
        (ServiceError::SnsError("x".into()), 500, "event_error"),
        (ServiceError::Internal("x".into()), 500, "internal_error"),
    ];
    for (err, status, kind) in cases {
        let resp = err.error_response();
        assert_eq!(resp.status().as_u16(), status, "{err:?}");
        let body = actix_web::body::to_bytes(resp.into_body());
        let body = futures_util::FutureExt::now_or_never(body)
            .unwrap()
            .unwrap();
        let v: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(v["error"], kind);
        assert!(v["message"].is_string());
    }
}

#[test]
fn file_too_large_message_reports_size_and_limit() {
    let msg = ServiceError::FileTooLarge {
        max_bytes: 1024,
        actual_bytes: 2048,
    }
    .to_string();
    assert!(msg.contains("2048") && msg.contains("1024"), "{msg}");
}

#[test]
fn share_permission_serializes_lowercase_and_rejects_unknown_roles() {
    assert_eq!(
        serde_json::to_value(SharePermission::Viewer).unwrap(),
        "viewer"
    );
    assert_eq!(
        serde_json::to_value(SharePermission::Editor).unwrap(),
        "editor"
    );
    assert_eq!(SharePermission::Editor.to_string(), "editor");
    for bad in ["owner", "admin", "Viewer", ""] {
        assert!(
            serde_json::from_value::<SharePermission>(json!(bad)).is_err(),
            "{bad}"
        );
    }
}

#[test]
fn share_request_requires_permission_and_shared_by() {
    let ok = json!({
        "shared_with": uuid::Uuid::new_v4(),
        "permission": "viewer",
        "shared_by": uuid::Uuid::new_v4()
    });
    assert!(serde_json::from_value::<ShareFileRequest>(ok).is_ok());
    let missing_perm =
        json!({"shared_with": uuid::Uuid::new_v4(), "shared_by": uuid::Uuid::new_v4()});
    assert!(serde_json::from_value::<ShareFileRequest>(missing_perm).is_err());
    let missing_by = json!({"shared_with": uuid::Uuid::new_v4(), "permission": "viewer"});
    assert!(serde_json::from_value::<ShareFileRequest>(missing_by).is_err());
}
