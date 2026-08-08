//! Wire-format tests for the request/response models.

use actix_web::web::Query;
use chrono::{DateTime, Utc};
use file_service::models::*;
use uuid::Uuid;

fn epoch() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-01-02T03:04:05Z")
        .unwrap()
        .with_timezone(&Utc)
}

fn sample_file() -> FileMetadata {
    FileMetadata {
        id: Uuid::nil(),
        name: "report.pdf".into(),
        mime_type: "application/pdf".into(),
        size_bytes: 42,
        s3_key: "files/owner/id".into(),
        folder_id: None,
        owner_id: Uuid::nil(),
        version: 2,
        is_trashed: false,
        created_at: epoch(),
        updated_at: epoch(),
    }
}

#[test]
fn share_permission_displays_lowercase() {
    assert_eq!(SharePermission::Viewer.to_string(), "viewer");
    assert_eq!(SharePermission::Editor.to_string(), "editor");
}

#[test]
fn share_permission_parses_case_insensitively_and_rejects_junk() {
    for input in ["viewer", "Viewer", "VIEWER"] {
        assert_eq!(
            SharePermission::from_str_value(input),
            Some(SharePermission::Viewer),
            "{input}"
        );
    }
    for input in ["editor", "Editor", "EDITOR"] {
        assert_eq!(
            SharePermission::from_str_value(input),
            Some(SharePermission::Editor),
            "{input}"
        );
    }
    for input in ["", "owner", "read-only", " viewer"] {
        assert_eq!(SharePermission::from_str_value(input), None, "{input}");
    }
}

#[test]
fn share_permission_serializes_lowercase() {
    assert_eq!(
        serde_json::to_string(&SharePermission::Editor).unwrap(),
        "\"editor\""
    );
    let parsed: SharePermission = serde_json::from_str("\"viewer\"").unwrap();
    assert_eq!(parsed, SharePermission::Viewer);
    assert!(format!("{:?}", SharePermission::Viewer).contains("Viewer"));
    assert_eq!(SharePermission::Viewer.clone(), SharePermission::Viewer);
}

#[test]
fn file_metadata_round_trips_through_json() {
    let file = sample_file();
    let json = serde_json::to_value(&file).unwrap();
    assert_eq!(json["name"], "report.pdf");
    assert_eq!(json["size_bytes"], 42);
    assert!(json["folder_id"].is_null());

    let back: FileMetadata = serde_json::from_value(json).unwrap();
    assert_eq!(back.id, file.id);
    assert_eq!(back.version, file.version);
    assert_eq!(back.created_at, file.created_at);
    assert!(format!("{:?}", file.clone()).contains("report.pdf"));
}

#[test]
fn file_detail_response_flattens_the_file_fields() {
    let share = FileShare {
        id: Uuid::nil(),
        file_id: Uuid::nil(),
        shared_with: Uuid::nil(),
        permission: SharePermission::Viewer,
        shared_by: Uuid::nil(),
        created_at: epoch(),
    };
    let detail = FileDetailResponse {
        file: sample_file(),
        shared_with: vec![share.clone()],
    };
    let json = serde_json::to_value(&detail).unwrap();
    assert_eq!(json["name"], "report.pdf", "file fields are flattened");
    assert_eq!(json["shared_with"].as_array().unwrap().len(), 1);
    assert_eq!(json["shared_with"][0]["permission"], "viewer");
    assert!(format!("{share:?}").contains("FileShare"));
}

#[test]
fn folder_and_version_round_trip_through_json() {
    let parent = Uuid::new_v4();
    let folder = Folder {
        id: Uuid::new_v4(),
        name: "Finance".into(),
        parent_id: Some(parent),
        owner_id: Uuid::new_v4(),
        created_at: epoch(),
        updated_at: epoch(),
    };
    let back: Folder = serde_json::from_value(serde_json::to_value(folder.clone()).unwrap())
        .expect("folder round-trips");
    assert_eq!(back.parent_id, Some(parent));
    assert_eq!(back.name, "Finance");
    assert!(format!("{folder:?}").contains("Finance"));

    let version = FileVersion {
        file_id: Uuid::new_v4(),
        version: 7,
        s3_key: "files/o/f".into(),
        size_bytes: 9,
        created_by: Uuid::new_v4(),
        created_at: epoch(),
    };
    let back: FileVersion = serde_json::from_value(serde_json::to_value(version.clone()).unwrap())
        .expect("version round-trips");
    assert_eq!(back.version, 7);
    assert_eq!(back.size_bytes, 9);
    assert!(format!("{version:?}").contains("FileVersion"));
}

#[test]
fn list_queries_deserialize_from_query_strings() {
    let folder = Uuid::new_v4();
    let query = Query::<ListFilesQuery>::from_query(&format!(
        "folder_id={folder}&page=3&page_size=10&include_trashed=true"
    ))
    .unwrap()
    .into_inner();
    assert_eq!(query.folder_id, Some(folder));
    assert_eq!(query.page, Some(3));
    assert_eq!(query.page_size, Some(10));
    assert_eq!(query.include_trashed, Some(true));
    assert_eq!(query.owner_id, None);
    assert!(format!("{query:?}").contains("ListFilesQuery"));

    let empty = Query::<ListFilesQuery>::from_query("")
        .unwrap()
        .into_inner();
    assert!(empty.folder_id.is_none() && empty.page.is_none());

    let folders = Query::<ListFoldersQuery>::from_query("")
        .unwrap()
        .into_inner();
    assert!(folders.parent_id.is_none() && folders.owner_id.is_none());
    assert!(format!("{folders:?}").contains("ListFoldersQuery"));

    let activity = Query::<ActivityQuery>::from_query("limit=5")
        .unwrap()
        .into_inner();
    assert_eq!(activity.limit, Some(5));
    assert!(format!("{activity:?}").contains("ActivityQuery"));
}

#[test]
fn request_bodies_deserialize_from_json() {
    let owner = Uuid::new_v4();
    let create: CreateFolderRequest =
        serde_json::from_value(serde_json::json!({"name": "Legal", "owner_id": owner})).unwrap();
    assert_eq!(create.name, "Legal");
    assert_eq!(create.owner_id, owner);
    assert!(create.parent_id.is_none());
    assert!(format!("{create:?}").contains("Legal"));

    let update: UpdateFolderRequest =
        serde_json::from_value(serde_json::json!({"name": "Legal Archive"})).unwrap();
    assert_eq!(update.name.as_deref(), Some("Legal Archive"));
    assert!(format!("{update:?}").contains("UpdateFolderRequest"));

    let mv: MoveFileRequest = serde_json::from_value(serde_json::json!({})).unwrap();
    assert!(mv.folder_id.is_none());
    assert!(format!("{mv:?}").contains("MoveFileRequest"));

    let rename: RenameFileRequest =
        serde_json::from_value(serde_json::json!({"name": "new.txt"})).unwrap();
    assert_eq!(rename.name, "new.txt");
    assert!(format!("{rename:?}").contains("new.txt"));

    let share: ShareFileRequest = serde_json::from_value(serde_json::json!({
        "shared_with": owner,
        "permission": "editor",
        "shared_by": owner,
    }))
    .unwrap();
    assert_eq!(share.permission, SharePermission::Editor);
    assert!(format!("{share:?}").contains("ShareFileRequest"));
}

#[test]
fn response_wrappers_serialize_their_payload() {
    let health = HealthResponse {
        status: "healthy".into(),
        service: "file-service".into(),
        version: "0.1.0".into(),
    };
    assert_eq!(
        serde_json::to_value(&health).unwrap(),
        serde_json::json!({"status": "healthy", "service": "file-service", "version": "0.1.0"})
    );
    assert!(format!("{health:?}").contains("HealthResponse"));

    let upload = UploadResponse {
        file: sample_file(),
    };
    assert_eq!(
        serde_json::to_value(&upload).unwrap()["file"]["name"],
        "report.pdf"
    );
    assert!(format!("{upload:?}").contains("UploadResponse"));

    let download = DownloadResponse {
        url: "https://example.test/x".into(),
        expires_in_secs: 3600,
    };
    let json = serde_json::to_value(&download).unwrap();
    assert_eq!(json["url"], "https://example.test/x");
    assert_eq!(json["expires_in_secs"], 3600);
    assert!(format!("{download:?}").contains("DownloadResponse"));

    let list = ListFilesResponse {
        files: vec![sample_file()],
        total: 1,
        page: 1,
        page_size: 50,
    };
    assert_eq!(serde_json::to_value(&list).unwrap()["total"], 1);
    assert!(format!("{list:?}").contains("ListFilesResponse"));

    let versions = ListVersionsResponse { versions: vec![] };
    assert_eq!(
        serde_json::to_value(&versions).unwrap(),
        serde_json::json!({"versions": []})
    );
    assert!(format!("{versions:?}").contains("ListVersionsResponse"));

    let folders = ListFoldersResponse { folders: vec![] };
    assert_eq!(
        serde_json::to_value(&folders).unwrap(),
        serde_json::json!({"folders": []})
    );
    assert!(format!("{folders:?}").contains("ListFoldersResponse"));

    let share_resp = ShareFileResponse {
        share: FileShare {
            id: Uuid::nil(),
            file_id: Uuid::nil(),
            shared_with: Uuid::nil(),
            permission: SharePermission::Editor,
            shared_by: Uuid::nil(),
            created_at: epoch(),
        },
    };
    assert_eq!(
        serde_json::to_value(&share_resp).unwrap()["share"]["permission"],
        "editor"
    );
    assert!(format!("{share_resp:?}").contains("ShareFileResponse"));
}

#[test]
fn activity_item_renames_type_field_and_wraps_in_items() {
    let item = ActivityItem {
        id: "upload-1".into(),
        activity_type: "upload".into(),
        description: "Uploaded report.pdf".into(),
        actor_name: "You".into(),
        resource_name: "report.pdf".into(),
        resource_type: "file".into(),
        resource_id: "1".into(),
        created_at: epoch().to_rfc3339(),
    };
    let json = serde_json::to_value(&item).unwrap();
    assert_eq!(json["type"], "upload", "activity_type serializes as `type`");
    assert!(json.get("activity_type").is_none());
    assert!(format!("{item:?}").contains("ActivityItem"));

    let resp = ActivityResponse { items: vec![item] };
    assert_eq!(
        serde_json::to_value(&resp).unwrap()["items"][0]["id"],
        "upload-1"
    );
    assert!(format!("{resp:?}").contains("ActivityResponse"));
}
