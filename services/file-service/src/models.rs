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
mod tests {
    use super::*;

    #[test]
    fn share_permission_displays_lowercase() {
        assert_eq!(SharePermission::Viewer.to_string(), "viewer");
        assert_eq!(SharePermission::Editor.to_string(), "editor");
    }

    #[test]
    fn share_permission_parses_case_insensitively() {
        let cases = [
            ("viewer", Some(SharePermission::Viewer)),
            ("VIEWER", Some(SharePermission::Viewer)),
            ("Editor", Some(SharePermission::Editor)),
            ("editor", Some(SharePermission::Editor)),
            ("owner", None),
            ("", None),
        ];
        for (input, expected) in cases {
            assert_eq!(SharePermission::from_str_value(input), expected, "{input}");
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
    }

    #[test]
    fn file_metadata_round_trips_through_json() {
        let now = Utc::now();
        let file = FileMetadata {
            id: Uuid::new_v4(),
            name: "report.pdf".into(),
            mime_type: "application/pdf".into(),
            size_bytes: 42,
            s3_key: "files/a/b".into(),
            folder_id: Some(Uuid::new_v4()),
            owner_id: Uuid::new_v4(),
            version: 2,
            is_trashed: false,
            created_at: now,
            updated_at: now,
        };
        let json = serde_json::to_string(&file).unwrap();
        let back: FileMetadata = serde_json::from_str(&json).unwrap();
        assert_eq!(back.id, file.id);
        assert_eq!(back.name, file.name);
        assert_eq!(back.folder_id, file.folder_id);
        assert_eq!(back.version, 2);
    }

    #[test]
    fn file_detail_response_flattens_the_file() {
        let now = Utc::now();
        let file_id = Uuid::new_v4();
        let detail = FileDetailResponse {
            file: FileMetadata {
                id: file_id,
                name: "notes.txt".into(),
                mime_type: "text/plain".into(),
                size_bytes: 1,
                s3_key: "files/x".into(),
                folder_id: None,
                owner_id: Uuid::new_v4(),
                version: 1,
                is_trashed: true,
                created_at: now,
                updated_at: now,
            },
            shared_with: vec![],
        };
        let value: serde_json::Value = serde_json::to_value(&detail).unwrap();
        assert_eq!(value["name"], "notes.txt", "file fields are flattened");
        assert_eq!(value["shared_with"], serde_json::json!([]));
    }

    #[test]
    fn list_files_query_defaults_missing_fields_to_none() {
        let query: ListFilesQuery = serde_json::from_str("{}").unwrap();
        assert!(query.folder_id.is_none());
        assert!(query.owner_id.is_none());
        assert!(query.page.is_none());
        assert!(query.page_size.is_none());
        assert!(query.include_trashed.is_none());
    }

    #[test]
    fn activity_item_renames_type_field() {
        let item = ActivityItem {
            id: "upload-1".into(),
            activity_type: "upload".into(),
            description: "Uploaded a.txt".into(),
            actor_name: "You".into(),
            resource_name: "a.txt".into(),
            resource_type: "file".into(),
            resource_id: "1".into(),
            created_at: Utc::now().to_rfc3339(),
        };
        let value = serde_json::to_value(&item).unwrap();
        assert_eq!(value["type"], "upload");
    }
}
