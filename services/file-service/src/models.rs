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
    /// Address of an invitee who has no OtterWorks account yet. Set only
    /// while the share is a pending invite.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub invited_email: Option<String>,
    #[serde(default)]
    pub status: ShareStatus,
    pub permission: SharePermission,
    pub shared_by: Uuid,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Clone, Copy, Default, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ShareStatus {
    #[default]
    Active,
    Pending,
}

impl std::fmt::Display for ShareStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ShareStatus::Active => write!(f, "active"),
            ShareStatus::Pending => write!(f, "pending"),
        }
    }
}

impl ShareStatus {
    pub fn from_str_value(s: &str) -> Option<Self> {
        match s {
            "active" => Some(ShareStatus::Active),
            "pending" => Some(ShareStatus::Pending),
            _ => None,
        }
    }
}

/// Deterministic recipient id for an invitee without an account, so repeat
/// invites to the same address resolve to the same share record.
pub fn pending_invitee_id(email: &str) -> Uuid {
    Uuid::new_v5(&Uuid::NAMESPACE_DNS, email.as_bytes())
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
    pub shared_with: Option<Uuid>,
    pub shared_with_email: Option<String>,
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
