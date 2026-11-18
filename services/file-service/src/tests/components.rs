use actix_web::ResponseError;
use bytes::Bytes;
use chrono::Utc;
use serde_json::json;
use uuid::Uuid;

use crate::alerts::{self, AlertConfig};
use crate::config::{AppConfig, AwsConfig, ServerConfig, SnsConfig};
use crate::errors::ServiceError;
use crate::events::EventPublisher;
use crate::metadata::MetadataClient;
use crate::models::{FileMetadata, FileShare, FileVersion, Folder, SharePermission};
use crate::storage::S3Client;
use crate::test_support::{FakeAws, BUCKET, TOPIC};

fn sample_file(owner: Uuid) -> FileMetadata {
    let id = Uuid::new_v4();
    FileMetadata {
        id,
        name: "f".into(),
        mime_type: "text/plain".into(),
        size_bytes: 1,
        s3_key: format!("files/{owner}/{id}"),
        folder_id: None,
        owner_id: owner,
        version: 1,
        is_trashed: false,
        created_at: Utc::now(),
        updated_at: Utc::now(),
    }
}

#[test]
fn service_errors_map_to_http_statuses() {
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
        assert_eq!(resp.status().as_u16(), status);
        let body = actix_web::body::to_bytes(resp.into_body());
        let body = futures_util::FutureExt::now_or_never(body)
            .unwrap()
            .unwrap();
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["error"], kind, "{err}");
        assert_eq!(json["message"], err.to_string());
    }
}

#[test]
fn config_from_env_builds_every_section() {
    let cfg = AppConfig::from_env();
    assert!(!cfg.aws.region.is_empty());
    assert!(!cfg.aws.s3_bucket.is_empty());
    assert!(cfg.server.max_upload_bytes > 0);
    let alerts = AlertConfig::from_env();
    assert!(!alerts.admin_service_url.is_empty());
}

#[actix_rt::test]
async fn s3_client_operations() {
    let aws = FakeAws::start();
    let s3 = aws.s3();
    s3.upload_object("a/b", Bytes::from_static(b"data"), "text/plain")
        .await
        .unwrap();
    assert_eq!(
        s3.download_object("a/b").await.unwrap(),
        Bytes::from_static(b"data")
    );
    s3.copy_object("a/b", "a/c").await.unwrap();
    assert!(aws
        .st()
        .objects
        .contains_key(&(BUCKET.into(), "a/c".into())));
    let url = s3.presigned_download_url("a/b", 60).await.unwrap();
    assert!(
        url.contains("/a/b") && url.contains("X-Amz-Expires=60"),
        "{url}"
    );
    s3.delete_object("a/b").await.unwrap();

    assert!(matches!(
        s3.download_object("a/b").await,
        Err(ServiceError::S3Error(_))
    ));
    assert!(matches!(
        s3.copy_object("missing", "x").await,
        Err(ServiceError::S3Error(_))
    ));
    aws.fail("s3:DELETE");
    assert!(matches!(
        s3.delete_object("a/c").await,
        Err(ServiceError::S3Error(_))
    ));
    let missing = aws.s3_bucket("nope");
    assert!(matches!(
        missing
            .upload_object("k", Bytes::from_static(b"x"), "text/plain")
            .await,
        Err(ServiceError::S3Error(_))
    ));
}

#[actix_rt::test]
async fn clients_build_from_config() {
    let aws = FakeAws::start();
    let mut cfg: AwsConfig = aws.config().aws;
    let s3 = S3Client::new(&cfg).await;
    assert_eq!(s3.bucket, BUCKET);
    let meta = MetadataClient::new(&cfg).await;
    assert_eq!(meta.files_table, "files");
    let sns = SnsConfig {
        topic_arn: Some(TOPIC.into()),
        share_event_always_fail: true,
    };
    let publisher = EventPublisher::new(&sns, &cfg).await;
    assert!(publisher.share_publish_forced());

    cfg.endpoint_url = None;
    S3Client::new(&cfg).await;
    MetadataClient::new(&cfg).await;
    let publisher = EventPublisher::new(
        &SnsConfig {
            topic_arn: None,
            share_event_always_fail: true,
        },
        &cfg,
    )
    .await;
    assert!(publisher.share_publish_forced());
    let publisher = EventPublisher::new(
        &SnsConfig {
            topic_arn: None,
            share_event_always_fail: false,
        },
        &cfg,
    )
    .await;
    assert!(!publisher.share_publish_forced());
}

#[actix_rt::test]
async fn event_publisher_methods_and_failures() {
    let aws = FakeAws::start();
    let events = aws.events(Some(TOPIC), None);
    let (f, o, u) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    events
        .file_uploaded(&f, &o, Some(&u), "n", "text/plain", 1)
        .await
        .unwrap();
    events.file_deleted(&f, &o).await.unwrap();
    events.file_shared(&f, &o, &u).await.unwrap();
    events.file_trashed(&f, &o).await.unwrap();
    events
        .file_restored(&f, &o, None, "n", "text/plain", 1)
        .await
        .unwrap();
    events
        .file_updated(&f, &o, None, "n", "text/plain", 1)
        .await
        .unwrap();
    events.file_moved(&f, &o, Some(&u)).await.unwrap();
    events.file_moved(&f, &o, None).await.unwrap();
    let types: Vec<String> = aws
        .st()
        .published
        .iter()
        .map(|p| {
            serde_json::from_str::<serde_json::Value>(&p["Message"]).unwrap()["eventType"]
                .as_str()
                .unwrap_or_default()
                .to_string()
        })
        .collect();
    assert_eq!(types.len(), 8);

    let fifo = "arn:aws:sns:us-east-1:000000000000:file-events.fifo";
    aws.st().topics.insert(fifo.into());
    aws.events(Some(fifo), None)
        .file_deleted(&f, &o)
        .await
        .unwrap();
    let last = aws.st().published.last().unwrap().clone();
    assert!(last.contains_key("MessageGroupId"));
    assert!(last.contains_key("MessageDeduplicationId"));

    aws.events(None, None).file_deleted(&f, &o).await.unwrap();

    let forced = aws.events(Some(TOPIC), Some("arn:aws:sns:us-east-1:000000000000:gone"));
    let err = forced
        .file_shared(&f, &o, &u)
        .await
        .unwrap_err()
        .to_string();
    assert!(err.contains("gone") && err.contains("NotFound"), "{err}");

    let unreachable = EventPublisher::for_test(
        crate::test_support::sns_client("http://127.0.0.1:1"),
        Some(TOPIC.into()),
        None,
    );
    let err = unreachable.file_deleted(&f, &o).await.unwrap_err();
    assert!(matches!(err, ServiceError::SnsError(_)));
}

#[actix_rt::test]
async fn metadata_errors_are_mapped() {
    let aws = FakeAws::start();
    let meta = aws.meta();
    let id = Uuid::new_v4();
    let owner = Uuid::new_v4();

    assert!(matches!(
        meta.get_file(&id).await,
        Err(ServiceError::FileNotFound(_))
    ));
    assert!(matches!(
        meta.trash_file(&id).await,
        Err(ServiceError::FileNotFound(_))
    ));
    assert!(matches!(
        meta.restore_file(&id).await,
        Err(ServiceError::FileNotFound(_))
    ));
    assert!(matches!(
        meta.rename_file(&id, "x").await,
        Err(ServiceError::FileNotFound(_))
    ));
    assert!(matches!(
        meta.move_file(&id, None).await,
        Err(ServiceError::FileNotFound(_))
    ));
    assert!(matches!(
        meta.get_folder(&id).await,
        Err(ServiceError::FolderNotFound(_))
    ));
    assert!(matches!(
        meta.update_folder(&id, Some("x".into()), None).await,
        Err(ServiceError::FolderNotFound(_))
    ));

    for op in [
        "PutItem",
        "GetItem",
        "DeleteItem",
        "UpdateItem",
        "Scan",
        "Query",
    ] {
        aws.fail(op);
    }
    let now = Utc::now();
    let file = sample_file(owner);
    let folder = Folder {
        id,
        name: "x".into(),
        parent_id: None,
        owner_id: owner,
        created_at: now,
        updated_at: now,
    };
    let version = FileVersion {
        file_id: id,
        version: 1,
        s3_key: "k".into(),
        size_bytes: 1,
        created_by: owner,
        created_at: now,
    };
    let share = FileShare {
        id,
        file_id: id,
        shared_with: owner,
        permission: SharePermission::Editor,
        shared_by: owner,
        created_at: now,
    };
    let results: Vec<bool> = vec![
        meta.put_file(&file).await.is_err(),
        meta.get_file(&id).await.is_err(),
        meta.delete_file(&id).await.is_err(),
        meta.trash_file(&id).await.is_err(),
        meta.restore_file(&id).await.is_err(),
        meta.rename_file(&id, "x").await.is_err(),
        meta.move_file(&id, Some(id)).await.is_err(),
        meta.list_trashed(Some(owner)).await.is_err(),
        meta.list_files(Some(id), Some(owner), false).await.is_err(),
        meta.put_folder(&folder).await.is_err(),
        meta.get_folder(&id).await.is_err(),
        meta.update_folder(&id, None, Some(id)).await.is_err(),
        meta.delete_folder(&id).await.is_err(),
        meta.list_folders(Some(id), Some(owner)).await.is_err(),
        meta.put_version(&version).await.is_err(),
        meta.list_versions(&id).await.is_err(),
        meta.put_share(&share).await.is_err(),
        meta.find_existing_share(&id, &owner).await.is_err(),
        meta.list_shares_for_user(&owner).await.is_err(),
        meta.list_shares_by_owner(&owner).await.is_err(),
        meta.delete_share(&id).await.is_err(),
        meta.list_shares(&id).await.is_err(),
    ];
    assert!(results.iter().all(|r| *r), "{results:?}");
}

#[actix_rt::test]
async fn metadata_rejects_malformed_items() {
    let aws = FakeAws::start();
    let meta = aws.meta();
    let id = Uuid::new_v4();
    let s = |v: &str| json!({"S": v});
    aws.insert_item(
        "files",
        json!({"id": s("not-a-uuid"), "is_trashed": {"BOOL": true}}),
    );
    aws.insert_item("folders", json!({"id": s(&id.to_string())}));
    aws.insert_item(
        "versions",
        json!({"file_id": s(&id.to_string()), "version": {"N": "1"}}),
    );
    aws.insert_item(
        "shares",
        json!({"id": s("x"), "file_id": s(&id.to_string()), "shared_with": s(&id.to_string()), "shared_by": s(&id.to_string())}),
    );
    assert!(meta.list_files(None, None, true).await.is_err());
    assert!(meta.list_trashed(None).await.is_err());
    assert!(meta.list_folders(None, None).await.is_err());
    assert!(meta.get_folder(&id).await.is_err());
    assert!(meta.list_versions(&id).await.is_err());
    assert!(meta.list_shares(&id).await.is_err());
    assert!(meta.list_shares_for_user(&id).await.is_err());
    assert!(meta.list_shares_by_owner(&id).await.is_err());
    assert!(meta.find_existing_share(&id, &id).await.is_err());
}

#[actix_rt::test]
async fn seed_skips_on_failures() {
    let aws = FakeAws::start();
    let meta = aws.meta();
    let owner = Uuid::new_v4();

    assert!(!crate::seed::maybe_seed_demo_docs(&meta, &aws.s3_bucket("nope"), owner).await);
    aws.fail("PutItem:files");
    assert!(!crate::seed::maybe_seed_demo_docs(&meta, &aws.s3(), owner).await);
    aws.st().fail.clear();
    meta.put_file(&sample_file(owner)).await.unwrap();
    assert!(!crate::seed::maybe_seed_demo_docs(&meta, &aws.s3(), owner).await);
    aws.fail("Scan");
    assert!(!crate::seed::maybe_seed_demo_docs(&meta, &aws.s3(), Uuid::new_v4()).await);
}

#[actix_rt::test]
async fn alert_delivery_outcomes() {
    let aws = FakeAws::start();
    let mut cfg = aws.config().alerts;
    cfg.alert_webhook_secret = None;
    alerts::notify_share_notification_failure(&cfg, "doc", "boom", None, true, true);
    assert_eq!(aws.wait_alerts(1).await[0].0, None);
    aws.st().alert_status = 503;
    alerts::notify_share_notification_failure(&cfg, "doc", "boom", None, false, false);
    alerts::notify_upload_failure(&cfg, "doc", "boom", None);
    assert_eq!(aws.wait_alerts(3).await.len(), 3);

    let empty = AlertConfig {
        admin_service_url: " ".into(),
        alert_webhook_secret: None,
    };
    alerts::notify_share_notification_failure(&empty, "doc", "boom", None, true, true);
    let unreachable = AlertConfig {
        admin_service_url: "http://127.0.0.1:1".into(),
        alert_webhook_secret: None,
    };
    alerts::notify_share_notification_failure(&unreachable, "doc", "boom", None, true, true);
    actix_web::rt::time::sleep(std::time::Duration::from_millis(200)).await;
}

#[test]
fn server_config_defaults() {
    let cfg = ServerConfig::from_env();
    assert!(cfg.port > 0);
}
