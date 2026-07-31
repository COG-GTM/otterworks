use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

// ── File Metadata ──────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileMetadata {
    pub id: Uuid,
    pub name: String,
    pub mime_type: String,
    pub size_bytes: u64,
    pub s3_key: String,
    pub folder_id: Option<Uuid>,
    pub owner_id: Uuid,
    pub version: u32,
    pub is_trashed: bool,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

#[derive(Debug, Serialize)]
pub struct FileDetailResponse {
    #[serde(flatten)]
    pub file: FileMetadata,
    pub shared_with: Vec<FileShare>,
}

// ── Folder ─────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Folder {
    pub id: Uuid,
    pub name: String,
    pub parent_id: Option<Uuid>,
    pub owner_id: Uuid,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

// ── File Version ───────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileVersion {
    pub file_id: Uuid,
    pub version: u32,
    pub s3_key: String,
    pub size_bytes: u64,
    pub created_by: Uuid,
    pub created_at: DateTime<Utc>,
}

// ── File Share ─────────────────────────────────────────────────────────

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileShare {
    pub id: Uuid,
    pub file_id: Uuid,
    pub shared_with: Uuid,
    pub permission: SharePermission,
    pub shared_by: Uuid,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum SharePermission {
    Viewer,
    Editor,
}

impl std::fmt::Display for SharePermission {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            SharePermission::Viewer => write!(f, "viewer"),
            SharePermission::Editor => write!(f, "editor"),
        }
    }
}

impl SharePermission {
    pub fn from_str_value(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "viewer" => Some(SharePermission::Viewer),
            "editor" => Some(SharePermission::Editor),
            _ => None,
        }
    }
}

// ── Request / Response Types ───────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct HealthResponse {
    pub status: String,
    pub service: String,
    pub version: String,
}

#[derive(Debug, Serialize)]
pub struct UploadResponse {
    pub file: FileMetadata,
}

#[derive(Debug, Serialize)]
pub struct DownloadResponse {
    pub url: String,
    pub expires_in_secs: u64,
}

#[derive(Debug, Deserialize)]
pub struct ListFilesQuery {
    pub folder_id: Option<Uuid>,
    pub owner_id: Option<Uuid>,
    pub page: Option<u32>,
    pub page_size: Option<u32>,
    pub include_trashed: Option<bool>,
}

#[derive(Debug, Serialize)]
pub struct ListFilesResponse {
    pub files: Vec<FileMetadata>,
    pub total: usize,
    pub page: u32,
    pub page_size: u32,
}

#[derive(Debug, Serialize)]
pub struct ListVersionsResponse {
    pub versions: Vec<FileVersion>,
}

#[derive(Debug, Deserialize)]
pub struct ListFoldersQuery {
    pub parent_id: Option<Uuid>,
    pub owner_id: Option<Uuid>,
}

#[derive(Debug, Serialize)]
pub struct ListFoldersResponse {
    pub folders: Vec<Folder>,
}

#[derive(Debug, Deserialize)]
pub struct CreateFolderRequest {
    pub name: String,
    pub parent_id: Option<Uuid>,
    pub owner_id: Uuid,
}

#[derive(Debug, Deserialize)]
pub struct UpdateFolderRequest {
    pub name: Option<String>,
    pub parent_id: Option<Uuid>,
}

#[derive(Debug, Deserialize)]
pub struct MoveFileRequest {
    pub folder_id: Option<Uuid>,
}

#[derive(Debug, Deserialize)]
pub struct RenameFileRequest {
    pub name: String,
}

#[derive(Debug, Deserialize)]
pub struct ShareFileRequest {
    pub shared_with: Uuid,
    pub permission: SharePermission,
    pub shared_by: Uuid,
}

#[derive(Debug, Serialize)]
pub struct ShareFileResponse {
    pub share: FileShare,
}

// ── Activity ───────────────────────────────────────────────────────────

#[derive(Debug, Serialize)]
pub struct ActivityItem {
    pub id: String,
    #[serde(rename = "type")]
    pub activity_type: String,
    pub description: String,
    pub actor_name: String,
    pub resource_name: String,
    pub resource_type: String,
    pub resource_id: String,
    pub created_at: String,
}

#[derive(Debug, Deserialize)]
pub struct ActivityQuery {
    pub limit: Option<u32>,
}

#[derive(Debug, Serialize)]
pub struct ActivityResponse {
    pub items: Vec<ActivityItem>,
}

#[cfg(test)]
mod models_tests {
    use super::*;
    use crate::test_support::{fixed_time, uuid_from};

    fn file() -> FileMetadata {
        FileMetadata {
            id: uuid_from(1),
            name: "report.pdf".into(),
            mime_type: "application/pdf".into(),
            size_bytes: 2048,
            s3_key: "files/a/b".into(),
            folder_id: Some(uuid_from(2)),
            owner_id: uuid_from(3),
            version: 2,
            is_trashed: false,
            created_at: fixed_time(),
            updated_at: fixed_time(),
        }
    }

    fn share() -> FileShare {
        FileShare {
            id: uuid_from(4),
            file_id: uuid_from(1),
            shared_with: uuid_from(5),
            permission: SharePermission::Viewer,
            shared_by: uuid_from(3),
            created_at: fixed_time(),
        }
    }

    #[test]
    fn share_permission_renders_lowercase_in_json_and_display() {
        assert_eq!(SharePermission::Viewer.to_string(), "viewer");
        assert_eq!(SharePermission::Editor.to_string(), "editor");
        assert_eq!(
            serde_json::to_string(&SharePermission::Viewer).unwrap(),
            "\"viewer\""
        );
        assert_eq!(
            serde_json::to_string(&SharePermission::Editor).unwrap(),
            "\"editor\""
        );
    }

    #[test]
    fn share_permission_parses_case_insensitively() {
        for input in ["viewer", "VIEWER", "Viewer"] {
            assert_eq!(
                SharePermission::from_str_value(input),
                Some(SharePermission::Viewer),
                "{input}"
            );
        }
        for input in ["editor", "EDITOR", "Editor"] {
            assert_eq!(
                SharePermission::from_str_value(input),
                Some(SharePermission::Editor),
                "{input}"
            );
        }
        assert_eq!(SharePermission::from_str_value("owner"), None);
        assert_eq!(SharePermission::from_str_value(""), None);
    }

    #[test]
    fn file_metadata_round_trips_through_json() {
        let original = file();
        let json = serde_json::to_string(&original).unwrap();
        let parsed: FileMetadata = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.id, original.id);
        assert_eq!(parsed.name, original.name);
        assert_eq!(parsed.size_bytes, original.size_bytes);
        assert_eq!(parsed.folder_id, original.folder_id);
        assert_eq!(parsed.version, original.version);
        assert_eq!(parsed.created_at, original.created_at);
        assert!(format!("{:?}", original.clone()).contains("report.pdf"));
    }

    #[test]
    fn file_detail_response_flattens_the_file_fields() {
        let value = serde_json::to_value(FileDetailResponse {
            file: file(),
            shared_with: vec![share()],
        })
        .unwrap();
        assert_eq!(value["name"], "report.pdf", "file fields are flattened");
        assert_eq!(value["shared_with"][0]["permission"], "viewer");
    }

    #[test]
    fn folder_and_version_round_trip_through_json() {
        let folder = Folder {
            id: uuid_from(6),
            name: "Finance".into(),
            parent_id: None,
            owner_id: uuid_from(3),
            created_at: fixed_time(),
            updated_at: fixed_time(),
        };
        let parsed: Folder =
            serde_json::from_str(&serde_json::to_string(&folder).unwrap()).unwrap();
        assert_eq!(parsed.name, "Finance");
        assert_eq!(parsed.parent_id, None);
        assert!(format!("{:?}", folder.clone()).contains("Finance"));

        let version = FileVersion {
            file_id: uuid_from(1),
            version: 7,
            s3_key: "files/a/b".into(),
            size_bytes: 99,
            created_by: uuid_from(3),
            created_at: fixed_time(),
        };
        let parsed: FileVersion =
            serde_json::from_str(&serde_json::to_string(&version).unwrap()).unwrap();
        assert_eq!(parsed.version, 7);
        assert_eq!(parsed.size_bytes, 99);
        assert!(format!("{:?}", version.clone()).contains("files/a/b"));
    }

    #[test]
    fn file_share_round_trips_and_compares_by_permission() {
        let original = share();
        let parsed: FileShare =
            serde_json::from_str(&serde_json::to_string(&original).unwrap()).unwrap();
        assert_eq!(parsed.permission, SharePermission::Viewer);
        assert_ne!(parsed.permission, SharePermission::Editor);
        assert_eq!(parsed.shared_with, original.shared_with);
        assert!(format!("{:?}", original.clone()).contains("Viewer"));
    }

    #[test]
    fn list_queries_deserialize_from_query_strings() {
        let files = actix_web::web::Query::<ListFilesQuery>::from_query(&format!(
            "folder_id={}&owner_id={}&page=2&page_size=10&include_trashed=true",
            uuid_from(2),
            uuid_from(3)
        ))
        .unwrap()
        .into_inner();
        assert_eq!(files.folder_id, Some(uuid_from(2)));
        assert_eq!(files.owner_id, Some(uuid_from(3)));
        assert_eq!(files.page, Some(2));
        assert_eq!(files.page_size, Some(10));
        assert_eq!(files.include_trashed, Some(true));

        let empty = actix_web::web::Query::<ListFilesQuery>::from_query("")
            .unwrap()
            .into_inner();
        assert_eq!(empty.page, None);
        assert_eq!(empty.include_trashed, None);

        let folders = actix_web::web::Query::<ListFoldersQuery>::from_query(&format!(
            "parent_id={}",
            uuid_from(2)
        ))
        .unwrap()
        .into_inner();
        assert_eq!(folders.parent_id, Some(uuid_from(2)));
        assert_eq!(folders.owner_id, None);

        let activity = actix_web::web::Query::<ActivityQuery>::from_query("limit=5")
            .unwrap()
            .into_inner();
        assert_eq!(activity.limit, Some(5));
    }

    #[test]
    fn request_bodies_deserialize_from_json() {
        let create: CreateFolderRequest = serde_json::from_str(&format!(
            r#"{{"name":"Docs","owner_id":"{}"}}"#,
            uuid_from(3)
        ))
        .unwrap();
        assert_eq!(create.name, "Docs");
        assert_eq!(create.parent_id, None);

        let update: UpdateFolderRequest =
            serde_json::from_str(r#"{"name":"Renamed","parent_id":null}"#).unwrap();
        assert_eq!(update.name.as_deref(), Some("Renamed"));

        let move_req: MoveFileRequest =
            serde_json::from_str(&format!(r#"{{"folder_id":"{}"}}"#, uuid_from(2))).unwrap();
        assert_eq!(move_req.folder_id, Some(uuid_from(2)));

        let rename: RenameFileRequest = serde_json::from_str(r#"{"name":"new.txt"}"#).unwrap();
        assert_eq!(rename.name, "new.txt");

        let share_req: ShareFileRequest = serde_json::from_str(&format!(
            r#"{{"shared_with":"{}","permission":"editor","shared_by":"{}"}}"#,
            uuid_from(5),
            uuid_from(3)
        ))
        .unwrap();
        assert_eq!(share_req.permission, SharePermission::Editor);
        assert_eq!(share_req.shared_with, uuid_from(5));
    }

    #[test]
    fn response_wrappers_serialize_their_payloads() {
        let health = serde_json::to_value(HealthResponse {
            status: "healthy".into(),
            service: "file-service".into(),
            version: "0.1.0".into(),
        })
        .unwrap();
        assert_eq!(health["status"], "healthy");

        let upload = serde_json::to_value(UploadResponse { file: file() }).unwrap();
        assert_eq!(upload["file"]["name"], "report.pdf");

        let download = serde_json::to_value(DownloadResponse {
            url: "https://example.test/x".into(),
            expires_in_secs: 3600,
        })
        .unwrap();
        assert_eq!(download["expires_in_secs"], 3600);

        let list_files = serde_json::to_value(ListFilesResponse {
            files: vec![file()],
            total: 1,
            page: 1,
            page_size: 50,
        })
        .unwrap();
        assert_eq!(list_files["total"], 1);
        assert_eq!(list_files["files"][0]["mime_type"], "application/pdf");

        let versions = serde_json::to_value(ListVersionsResponse {
            versions: Vec::new(),
        })
        .unwrap();
        assert_eq!(versions["versions"].as_array().unwrap().len(), 0);

        let folders = serde_json::to_value(ListFoldersResponse {
            folders: Vec::new(),
        })
        .unwrap();
        assert!(folders["folders"].is_array());

        let share_resp = serde_json::to_value(ShareFileResponse { share: share() }).unwrap();
        assert_eq!(share_resp["share"]["permission"], "viewer");
    }

    #[test]
    fn activity_items_serialize_type_under_the_type_key() {
        let response = ActivityResponse {
            items: vec![ActivityItem {
                id: "upload-1".into(),
                activity_type: "upload".into(),
                description: "Uploaded report.pdf".into(),
                actor_name: "You".into(),
                resource_name: "report.pdf".into(),
                resource_type: "file".into(),
                resource_id: uuid_from(1).to_string(),
                created_at: fixed_time().to_rfc3339(),
            }],
        };
        let value = serde_json::to_value(&response).unwrap();
        assert_eq!(value["items"][0]["type"], "upload");
        assert_eq!(value["items"][0]["description"], "Uploaded report.pdf");
        assert!(format!("{response:?}").contains("ActivityResponse"));
    }
}
