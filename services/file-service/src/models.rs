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
pub(crate) mod test_support {
    use aws_smithy_runtime::client::http::test_util::{ReplayEvent, StaticReplayClient};
    use aws_smithy_types::body::SdkBody;
    use aws_smithy_types::retry::RetryConfig;

    /// Build a replay client that answers each call with the next `(status, body)`
    /// pair, so tests exercise the real AWS SDK stack without any network.
    pub(crate) fn replay_client(responses: Vec<(u16, String)>) -> StaticReplayClient {
        StaticReplayClient::new(
            responses
                .into_iter()
                .map(|(status, body)| {
                    ReplayEvent::new(
                        http::Request::builder()
                            .uri("https://example.test/")
                            .body(SdkBody::empty())
                            .unwrap(),
                        http::Response::builder()
                            .status(status)
                            .body(SdkBody::from(body))
                            .unwrap(),
                    )
                })
                .collect::<Vec<_>>(),
        )
    }

    pub(crate) fn dynamo_client(
        responses: Vec<(u16, String)>,
    ) -> (aws_sdk_dynamodb::Client, StaticReplayClient) {
        let http = replay_client(responses);
        let conf = aws_sdk_dynamodb::Config::builder()
            .behavior_version(aws_sdk_dynamodb::config::BehaviorVersion::latest())
            .region(aws_sdk_dynamodb::config::Region::new("us-east-1"))
            .credentials_provider(aws_sdk_dynamodb::config::Credentials::for_tests())
            .retry_config(RetryConfig::disabled())
            .http_client(http.clone())
            .build();
        (aws_sdk_dynamodb::Client::from_conf(conf), http)
    }

    pub(crate) fn s3_client(
        responses: Vec<(u16, String)>,
    ) -> (aws_sdk_s3::Client, StaticReplayClient) {
        let http = replay_client(responses);
        let conf = aws_sdk_s3::Config::builder()
            .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
            .region(aws_sdk_s3::config::Region::new("us-east-1"))
            .credentials_provider(aws_sdk_s3::config::Credentials::for_tests())
            .retry_config(RetryConfig::disabled())
            .http_client(http.clone())
            .build();
        (aws_sdk_s3::Client::from_conf(conf), http)
    }

    pub(crate) fn sns_client(
        responses: Vec<(u16, String)>,
    ) -> (aws_sdk_sns::Client, StaticReplayClient) {
        let http = replay_client(responses);
        let conf = aws_sdk_sns::Config::builder()
            .behavior_version(aws_sdk_sns::config::BehaviorVersion::latest())
            .region(aws_sdk_sns::config::Region::new("us-east-1"))
            .credentials_provider(aws_sdk_sns::config::Credentials::for_tests())
            .retry_config(RetryConfig::disabled())
            .http_client(http.clone())
            .build();
        (aws_sdk_sns::Client::from_conf(conf), http)
    }
}

#[cfg(test)]
mod model_tests {
    use super::*;

    fn sample_file() -> FileMetadata {
        FileMetadata {
            id: Uuid::nil(),
            name: "report.pdf".into(),
            mime_type: "application/pdf".into(),
            size_bytes: 42,
            s3_key: "files/x/y".into(),
            folder_id: None,
            owner_id: Uuid::nil(),
            version: 2,
            is_trashed: false,
            created_at: DateTime::from_timestamp(0, 0).unwrap(),
            updated_at: DateTime::from_timestamp(0, 0).unwrap(),
        }
    }

    #[test]
    fn share_permission_displays_lowercase_wire_values() {
        assert_eq!(SharePermission::Viewer.to_string(), "viewer");
        assert_eq!(SharePermission::Editor.to_string(), "editor");
    }

    #[test]
    fn share_permission_parses_case_insensitively_and_rejects_unknown() {
        for raw in ["viewer", "VIEWER", "Viewer"] {
            assert_eq!(
                SharePermission::from_str_value(raw),
                Some(SharePermission::Viewer)
            );
        }
        for raw in ["editor", "EDITOR"] {
            assert_eq!(
                SharePermission::from_str_value(raw),
                Some(SharePermission::Editor)
            );
        }
        assert_eq!(SharePermission::from_str_value("owner"), None);
    }

    #[test]
    fn file_metadata_round_trips_through_json() {
        let file = sample_file();
        let json = serde_json::to_string(&file).unwrap();
        let parsed: FileMetadata = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.name, file.name);
        assert_eq!(parsed.size_bytes, 42);
        assert_eq!(parsed.version, 2);
        assert!(parsed.folder_id.is_none());
    }

    #[test]
    fn file_detail_response_flattens_the_file_fields() {
        let body = serde_json::to_value(FileDetailResponse {
            file: sample_file(),
            shared_with: vec![],
        })
        .unwrap();
        assert_eq!(body["name"], "report.pdf");
        assert_eq!(body["size_bytes"], 42);
        assert!(body["shared_with"].as_array().unwrap().is_empty());
    }

    #[test]
    fn share_permission_serializes_lowercase() {
        let json = serde_json::to_string(&SharePermission::Editor).unwrap();
        assert_eq!(json, "\"editor\"");
        let parsed: SharePermission = serde_json::from_str("\"viewer\"").unwrap();
        assert_eq!(parsed, SharePermission::Viewer);
    }
}
