use actix_multipart::Multipart;
use actix_web::{web, HttpRequest, HttpResponse};
use bytes::BytesMut;
use chrono::Utc;
use futures_util::StreamExt;
use uuid::Uuid;

async fn chaos_active(cm: &mut redis::aio::ConnectionManager, flag: &str) -> bool {
    let result: redis::RedisResult<i64> = redis::cmd("EXISTS").arg(flag).query_async(cm).await;
    result.unwrap_or(0) > 0
}

use crate::config::AppConfig;
use crate::errors::ServiceError;
use crate::events::EventPublisher;
use crate::metadata::MetadataClient;
use crate::middleware;
use crate::models::{
    ActivityItem, ActivityQuery, ActivityResponse, CreateFolderRequest, DownloadResponse,
    FileDetailResponse, FileMetadata, FileShare, FileVersion, Folder, HealthResponse,
    ListFilesQuery, ListFilesResponse, ListFoldersQuery, ListFoldersResponse, ListVersionsResponse,
    MoveFileRequest, RenameFileRequest, ShareFileRequest, ShareFileResponse, UpdateFolderRequest,
    UploadResponse,
};
use crate::storage::S3Client;

// -- Health & Metrics --

pub async fn health() -> HttpResponse {
    HttpResponse::Ok().json(HealthResponse {
        status: "healthy".into(),
        service: "file-service".into(),
        version: env!("CARGO_PKG_VERSION").into(),
    })
}

pub async fn metrics() -> HttpResponse {
    HttpResponse::Ok()
        .content_type("text/plain; charset=utf-8")
        .body(middleware::render_metrics())
}

// -- File Handlers --

pub async fn upload_file(
    req: HttpRequest,
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    config: web::Data<AppConfig>,
    redis_cm: web::Data<redis::aio::ConnectionManager>,
    mut payload: Multipart,
) -> Result<HttpResponse, ServiceError> {
    // Prefer owner_id from X-User-ID header (injected by api-gateway from JWT).
    // Fall back to the multipart field for direct/internal callers.
    let header_owner_id = req
        .headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok());

    let mut file_bytes = BytesMut::new();
    let mut file_name = String::from("unnamed");
    let mut content_type = String::from("application/octet-stream");
    let mut owner_id: Option<Uuid> = None;
    let mut folder_id: Option<Uuid> = None;

    while let Some(item) = payload.next().await {
        let mut field = item.map_err(|e| ServiceError::BadRequest(e.to_string()))?;
        let disposition = field.content_disposition().cloned();
        let field_name = disposition
            .as_ref()
            .and_then(|d| d.get_name().map(|s| s.to_string()))
            .unwrap_or_default();

        match field_name.as_str() {
            "file" => {
                if let Some(fname) = disposition.as_ref().and_then(|d| d.get_filename()) {
                    file_name = fname.to_string();
                }
                if let Some(ct) = field.content_type() {
                    content_type = ct.to_string();
                }
                while let Some(chunk) = field.next().await {
                    let data = chunk.map_err(|e| ServiceError::BadRequest(e.to_string()))?;
                    file_bytes.extend_from_slice(&data);
                    if file_bytes.len() as u64 > config.server.max_upload_bytes {
                        return Err(ServiceError::FileTooLarge {
                            max_bytes: config.server.max_upload_bytes,
                            actual_bytes: file_bytes.len() as u64,
                        });
                    }
                }
            }
            "owner_id" => {
                let mut value = BytesMut::new();
                while let Some(chunk) = field.next().await {
                    let data = chunk.map_err(|e| ServiceError::BadRequest(e.to_string()))?;
                    value.extend_from_slice(&data);
                }
                let s = String::from_utf8_lossy(&value).to_string();
                owner_id = Some(
                    s.trim()
                        .parse::<Uuid>()
                        .map_err(|e| ServiceError::BadRequest(format!("invalid owner_id: {e}")))?,
                );
            }
            "folder_id" => {
                let mut value = BytesMut::new();
                while let Some(chunk) = field.next().await {
                    let data = chunk.map_err(|e| ServiceError::BadRequest(e.to_string()))?;
                    value.extend_from_slice(&data);
                }
                let s = String::from_utf8_lossy(&value).to_string();
                let trimmed = s.trim();
                if !trimmed.is_empty() {
                    folder_id = Some(trimmed.parse::<Uuid>().map_err(|e| {
                        ServiceError::BadRequest(format!("invalid folder_id: {e}"))
                    })?);
                }
            }
            _ => {}
        }
    }

    let owner = header_owner_id
        .or(owner_id)
        .ok_or_else(|| ServiceError::BadRequest("owner_id is required".into()))?;

    if file_bytes.is_empty() {
        return Err(ServiceError::BadRequest("file field is required".into()));
    }

    let file_id = Uuid::new_v4();
    let s3_key = format!("files/{}/{}", owner, file_id);
    let now = Utc::now();
    let size = file_bytes.len() as u64;

    // CHAOS: when FILE_UPLOAD_ALWAYS_FAIL is set, or the Redis chaos flag is
    // active, the S3 client targets a nonexistent bucket, simulating a
    // misconfigured bucket name after a recent infra change.  The AWS SDK
    // returns NoSuchBucket which surfaces as a 500.  The env var is a
    // permanent, per-deployment switch; the Redis flag is transient.
    let effective_bucket = if config.server.upload_always_fail {
        tracing::warn!(
            "FILE_UPLOAD_ALWAYS_FAIL is enabled: redirecting upload to nonexistent bucket"
        );
        "otterworks-files-chaos-nonexistent".to_string()
    } else if chaos_active(
        &mut redis_cm.get_ref().clone(),
        "chaos:file-service:upload_s3_error",
    )
    .await
    {
        tracing::warn!("Chaos flag active: redirecting upload to nonexistent bucket");
        "otterworks-files-chaos-nonexistent".to_string()
    } else {
        s3.bucket.clone()
    };
    let chaos_s3 = crate::storage::S3Client {
        client: s3.client.clone(),
        bucket: effective_bucket,
    };
    chaos_s3
        .upload_object(&s3_key, file_bytes.freeze(), &content_type)
        .await?;

    let file_meta = FileMetadata {
        id: file_id,
        name: file_name,
        mime_type: content_type,
        size_bytes: size,
        s3_key: s3_key.clone(),
        folder_id,
        owner_id: owner,
        version: 1,
        is_trashed: false,
        created_at: now,
        updated_at: now,
    };

    meta.put_file(&file_meta).await?;

    let version = FileVersion {
        file_id,
        version: 1,
        s3_key,
        size_bytes: size,
        created_by: owner,
        created_at: now,
    };
    meta.put_version(&version).await?;

    let _ = events
        .file_uploaded(
            &file_id,
            &owner,
            folder_id.as_ref(),
            &file_meta.name,
            &file_meta.mime_type,
            file_meta.size_bytes,
        )
        .await;

    tracing::info!(file_id = %file_id, name = %file_meta.name, size = %size, "File uploaded");

    Ok(HttpResponse::Created().json(UploadResponse { file: file_meta }))
}

pub async fn get_file_metadata(
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;
    let file = meta.get_file(&file_id).await?;
    let shares = meta.list_shares(&file_id).await.unwrap_or_default();
    Ok(HttpResponse::Ok().json(FileDetailResponse {
        file,
        shared_with: shares,
    }))
}

/// Resolve the effective owner_id for list operations.
///
/// Prefer the `X-User-ID` header injected by the api-gateway from the
/// authenticated JWT. This prevents a caller from spoofing another user's
/// `owner_id` via the query string. Fall back to `query.owner_id` only when
/// no header is present (direct/internal callers).
fn resolve_owner_id(req: &HttpRequest, query_owner_id: Option<Uuid>) -> Option<Uuid> {
    let header_owner_id = req
        .headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok());

    header_owner_id.or(query_owner_id)
}

pub async fn list_files(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    query: web::Query<ListFilesQuery>,
) -> Result<HttpResponse, ServiceError> {
    let include_trashed = query.include_trashed.unwrap_or(false);
    let owner_id = resolve_owner_id(&req, query.owner_id);
    let files = meta
        .list_files(query.folder_id, owner_id, include_trashed)
        .await?;

    let page = query.page.unwrap_or(1).max(1);
    let page_size = query.page_size.unwrap_or(50).min(100);
    let total = files.len();
    let start = (page - 1).saturating_mul(page_size) as usize;
    let paged: Vec<FileMetadata> = files
        .into_iter()
        .skip(start)
        .take(page_size as usize)
        .collect();

    Ok(HttpResponse::Ok().json(ListFilesResponse {
        files: paged,
        total,
        page,
        page_size,
    }))
}

pub async fn list_shared_files(
    meta: web::Data<MetadataClient>,
    req: HttpRequest,
    query: web::Query<ListFilesQuery>,
) -> Result<HttpResponse, ServiceError> {
    let user_id: Uuid = req
        .headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.parse().ok())
        .ok_or_else(|| ServiceError::BadRequest("missing X-User-ID header".into()))?;

    let shares = meta.list_shares_for_user(&user_id).await?;

    // Deduplicate by file_id to handle legacy duplicate share records
    let mut seen_file_ids = std::collections::HashSet::new();
    let mut files = Vec::new();
    for share in &shares {
        if !seen_file_ids.insert(share.file_id) {
            continue;
        }
        match meta.get_file(&share.file_id).await {
            Ok(file) if !file.is_trashed => files.push(file),
            _ => {}
        }
    }

    let page = query.page.unwrap_or(1).max(1);
    let page_size = query.page_size.unwrap_or(50).min(100);
    let total = files.len();
    let start = (page - 1).saturating_mul(page_size) as usize;
    let paged: Vec<FileMetadata> = files
        .into_iter()
        .skip(start)
        .take(page_size as usize)
        .collect();

    Ok(HttpResponse::Ok().json(ListFilesResponse {
        files: paged,
        total,
        page,
        page_size,
    }))
}

pub async fn list_trashed(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    query: web::Query<ListFilesQuery>,
) -> Result<HttpResponse, ServiceError> {
    let owner_id = resolve_owner_id(&req, query.owner_id);
    let files = meta.list_trashed(owner_id).await?;

    let page = query.page.unwrap_or(1).max(1);
    let page_size = query.page_size.unwrap_or(50).min(100);
    let total = files.len();
    let start = (page - 1).saturating_mul(page_size) as usize;
    let paged: Vec<FileMetadata> = files
        .into_iter()
        .skip(start)
        .take(page_size as usize)
        .collect();

    Ok(HttpResponse::Ok().json(ListFilesResponse {
        files: paged,
        total,
        page,
        page_size,
    }))
}
pub async fn delete_file(
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let file = meta.get_file(&file_id).await?;
    meta.delete_file(&file_id).await?;
    s3.delete_object(&file.s3_key).await?;

    let _ = events.file_deleted(&file_id, &file.owner_id).await;

    tracing::info!(file_id = %file_id, "File deleted");
    Ok(HttpResponse::NoContent().finish())
}

pub async fn download_file(
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let file = meta.get_file(&file_id).await?;
    let url = s3.presigned_download_url(&file.s3_key, 3600).await?;

    Ok(HttpResponse::Ok().json(DownloadResponse {
        url,
        expires_in_secs: 3600,
    }))
}

pub async fn move_file(
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
    body: web::Json<MoveFileRequest>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let file = meta.move_file(&file_id, body.folder_id).await?;

    let _ = events
        .file_moved(&file_id, &file.owner_id, body.folder_id.as_ref())
        .await;

    tracing::info!(file_id = %file_id, folder_id = ?body.folder_id, "File moved");
    Ok(HttpResponse::Ok().json(file))
}

pub async fn rename_file(
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
    body: web::Json<RenameFileRequest>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let name = body.name.trim();
    if name.is_empty() {
        return Err(ServiceError::BadRequest("name cannot be empty".into()));
    }

    let file = meta.rename_file(&file_id, name).await?;

    let _ = events
        .file_updated(
            &file_id,
            &file.owner_id,
            file.folder_id.as_ref(),
            &file.name,
            &file.mime_type,
            file.size_bytes as u64,
        )
        .await;

    tracing::info!(file_id = %file_id, new_name = %name, "File renamed");
    Ok(HttpResponse::Ok().json(file))
}

pub async fn list_versions(
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let versions = meta.list_versions(&file_id).await?;
    Ok(HttpResponse::Ok().json(ListVersionsResponse { versions }))
}

pub async fn trash_file(
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let file = meta.trash_file(&file_id).await?;

    let _ = events.file_trashed(&file_id, &file.owner_id).await;

    tracing::info!(file_id = %file_id, "File trashed");
    Ok(HttpResponse::Ok().json(file))
}

pub async fn restore_file(
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let file = meta.restore_file(&file_id).await?;

    let _ = events
        .file_restored(
            &file_id,
            &file.owner_id,
            file.folder_id.as_ref(),
            &file.name,
            &file.mime_type,
            file.size_bytes as u64,
        )
        .await;

    tracing::info!(file_id = %file_id, "File restored");
    Ok(HttpResponse::Ok().json(file))
}

pub async fn share_file(
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
    body: web::Json<ShareFileRequest>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    // Ensure file exists
    let file = meta.get_file(&file_id).await?;

    // Check if share already exists for this file + user
    if let Some(existing) = meta
        .find_existing_share(&file_id, &body.shared_with)
        .await?
    {
        // Update permission if different, otherwise return existing
        if existing.permission != body.permission {
            let updated = FileShare {
                id: existing.id,
                file_id,
                shared_with: body.shared_with,
                permission: body.permission.clone(),
                shared_by: body.shared_by,
                created_at: existing.created_at,
            };
            meta.put_share(&updated).await?;
            tracing::info!(file_id = %file_id, shared_with = %body.shared_with, "File share updated");
            return Ok(HttpResponse::Ok().json(ShareFileResponse { share: updated }));
        }
        tracing::info!(file_id = %file_id, shared_with = %body.shared_with, "File already shared");
        return Ok(HttpResponse::Ok().json(ShareFileResponse { share: existing }));
    }

    let share = FileShare {
        id: Uuid::new_v4(),
        file_id,
        shared_with: body.shared_with,
        permission: body.permission.clone(),
        shared_by: body.shared_by,
        created_at: Utc::now(),
    };

    meta.put_share(&share).await?;

    let _ = events
        .file_shared(&file_id, &file.owner_id, &body.shared_with)
        .await;

    tracing::info!(file_id = %file_id, shared_with = %body.shared_with, "File shared");
    Ok(HttpResponse::Created().json(ShareFileResponse { share }))
}

pub async fn remove_share(
    meta: web::Data<MetadataClient>,
    path: web::Path<(String, String)>,
) -> Result<HttpResponse, ServiceError> {
    let (file_id_str, user_id_str) = path.into_inner();
    let file_id: Uuid = file_id_str
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;
    let user_id: Uuid = user_id_str
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid user id: {e}")))?;

    // Ensure file exists
    let _file = meta.get_file(&file_id).await?;

    // Find the existing share
    let share = meta
        .find_existing_share(&file_id, &user_id)
        .await?
        .ok_or_else(|| ServiceError::ShareNotFound("Share not found".into()))?;

    meta.delete_share(&share.id).await?;

    tracing::info!(file_id = %file_id, user_id = %user_id, "File share removed");
    Ok(HttpResponse::NoContent().finish())
}

// -- Folder Handlers --

pub async fn list_folders(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    query: web::Query<ListFoldersQuery>,
) -> Result<HttpResponse, ServiceError> {
    let owner_id = resolve_owner_id(&req, query.owner_id);
    let folders = meta.list_folders(query.parent_id, owner_id).await?;
    Ok(HttpResponse::Ok().json(ListFoldersResponse { folders }))
}

pub async fn create_folder(
    meta: web::Data<MetadataClient>,
    body: web::Json<CreateFolderRequest>,
) -> Result<HttpResponse, ServiceError> {
    let now = Utc::now();
    let folder = Folder {
        id: Uuid::new_v4(),
        name: body.name.clone(),
        parent_id: body.parent_id,
        owner_id: body.owner_id,
        created_at: now,
        updated_at: now,
    };

    meta.put_folder(&folder).await?;
    tracing::info!(folder_id = %folder.id, name = %folder.name, "Folder created");
    Ok(HttpResponse::Created().json(folder))
}

pub async fn get_folder(
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let folder_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid folder id: {e}")))?;

    let folder = meta.get_folder(&folder_id).await?;
    Ok(HttpResponse::Ok().json(folder))
}

pub async fn update_folder(
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
    body: web::Json<UpdateFolderRequest>,
) -> Result<HttpResponse, ServiceError> {
    let folder_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid folder id: {e}")))?;

    let folder = meta
        .update_folder(&folder_id, body.name.clone(), body.parent_id)
        .await?;
    Ok(HttpResponse::Ok().json(folder))
}

pub async fn delete_folder(
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let folder_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid folder id: {e}")))?;

    meta.delete_folder(&folder_id).await?;
    tracing::info!(folder_id = %folder_id, "Folder deleted");
    Ok(HttpResponse::NoContent().finish())
}

// -- Activity Handler --

pub async fn list_activity(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    query: web::Query<ActivityQuery>,
) -> Result<HttpResponse, ServiceError> {
    let owner_id = req
        .headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok())
        .ok_or_else(|| ServiceError::BadRequest("missing owner context".into()))?;

    let limit = query.limit.unwrap_or(20).min(50) as usize;

    let (files, shares) = futures_util::future::join(
        meta.list_files(None, Some(owner_id), true),
        meta.list_shares_by_owner(&owner_id),
    )
    .await;

    let files = files.unwrap_or_default();
    let shares = shares.unwrap_or_default();

    // Build a file-id → name lookup for share descriptions
    let file_names: std::collections::HashMap<Uuid, String> =
        files.iter().map(|f| (f.id, f.name.clone())).collect();

    let mut items: Vec<ActivityItem> = Vec::new();

    for f in &files {
        items.push(ActivityItem {
            id: format!("upload-{}", f.id),
            activity_type: "upload".into(),
            description: format!("Uploaded {}", f.name),
            actor_name: "You".into(),
            resource_name: f.name.clone(),
            resource_type: "file".into(),
            resource_id: f.id.to_string(),
            created_at: f.created_at.to_rfc3339(),
        });
    }

    for s in &shares {
        let name = file_names
            .get(&s.file_id)
            .cloned()
            .unwrap_or_else(|| "a file".into());
        items.push(ActivityItem {
            id: format!("share-{}", s.id),
            activity_type: "share".into(),
            description: format!("Shared {}", name),
            actor_name: "You".into(),
            resource_name: name,
            resource_type: "file".into(),
            resource_id: s.file_id.to_string(),
            created_at: s.created_at.to_rfc3339(),
        });
    }

    items.sort_by(|a, b| b.created_at.cmp(&a.created_at));
    items.truncate(limit);

    Ok(HttpResponse::Ok().json(ActivityResponse { items }))
}

#[cfg(test)]
mod handler_tests {
    use super::*;
    use crate::config::{AppConfig, ServerConfig, SnsConfig};
    use crate::models::SharePermission;
    use crate::test_support::{
        assert_calls, aws_config_fixture, dynamo_error, empty_get_item_response, file_item_json,
        folder_item_json, form_params, get_item_response, metadata_client, replay, s3_client,
        scan_response, share_item_json, sns_publish_ok, uuid_from, version_item_json, write_ok,
        RedisStub,
    };
    use actix_web::body::MessageBody;
    use actix_web::http::StatusCode;
    use actix_web::test as actix_test;
    use actix_web::FromRequest;
    use aws_smithy_runtime::client::http::test_util::StaticReplayClient;
    use serde_json::Value;

    const FILE: u8 = 1;
    const OWNER: u8 = 2;
    const FOLDER: u8 = 3;
    const SHARE: u8 = 4;
    const OTHER_USER: u8 = 5;

    fn s3_ok() -> (u16, String) {
        (200, String::new())
    }

    fn body_json(resp: HttpResponse) -> Value {
        let bytes = resp.into_body().try_into_bytes().unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    fn meta_data(responses: Vec<(u16, String)>) -> (web::Data<MetadataClient>, StaticReplayClient) {
        let http = replay(responses);
        (web::Data::new(metadata_client(http.clone())), http)
    }

    fn s3_data(responses: Vec<(u16, String)>) -> (web::Data<S3Client>, StaticReplayClient) {
        let http = replay(responses);
        (web::Data::new(s3_client(http.clone())), http)
    }

    /// An event publisher with no topic configured: `publish` short-circuits,
    /// so handler tests never touch SNS.
    fn silent_events() -> web::Data<EventPublisher> {
        web::Data::new(EventPublisher::from_parts(
            crate::test_support::sns_client(replay(vec![])),
            None,
        ))
    }

    /// A publisher with a topic configured, so `publish` actually reaches SNS
    /// and the test can read back the event payload the handler built.
    fn recording_events(
        responses: Vec<(u16, String)>,
    ) -> (web::Data<EventPublisher>, StaticReplayClient) {
        let http = replay(responses);
        let publisher = EventPublisher::from_parts(
            crate::test_support::sns_client(http.clone()),
            Some("arn:aws:sns:us-east-1:000000000000:file-events".into()),
        );
        (web::Data::new(publisher), http)
    }

    /// The single event published through `http`, decoded from the aws-query
    /// `Message` parameter of the SNS `Publish` call.
    fn published_event(http: &StaticReplayClient) -> Value {
        let requests: Vec<_> = http.actual_requests().collect();
        assert_eq!(requests.len(), 1, "exactly one SNS Publish");
        let body = std::str::from_utf8(requests[0].body().bytes().unwrap()).unwrap();
        let message = form_params(body)
            .remove("Message")
            .expect("Publish carries a Message parameter");
        serde_json::from_str(&message).unwrap()
    }

    fn app_config(max_upload_bytes: u64) -> web::Data<AppConfig> {
        web::Data::new(AppConfig {
            server: ServerConfig {
                port: 8082,
                max_upload_bytes,
                upload_always_fail: false,
            },
            aws: aws_config_fixture(),
            sns: SnsConfig { topic_arn: None },
        })
    }

    /// The `FILE_UPLOAD_ALWAYS_FAIL` deployment switch, set on the config the
    /// handler actually reads (no process-wide env mutation needed).
    fn app_config_always_failing() -> web::Data<AppConfig> {
        let mut cfg = (**app_config(1024)).clone();
        cfg.server.upload_always_fail = true;
        web::Data::new(cfg)
    }

    fn request_with_user(user_id: Option<&str>) -> HttpRequest {
        let mut builder = actix_test::TestRequest::default();
        if let Some(id) = user_id {
            builder = builder.insert_header(("X-User-ID", id.to_string()));
        }
        builder.to_http_request()
    }

    fn dynamo_bodies(http: &StaticReplayClient) -> Vec<Value> {
        http.actual_requests()
            .map(|r| serde_json::from_slice(r.body().bytes().unwrap()).unwrap())
            .collect()
    }

    // -- multipart helpers --

    struct Part<'a> {
        name: &'a str,
        filename: Option<&'a str>,
        content_type: Option<&'a str>,
        value: &'a str,
    }

    impl<'a> Part<'a> {
        fn field(name: &'a str, value: &'a str) -> Self {
            Self {
                name,
                filename: None,
                content_type: None,
                value,
            }
        }

        fn file(name: &'a str, filename: &'a str, content_type: &'a str, value: &'a str) -> Self {
            Self {
                name,
                filename: Some(filename),
                content_type: Some(content_type),
                value,
            }
        }
    }

    async fn multipart_request(
        user_id: Option<&str>,
        parts: &[Part<'_>],
    ) -> (HttpRequest, Multipart) {
        const BOUNDARY: &str = "otterworks-test-boundary";
        let mut body = String::new();
        for part in parts {
            body.push_str(&format!("--{BOUNDARY}\r\n"));
            body.push_str(&format!(
                "Content-Disposition: form-data; name=\"{}\"",
                part.name
            ));
            if let Some(filename) = part.filename {
                body.push_str(&format!("; filename=\"{filename}\""));
            }
            body.push_str("\r\n");
            if let Some(content_type) = part.content_type {
                body.push_str(&format!("Content-Type: {content_type}\r\n"));
            }
            body.push_str("\r\n");
            body.push_str(part.value);
            body.push_str("\r\n");
        }
        body.push_str(&format!("--{BOUNDARY}--\r\n"));

        let mut builder = actix_test::TestRequest::post()
            .insert_header((
                "content-type",
                format!("multipart/form-data; boundary={BOUNDARY}"),
            ))
            .set_payload(body);
        if let Some(id) = user_id {
            builder = builder.insert_header(("X-User-ID", id.to_string()));
        }
        let (req, mut payload) = builder.to_http_parts();
        let multipart = Multipart::from_request(&req, &mut payload).await.unwrap();
        (req, multipart)
    }

    // -- health & metrics --

    #[actix_rt::test]
    async fn health_reports_the_service_name_and_crate_version() {
        let body = body_json(health().await);

        assert_eq!(body["status"], "healthy");
        assert_eq!(body["service"], "file-service");
        assert_eq!(body["version"], env!("CARGO_PKG_VERSION"));
    }

    #[actix_rt::test]
    async fn metrics_serves_the_prometheus_exposition_as_plain_text() {
        middleware::HTTP_REQUESTS_TOTAL
            .with_label_values(&["GET", "/metrics-handler", "200"])
            .inc();

        let resp = metrics().await;

        assert_eq!(
            resp.headers().get("content-type").unwrap(),
            "text/plain; charset=utf-8"
        );
        let body = resp.into_body().try_into_bytes().unwrap();
        assert!(String::from_utf8(body.to_vec())
            .unwrap()
            .contains(r#"http_requests_total{method="GET",path="/metrics-handler",status="200"}"#));
    }

    // -- chaos flag --

    #[tokio::test]
    async fn chaos_active_reflects_the_redis_key() {
        let present = RedisStub::start(1).await;
        let absent = RedisStub::start(0).await;

        assert!(chaos_active(&mut present.connection_manager().await, "chaos:flag").await);
        assert!(!chaos_active(&mut absent.connection_manager().await, "chaos:flag").await);
    }

    // -- upload_file --

    #[actix_rt::test]
    async fn upload_file_stores_the_object_metadata_and_first_version() {
        let redis = RedisStub::start(0).await;
        let (s3, s3_http) = s3_data(vec![s3_ok()]);
        let (meta, meta_http) = meta_data(vec![write_ok(), write_ok()]);
        let (req, payload) = multipart_request(
            None,
            &[
                Part::file("file", "report.pdf", "application/pdf", "hello world"),
                Part::field("owner_id", &uuid_from(OWNER).to_string()),
                Part::field("folder_id", &uuid_from(FOLDER).to_string()),
            ],
        )
        .await;

        let resp = upload_file(
            req,
            s3,
            meta,
            silent_events(),
            app_config(1024),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .expect("upload succeeds");

        assert_eq!(resp.status(), StatusCode::CREATED);
        let body = body_json(resp);
        assert_eq!(body["file"]["name"], "report.pdf");
        assert_eq!(body["file"]["mime_type"], "application/pdf");
        assert_eq!(body["file"]["size_bytes"], 11);
        assert_eq!(body["file"]["owner_id"], uuid_from(OWNER).to_string());
        assert_eq!(body["file"]["folder_id"], uuid_from(FOLDER).to_string());
        assert_eq!(body["file"]["version"], 1);

        let uploaded = s3_http.actual_requests().next().expect("one S3 PUT");
        assert_eq!(uploaded.method(), "PUT");
        assert!(uploaded.uri().contains("test-bucket"), "{}", uploaded.uri());
        assert!(
            uploaded
                .uri()
                .contains(&format!("files/{}/", uuid_from(OWNER))),
            "the key is namespaced by owner: {}",
            uploaded.uri()
        );

        let writes = dynamo_bodies(&meta_http);
        assert_eq!(writes[0]["TableName"], "files");
        assert_eq!(writes[1]["TableName"], "versions");
        assert_eq!(writes[1]["Item"]["version"]["N"], "1");
        assert_eq!(writes[1]["Item"]["size_bytes"]["N"], "11");
    }

    #[actix_rt::test]
    async fn upload_file_publishes_the_uploaded_files_descriptor() {
        let redis = RedisStub::start(0).await;
        let (s3, _) = s3_data(vec![s3_ok()]);
        let (meta, _) = meta_data(vec![write_ok(), write_ok()]);
        let (events, sns) = recording_events(vec![sns_publish_ok()]);
        let (req, payload) = multipart_request(
            Some(&uuid_from(OWNER).to_string()),
            &[
                Part::file("file", "report.pdf", "application/pdf", "hello world"),
                Part::field("folder_id", &uuid_from(FOLDER).to_string()),
            ],
        )
        .await;

        upload_file(
            req,
            s3,
            meta,
            events,
            app_config(1024),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .expect("upload succeeds");

        let event = published_event(&sns);
        assert_eq!(event["eventType"], "file_uploaded");
        assert_eq!(event["ownerId"], uuid_from(OWNER).to_string());
        assert_eq!(event["folderId"], uuid_from(FOLDER).to_string());
        assert_eq!(event["name"], "report.pdf");
        assert_eq!(event["mimeType"], "application/pdf");
        assert_eq!(event["sizeBytes"], 11);
    }

    #[actix_rt::test]
    async fn upload_file_survives_a_failing_event_publish() {
        let redis = RedisStub::start(0).await;
        let (s3, _) = s3_data(vec![s3_ok()]);
        let (meta, _) = meta_data(vec![write_ok(), write_ok()]);
        let (events, sns) = recording_events(vec![(
            500,
            "<ErrorResponse><Error><Code>InternalFailure</Code></Error></ErrorResponse>".into(),
        )]);
        let (req, payload) = multipart_request(
            Some(&uuid_from(OWNER).to_string()),
            &[Part::file("file", "a.txt", "text/plain", "x")],
        )
        .await;

        let resp = upload_file(
            req,
            s3,
            meta,
            events,
            app_config(1024),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .expect("SNS is best-effort: the upload still succeeds");

        assert_eq!(resp.status(), StatusCode::CREATED);
        assert_calls(&sns, 1);
    }

    #[actix_rt::test]
    async fn upload_file_prefers_the_gateway_user_header_over_the_form_field() {
        let redis = RedisStub::start(0).await;
        let (s3, s3_http) = s3_data(vec![s3_ok()]);
        let (meta, _) = meta_data(vec![write_ok(), write_ok()]);
        let (req, payload) = multipart_request(
            Some(&uuid_from(OWNER).to_string()),
            &[
                Part::file("file", "a.txt", "text/plain", "x"),
                Part::field("owner_id", &uuid_from(OTHER_USER).to_string()),
            ],
        )
        .await;

        let resp = upload_file(
            req,
            s3,
            meta,
            silent_events(),
            app_config(1024),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .expect("upload succeeds");

        assert_eq!(
            body_json(resp)["file"]["owner_id"],
            uuid_from(OWNER).to_string(),
            "the header wins so a caller cannot spoof another owner"
        );
        let uri = s3_http.actual_requests().next().unwrap().uri().to_string();
        assert!(
            uri.contains(&format!("files/{}/", uuid_from(OWNER))),
            "{uri}"
        );
    }

    #[actix_rt::test]
    async fn upload_file_redirects_to_the_chaos_bucket_when_the_flag_is_set() {
        let redis = RedisStub::start(1).await;
        let (s3, s3_http) = s3_data(vec![s3_ok()]);
        let (meta, _) = meta_data(vec![write_ok(), write_ok()]);
        let (req, payload) = multipart_request(
            Some(&uuid_from(OWNER).to_string()),
            &[Part::file("file", "a.txt", "text/plain", "x")],
        )
        .await;

        upload_file(
            req,
            s3,
            meta,
            silent_events(),
            app_config(1024),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .expect("upload still runs against the chaos bucket");

        let uri = s3_http.actual_requests().next().unwrap().uri().to_string();
        assert!(
            uri.contains("otterworks-files-chaos-nonexistent"),
            "chaos flag redirects the upload: {uri}"
        );
        assert_calls(&s3_http, 1);
    }

    #[actix_rt::test]
    async fn upload_file_redirects_to_the_chaos_bucket_when_always_fail_is_configured() {
        // Redis says the transient flag is *absent*, so only the deployment
        // switch can redirect this upload.
        let redis = RedisStub::start(0).await;
        let (s3, s3_http) = s3_data(vec![s3_ok()]);
        let (meta, _) = meta_data(vec![write_ok(), write_ok()]);
        let (req, payload) = multipart_request(
            Some(&uuid_from(OWNER).to_string()),
            &[Part::file("file", "a.txt", "text/plain", "x")],
        )
        .await;

        upload_file(
            req,
            s3,
            meta,
            silent_events(),
            app_config_always_failing(),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .expect("upload still runs against the chaos bucket");

        let uri = s3_http.actual_requests().next().unwrap().uri().to_string();
        assert!(
            uri.contains("otterworks-files-chaos-nonexistent"),
            "FILE_UPLOAD_ALWAYS_FAIL redirects the upload: {uri}"
        );
        assert_calls(&s3_http, 1);
    }

    #[actix_rt::test]
    async fn upload_file_requires_an_owner() {
        let redis = RedisStub::start(0).await;
        let (s3, _) = s3_data(vec![]);
        let (meta, _) = meta_data(vec![]);
        let (req, payload) =
            multipart_request(None, &[Part::file("file", "a.txt", "text/plain", "x")]).await;

        let err = upload_file(
            req,
            s3,
            meta,
            silent_events(),
            app_config(1024),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .unwrap_err();

        assert_eq!(err.to_string(), "Bad request: owner_id is required");
    }

    #[actix_rt::test]
    async fn upload_file_rejects_an_empty_file_field() {
        let redis = RedisStub::start(0).await;
        let (s3, _) = s3_data(vec![]);
        let (meta, _) = meta_data(vec![]);
        let (req, payload) = multipart_request(
            None,
            &[
                Part::field("owner_id", &uuid_from(OWNER).to_string()),
                Part::field("folder_id", "   "),
                Part::field("unrelated", "ignored"),
            ],
        )
        .await;

        let err = upload_file(
            req,
            s3,
            meta,
            silent_events(),
            app_config(1024),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .unwrap_err();

        assert_eq!(err.to_string(), "Bad request: file field is required");
    }

    #[actix_rt::test]
    async fn upload_file_enforces_the_configured_size_limit() {
        let redis = RedisStub::start(0).await;
        let (s3, _) = s3_data(vec![]);
        let (meta, _) = meta_data(vec![]);
        let (req, payload) = multipart_request(
            Some(&uuid_from(OWNER).to_string()),
            &[Part::file(
                "file",
                "big.bin",
                "application/octet-stream",
                "0123456789",
            )],
        )
        .await;

        let err = upload_file(
            req,
            s3,
            meta,
            silent_events(),
            app_config(4),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .unwrap_err();

        assert!(
            matches!(
                err,
                ServiceError::FileTooLarge {
                    max_bytes: 4,
                    actual_bytes
                } if actual_bytes > 4
            ),
            "{err:?}"
        );
    }

    #[actix_rt::test]
    async fn upload_file_rejects_malformed_ids() {
        for (part, expected) in [
            (
                Part::field("owner_id", "not-a-uuid"),
                "Bad request: invalid owner_id",
            ),
            (
                Part::field("folder_id", "not-a-uuid"),
                "Bad request: invalid folder_id",
            ),
        ] {
            let redis = RedisStub::start(0).await;
            let (s3, _) = s3_data(vec![]);
            let (meta, _) = meta_data(vec![]);
            let (req, payload) = multipart_request(
                Some(&uuid_from(OWNER).to_string()),
                &[Part::file("file", "a.txt", "text/plain", "x"), part],
            )
            .await;

            let err = upload_file(
                req,
                s3,
                meta,
                silent_events(),
                app_config(1024),
                web::Data::new(redis.connection_manager().await),
                payload,
            )
            .await
            .unwrap_err();

            assert!(err.to_string().starts_with(expected), "{err}");
        }
    }

    #[actix_rt::test]
    async fn upload_file_defaults_the_name_and_content_type() {
        let redis = RedisStub::start(0).await;
        let (s3, _) = s3_data(vec![s3_ok()]);
        let (meta, _) = meta_data(vec![write_ok(), write_ok()]);
        let mut parts = vec![Part::file("file", "a.txt", "text/plain", "x")];
        parts[0].filename = None;
        parts[0].content_type = None;
        let (req, payload) = multipart_request(Some(&uuid_from(OWNER).to_string()), &parts).await;

        let body = body_json(
            upload_file(
                req,
                s3,
                meta,
                silent_events(),
                app_config(1024),
                web::Data::new(redis.connection_manager().await),
                payload,
            )
            .await
            .expect("upload succeeds"),
        );

        assert_eq!(body["file"]["name"], "unnamed");
        assert_eq!(body["file"]["mime_type"], "application/octet-stream");
        assert!(body["file"]["folder_id"].is_null());
    }

    #[actix_rt::test]
    async fn upload_file_propagates_storage_failures() {
        let redis = RedisStub::start(0).await;
        let (s3, _) = s3_data(vec![(
            500,
            "<Error><Code>NoSuchBucket</Code></Error>".into(),
        )]);
        let (meta, _) = meta_data(vec![]);
        let (req, payload) = multipart_request(
            Some(&uuid_from(OWNER).to_string()),
            &[Part::file("file", "a.txt", "text/plain", "x")],
        )
        .await;

        let err = upload_file(
            req,
            s3,
            meta,
            silent_events(),
            app_config(1024),
            web::Data::new(redis.connection_manager().await),
            payload,
        )
        .await
        .unwrap_err();

        assert!(matches!(err, ServiceError::S3Error(_)), "{err:?}");
    }

    // -- get_file_metadata --

    #[actix_rt::test]
    async fn get_file_metadata_returns_the_file_with_its_shares() {
        let (meta, _) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            scan_response(&[share_item_json(
                uuid_from(SHARE),
                uuid_from(FILE),
                uuid_from(OTHER_USER),
                uuid_from(OWNER),
                "editor",
            )]),
        ]);

        let body = body_json(
            get_file_metadata(meta, uuid_from(FILE).to_string().into())
                .await
                .expect("ok"),
        );

        assert_eq!(body["id"], uuid_from(FILE).to_string());
        assert_eq!(body["shared_with"][0]["permission"], "editor");
    }

    #[actix_rt::test]
    async fn get_file_metadata_tolerates_a_failing_share_lookup() {
        let (meta, _) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            dynamo_error(500, "InternalServerError"),
        ]);

        let body = body_json(
            get_file_metadata(meta, uuid_from(FILE).to_string().into())
                .await
                .expect("the file is still returned"),
        );

        assert_eq!(body["shared_with"].as_array().unwrap().len(), 0);
    }

    #[actix_rt::test]
    async fn get_file_metadata_rejects_a_malformed_id() {
        let (meta, _) = meta_data(vec![]);

        let err = get_file_metadata(meta, "nope".to_string().into())
            .await
            .unwrap_err();

        assert!(err.to_string().starts_with("Bad request: invalid file id"));
    }

    #[actix_rt::test]
    async fn get_file_metadata_propagates_a_missing_file() {
        let (meta, _) = meta_data(vec![empty_get_item_response()]);

        let err = get_file_metadata(meta, uuid_from(FILE).to_string().into())
            .await
            .unwrap_err();

        assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    }

    // -- list handlers --

    #[actix_rt::test]
    async fn list_files_pages_the_results_and_honours_the_user_header() {
        let items: Vec<String> = (10..=13)
            .map(|b| file_item_json(uuid_from(b), uuid_from(OWNER), None))
            .collect();
        let (meta, http) = meta_data(vec![scan_response(&items)]);

        let resp = list_files(
            request_with_user(Some(&uuid_from(OWNER).to_string())),
            meta,
            web::Query(ListFilesQuery {
                folder_id: Some(uuid_from(FOLDER)),
                owner_id: Some(uuid_from(OTHER_USER)),
                page: Some(2),
                page_size: Some(3),
                include_trashed: Some(true),
            }),
        )
        .await
        .expect("ok");

        let body = body_json(resp);
        assert_eq!(body["total"], 4);
        assert_eq!(body["page"], 2);
        assert_eq!(body["page_size"], 3);
        assert_eq!(
            body["files"].as_array().unwrap().len(),
            1,
            "the second page holds the remaining item"
        );
        let scan = &dynamo_bodies(&http)[0];
        assert_eq!(
            scan["ExpressionAttributeValues"][":owner_id"]["S"],
            uuid_from(OWNER).to_string(),
            "the header owner overrides the query string"
        );
        assert!(
            !scan["FilterExpression"]
                .as_str()
                .unwrap()
                .contains("is_trashed"),
            "include_trashed drops the trashed filter"
        );
    }

    #[actix_rt::test]
    async fn list_files_defaults_to_the_first_page_of_fifty() {
        let (meta, http) = meta_data(vec![scan_response(&[file_item_json(
            uuid_from(FILE),
            uuid_from(OWNER),
            None,
        )])]);

        let body = body_json(
            list_files(
                request_with_user(None),
                meta,
                web::Query(ListFilesQuery {
                    folder_id: None,
                    owner_id: None,
                    page: None,
                    page_size: None,
                    include_trashed: None,
                }),
            )
            .await
            .expect("ok"),
        );

        assert_eq!(body["page"], 1);
        assert_eq!(body["page_size"], 50);
        assert_eq!(body["files"].as_array().unwrap().len(), 1);
        assert_eq!(
            dynamo_bodies(&http)[0]["FilterExpression"],
            "is_trashed = :trashed"
        );
    }

    #[actix_rt::test]
    async fn list_files_caps_the_page_size_at_one_hundred() {
        let (meta, _) = meta_data(vec![scan_response(&[])]);

        let body = body_json(
            list_files(
                request_with_user(None),
                meta,
                web::Query(ListFilesQuery {
                    folder_id: None,
                    owner_id: None,
                    page: Some(0),
                    page_size: Some(1000),
                    include_trashed: None,
                }),
            )
            .await
            .expect("ok"),
        );

        assert_eq!(body["page"], 1, "page 0 is clamped to the first page");
        assert_eq!(body["page_size"], 100);
    }

    #[actix_rt::test]
    async fn list_files_propagates_metadata_failures() {
        let (meta, _) = meta_data(vec![dynamo_error(500, "InternalServerError")]);

        let err = list_files(
            request_with_user(None),
            meta,
            web::Query(ListFilesQuery {
                folder_id: None,
                owner_id: None,
                page: None,
                page_size: None,
                include_trashed: None,
            }),
        )
        .await
        .unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[actix_rt::test]
    async fn list_shared_files_deduplicates_and_hides_trashed_files() {
        let trashed = file_item_json(uuid_from(OTHER_USER), uuid_from(OWNER), None).replace(
            r#""is_trashed":{"BOOL":false}"#,
            r#""is_trashed":{"BOOL":true}"#,
        );
        let (meta, _) = meta_data(vec![
            scan_response(&[
                share_item_json(
                    uuid_from(SHARE),
                    uuid_from(FILE),
                    uuid_from(OTHER_USER),
                    uuid_from(OWNER),
                    "viewer",
                ),
                // duplicate share row for the same file
                share_item_json(
                    uuid_from(6),
                    uuid_from(FILE),
                    uuid_from(OTHER_USER),
                    uuid_from(OWNER),
                    "editor",
                ),
                share_item_json(
                    uuid_from(7),
                    uuid_from(OTHER_USER),
                    uuid_from(OTHER_USER),
                    uuid_from(OWNER),
                    "viewer",
                ),
                share_item_json(
                    uuid_from(8),
                    uuid_from(9),
                    uuid_from(OTHER_USER),
                    uuid_from(OWNER),
                    "viewer",
                ),
            ]),
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            get_item_response(&trashed),
            empty_get_item_response(),
        ]);

        let body = body_json(
            list_shared_files(
                meta,
                request_with_user(Some(&uuid_from(OTHER_USER).to_string())),
                web::Query(ListFilesQuery {
                    folder_id: None,
                    owner_id: None,
                    page: None,
                    page_size: None,
                    include_trashed: None,
                }),
            )
            .await
            .expect("ok"),
        );

        assert_eq!(
            body["total"], 1,
            "duplicate, trashed and missing files drop out"
        );
        assert_eq!(body["files"][0]["id"], uuid_from(FILE).to_string());
    }

    #[actix_rt::test]
    async fn list_shared_files_requires_the_user_header() {
        let (meta, _) = meta_data(vec![]);

        let err = list_shared_files(
            meta,
            request_with_user(None),
            web::Query(ListFilesQuery {
                folder_id: None,
                owner_id: None,
                page: None,
                page_size: None,
                include_trashed: None,
            }),
        )
        .await
        .unwrap_err();

        assert_eq!(err.to_string(), "Bad request: missing X-User-ID header");
    }

    #[actix_rt::test]
    async fn list_shared_files_propagates_share_lookup_failures() {
        let (meta, _) = meta_data(vec![dynamo_error(500, "InternalServerError")]);

        let err = list_shared_files(
            meta,
            request_with_user(Some(&uuid_from(OTHER_USER).to_string())),
            web::Query(ListFilesQuery {
                folder_id: None,
                owner_id: None,
                page: None,
                page_size: None,
                include_trashed: None,
            }),
        )
        .await
        .unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[actix_rt::test]
    async fn list_trashed_returns_the_owners_trash() {
        let (meta, http) = meta_data(vec![scan_response(&[file_item_json(
            uuid_from(FILE),
            uuid_from(OWNER),
            None,
        )])]);

        let body = body_json(
            list_trashed(
                request_with_user(Some(&uuid_from(OWNER).to_string())),
                meta,
                web::Query(ListFilesQuery {
                    folder_id: None,
                    owner_id: None,
                    page: Some(1),
                    page_size: Some(10),
                    include_trashed: None,
                }),
            )
            .await
            .expect("ok"),
        );

        assert_eq!(body["total"], 1);
        assert_eq!(body["files"][0]["id"], uuid_from(FILE).to_string());
        assert_eq!(
            dynamo_bodies(&http)[0]["ExpressionAttributeValues"][":owner_id"]["S"],
            uuid_from(OWNER).to_string()
        );
    }

    #[actix_rt::test]
    async fn list_trashed_propagates_metadata_failures() {
        let (meta, _) = meta_data(vec![dynamo_error(500, "InternalServerError")]);

        let err = list_trashed(
            request_with_user(None),
            meta,
            web::Query(ListFilesQuery {
                folder_id: None,
                owner_id: None,
                page: None,
                page_size: None,
                include_trashed: None,
            }),
        )
        .await
        .unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    // -- single-file operations --

    #[actix_rt::test]
    async fn delete_file_removes_the_metadata_and_the_object() {
        let (meta, meta_http) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            write_ok(),
        ]);
        let (s3, s3_http) = s3_data(vec![(204, String::new())]);

        let resp = delete_file(
            s3,
            meta,
            silent_events(),
            uuid_from(FILE).to_string().into(),
        )
        .await
        .expect("ok");

        assert_eq!(resp.status(), StatusCode::NO_CONTENT);
        assert_eq!(
            dynamo_bodies(&meta_http)[1]["Key"]["id"]["S"],
            uuid_from(FILE).to_string()
        );
        let deleted = s3_http.actual_requests().next().expect("one S3 DELETE");
        assert_eq!(deleted.method(), "DELETE");
        assert!(deleted.uri().contains(&uuid_from(FILE).to_string()));
    }

    #[actix_rt::test]
    async fn delete_file_rejects_a_malformed_id() {
        let (meta, _) = meta_data(vec![]);
        let (s3, _) = s3_data(vec![]);

        let err = delete_file(s3, meta, silent_events(), "nope".to_string().into())
            .await
            .unwrap_err();

        assert!(err.to_string().starts_with("Bad request: invalid file id"));
    }

    #[actix_rt::test]
    async fn download_file_returns_a_presigned_url_valid_for_an_hour() {
        let (meta, _) = meta_data(vec![get_item_response(&file_item_json(
            uuid_from(FILE),
            uuid_from(OWNER),
            None,
        ))]);
        let (s3, _) = s3_data(vec![]);

        let body = body_json(
            download_file(s3, meta, uuid_from(FILE).to_string().into())
                .await
                .expect("ok"),
        );

        assert_eq!(body["expires_in_secs"], 3600);
        let url = body["url"].as_str().unwrap();
        assert!(url.contains("X-Amz-Expires=3600"), "{url}");
        assert!(url.contains(&uuid_from(FILE).to_string()), "{url}");
    }

    #[actix_rt::test]
    async fn download_file_rejects_a_malformed_id() {
        let (meta, _) = meta_data(vec![]);
        let (s3, _) = s3_data(vec![]);

        let err = download_file(s3, meta, "nope".to_string().into())
            .await
            .unwrap_err();

        assert!(err.to_string().starts_with("Bad request: invalid file id"));
    }

    #[actix_rt::test]
    async fn move_file_updates_the_folder() {
        let (meta, http) = meta_data(vec![
            write_ok(),
            get_item_response(&file_item_json(
                uuid_from(FILE),
                uuid_from(OWNER),
                Some(uuid_from(FOLDER)),
            )),
        ]);

        let body = body_json(
            move_file(
                meta,
                silent_events(),
                uuid_from(FILE).to_string().into(),
                web::Json(MoveFileRequest {
                    folder_id: Some(uuid_from(FOLDER)),
                }),
            )
            .await
            .expect("ok"),
        );

        assert_eq!(body["folder_id"], uuid_from(FOLDER).to_string());
        assert_eq!(
            dynamo_bodies(&http)[0]["UpdateExpression"],
            "SET folder_id = :f, updated_at = :u"
        );
    }

    #[actix_rt::test]
    async fn move_file_rejects_a_malformed_id() {
        let (meta, _) = meta_data(vec![]);

        let err = move_file(
            meta,
            silent_events(),
            "nope".to_string().into(),
            web::Json(MoveFileRequest { folder_id: None }),
        )
        .await
        .unwrap_err();

        assert!(err.to_string().starts_with("Bad request: invalid file id"));
    }

    #[actix_rt::test]
    async fn rename_file_trims_the_new_name() {
        let (meta, http) = meta_data(vec![
            write_ok(),
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
        ]);

        let resp = rename_file(
            meta,
            silent_events(),
            uuid_from(FILE).to_string().into(),
            web::Json(RenameFileRequest {
                name: "  renamed.pdf  ".into(),
            }),
        )
        .await
        .expect("ok");

        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(
            dynamo_bodies(&http)[0]["ExpressionAttributeValues"][":n"]["S"],
            "renamed.pdf"
        );
    }

    #[actix_rt::test]
    async fn rename_file_rejects_blank_names_and_malformed_ids() {
        let (meta, _) = meta_data(vec![]);
        let blank = rename_file(
            meta,
            silent_events(),
            uuid_from(FILE).to_string().into(),
            web::Json(RenameFileRequest { name: "   ".into() }),
        )
        .await
        .unwrap_err();
        assert_eq!(blank.to_string(), "Bad request: name cannot be empty");

        let (meta, _) = meta_data(vec![]);
        let bad_id = rename_file(
            meta,
            silent_events(),
            "nope".to_string().into(),
            web::Json(RenameFileRequest { name: "x".into() }),
        )
        .await
        .unwrap_err();
        assert!(bad_id
            .to_string()
            .starts_with("Bad request: invalid file id"));
    }

    #[actix_rt::test]
    async fn list_versions_returns_the_version_history() {
        let (meta, _) = meta_data(vec![scan_response(&[
            version_item_json(uuid_from(FILE), uuid_from(OWNER), 2),
            version_item_json(uuid_from(FILE), uuid_from(OWNER), 1),
        ])]);

        let body = body_json(
            list_versions(meta, uuid_from(FILE).to_string().into())
                .await
                .expect("ok"),
        );

        assert_eq!(body["versions"][0]["version"], 2);
        assert_eq!(body["versions"][1]["version"], 1);
    }

    #[actix_rt::test]
    async fn list_versions_rejects_a_malformed_id() {
        let (meta, _) = meta_data(vec![]);

        let err = list_versions(meta, "nope".to_string().into())
            .await
            .unwrap_err();

        assert!(err.to_string().starts_with("Bad request: invalid file id"));
    }

    #[actix_rt::test]
    async fn trash_file_flags_the_file() {
        let trashed = file_item_json(uuid_from(FILE), uuid_from(OWNER), None).replace(
            r#""is_trashed":{"BOOL":false}"#,
            r#""is_trashed":{"BOOL":true}"#,
        );
        let (meta, _) = meta_data(vec![write_ok(), get_item_response(&trashed)]);

        let body = body_json(
            trash_file(meta, silent_events(), uuid_from(FILE).to_string().into())
                .await
                .expect("ok"),
        );

        assert_eq!(body["is_trashed"], true);
    }

    #[actix_rt::test]
    async fn trash_file_rejects_a_malformed_id() {
        let (meta, _) = meta_data(vec![]);

        let err = trash_file(meta, silent_events(), "nope".to_string().into())
            .await
            .unwrap_err();

        assert!(err.to_string().starts_with("Bad request: invalid file id"));
    }

    #[actix_rt::test]
    async fn restore_file_clears_the_flag() {
        let (meta, http) = meta_data(vec![
            write_ok(),
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
        ]);

        let body = body_json(
            restore_file(meta, silent_events(), uuid_from(FILE).to_string().into())
                .await
                .expect("ok"),
        );

        assert_eq!(body["is_trashed"], false);
        assert_eq!(
            dynamo_bodies(&http)[0]["ExpressionAttributeValues"][":t"]["BOOL"],
            false
        );
    }

    #[actix_rt::test]
    async fn restore_file_rejects_a_malformed_id() {
        let (meta, _) = meta_data(vec![]);

        let err = restore_file(meta, silent_events(), "nope".to_string().into())
            .await
            .unwrap_err();

        assert!(err.to_string().starts_with("Bad request: invalid file id"));
    }

    // -- sharing --

    fn share_request(permission: SharePermission) -> web::Json<ShareFileRequest> {
        web::Json(ShareFileRequest {
            shared_with: uuid_from(OTHER_USER),
            permission,
            shared_by: uuid_from(OWNER),
        })
    }

    #[actix_rt::test]
    async fn share_file_creates_a_new_share() {
        let (meta, http) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            scan_response(&[]),
            write_ok(),
        ]);

        let resp = share_file(
            meta,
            silent_events(),
            uuid_from(FILE).to_string().into(),
            share_request(SharePermission::Editor),
        )
        .await
        .expect("ok");

        assert_eq!(resp.status(), StatusCode::CREATED);
        let body = body_json(resp);
        assert_eq!(body["share"]["permission"], "editor");
        assert_eq!(
            body["share"]["shared_with"],
            uuid_from(OTHER_USER).to_string()
        );
        assert_eq!(dynamo_bodies(&http)[2]["Item"]["permission"]["S"], "editor");
    }

    #[actix_rt::test]
    async fn share_file_publishes_the_share_event_on_create_only() {
        // Creating a share notifies downstream consumers ...
        let (meta, _) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            scan_response(&[]),
            write_ok(),
        ]);
        let (events, sns) = recording_events(vec![sns_publish_ok()]);

        share_file(
            meta,
            events,
            uuid_from(FILE).to_string().into(),
            share_request(SharePermission::Editor),
        )
        .await
        .expect("ok");

        let event = published_event(&sns);
        assert_eq!(event["eventType"], "file_shared");
        assert_eq!(event["fileId"], uuid_from(FILE).to_string());
        assert_eq!(event["ownerId"], uuid_from(OWNER).to_string());
        assert_eq!(
            event["sharedWithUserId"],
            uuid_from(OTHER_USER).to_string(),
            "consumers learn who gained access"
        );

        // ... but upgrading an existing share returns early and publishes nothing.
        let (meta, _) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            scan_response(&[share_item_json(
                uuid_from(SHARE),
                uuid_from(FILE),
                uuid_from(OTHER_USER),
                uuid_from(OWNER),
                "viewer",
            )]),
            write_ok(),
        ]);
        let (events, sns) = recording_events(vec![sns_publish_ok()]);

        share_file(
            meta,
            events,
            uuid_from(FILE).to_string().into(),
            share_request(SharePermission::Editor),
        )
        .await
        .expect("ok");

        assert_calls(&sns, 0);
    }

    #[actix_rt::test]
    async fn share_file_upgrades_the_permission_of_an_existing_share() {
        let (meta, http) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            scan_response(&[share_item_json(
                uuid_from(SHARE),
                uuid_from(FILE),
                uuid_from(OTHER_USER),
                uuid_from(OWNER),
                "viewer",
            )]),
            write_ok(),
        ]);

        let resp = share_file(
            meta,
            silent_events(),
            uuid_from(FILE).to_string().into(),
            share_request(SharePermission::Editor),
        )
        .await
        .expect("ok");

        assert_eq!(
            resp.status(),
            StatusCode::OK,
            "the share is updated in place"
        );
        let body = body_json(resp);
        assert_eq!(body["share"]["id"], uuid_from(SHARE).to_string());
        assert_eq!(body["share"]["permission"], "editor");
        assert_eq!(dynamo_bodies(&http)[2]["Item"]["permission"]["S"], "editor");
    }

    #[actix_rt::test]
    async fn share_file_is_idempotent_for_an_unchanged_permission() {
        let (meta, http) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            scan_response(&[share_item_json(
                uuid_from(SHARE),
                uuid_from(FILE),
                uuid_from(OTHER_USER),
                uuid_from(OWNER),
                "viewer",
            )]),
        ]);

        let resp = share_file(
            meta,
            silent_events(),
            uuid_from(FILE).to_string().into(),
            share_request(SharePermission::Viewer),
        )
        .await
        .expect("ok");

        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(body_json(resp)["share"]["id"], uuid_from(SHARE).to_string());
        assert_eq!(
            http.actual_requests().count(),
            2,
            "nothing is written when the permission already matches"
        );
    }

    #[actix_rt::test]
    async fn share_file_rejects_a_malformed_id_and_a_missing_file() {
        let (meta, _) = meta_data(vec![]);
        let bad_id = share_file(
            meta,
            silent_events(),
            "nope".to_string().into(),
            share_request(SharePermission::Viewer),
        )
        .await
        .unwrap_err();
        assert!(bad_id
            .to_string()
            .starts_with("Bad request: invalid file id"));

        let (meta, _) = meta_data(vec![empty_get_item_response()]);
        let missing = share_file(
            meta,
            silent_events(),
            uuid_from(FILE).to_string().into(),
            share_request(SharePermission::Viewer),
        )
        .await
        .unwrap_err();
        assert!(matches!(missing, ServiceError::FileNotFound(_)));
    }

    #[actix_rt::test]
    async fn remove_share_deletes_the_share_row() {
        let (meta, http) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            scan_response(&[share_item_json(
                uuid_from(SHARE),
                uuid_from(FILE),
                uuid_from(OTHER_USER),
                uuid_from(OWNER),
                "viewer",
            )]),
            write_ok(),
        ]);

        let resp = remove_share(
            meta,
            (
                uuid_from(FILE).to_string(),
                uuid_from(OTHER_USER).to_string(),
            )
                .into(),
        )
        .await
        .expect("ok");

        assert_eq!(resp.status(), StatusCode::NO_CONTENT);
        assert_eq!(
            dynamo_bodies(&http)[2]["Key"]["id"]["S"],
            uuid_from(SHARE).to_string()
        );
    }

    #[actix_rt::test]
    async fn remove_share_reports_a_missing_share() {
        let (meta, _) = meta_data(vec![
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
            scan_response(&[]),
        ]);

        let err = remove_share(
            meta,
            (
                uuid_from(FILE).to_string(),
                uuid_from(OTHER_USER).to_string(),
            )
                .into(),
        )
        .await
        .unwrap_err();

        assert!(matches!(err, ServiceError::ShareNotFound(_)), "{err:?}");
    }

    #[actix_rt::test]
    async fn remove_share_rejects_malformed_ids() {
        let (meta, _) = meta_data(vec![]);
        let bad_file = remove_share(
            meta,
            ("nope".to_string(), uuid_from(OTHER_USER).to_string()).into(),
        )
        .await
        .unwrap_err();
        assert!(bad_file
            .to_string()
            .starts_with("Bad request: invalid file id"));

        let (meta, _) = meta_data(vec![]);
        let bad_user = remove_share(
            meta,
            (uuid_from(FILE).to_string(), "nope".to_string()).into(),
        )
        .await
        .unwrap_err();
        assert!(bad_user
            .to_string()
            .starts_with("Bad request: invalid user id"));
    }

    // -- folders --

    #[actix_rt::test]
    async fn list_folders_scopes_to_the_header_owner() {
        let (meta, http) = meta_data(vec![scan_response(&[folder_item_json(
            uuid_from(FOLDER),
            uuid_from(OWNER),
            None,
        )])]);

        let body = body_json(
            list_folders(
                request_with_user(Some(&uuid_from(OWNER).to_string())),
                meta,
                web::Query(ListFoldersQuery {
                    parent_id: None,
                    owner_id: None,
                }),
            )
            .await
            .expect("ok"),
        );

        assert_eq!(body["folders"][0]["name"], "Finance");
        assert_eq!(
            dynamo_bodies(&http)[0]["ExpressionAttributeValues"][":owner_id"]["S"],
            uuid_from(OWNER).to_string()
        );
    }

    #[actix_rt::test]
    async fn create_folder_persists_and_returns_the_new_folder() {
        let (meta, http) = meta_data(vec![write_ok()]);

        let resp = create_folder(
            meta,
            web::Json(CreateFolderRequest {
                name: "Finance".into(),
                parent_id: Some(uuid_from(FOLDER)),
                owner_id: uuid_from(OWNER),
            }),
        )
        .await
        .expect("ok");

        assert_eq!(resp.status(), StatusCode::CREATED);
        let body = body_json(resp);
        assert_eq!(body["name"], "Finance");
        assert_eq!(body["parent_id"], uuid_from(FOLDER).to_string());
        assert_eq!(body["owner_id"], uuid_from(OWNER).to_string());
        assert_eq!(dynamo_bodies(&http)[0]["Item"]["name"]["S"], "Finance");
    }

    #[actix_rt::test]
    async fn create_folder_propagates_metadata_failures() {
        let (meta, _) = meta_data(vec![dynamo_error(500, "InternalServerError")]);

        let err = create_folder(
            meta,
            web::Json(CreateFolderRequest {
                name: "Finance".into(),
                parent_id: None,
                owner_id: uuid_from(OWNER),
            }),
        )
        .await
        .unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[actix_rt::test]
    async fn get_folder_returns_the_folder_and_rejects_bad_ids() {
        let (meta, _) = meta_data(vec![get_item_response(&folder_item_json(
            uuid_from(FOLDER),
            uuid_from(OWNER),
            None,
        ))]);
        let body = body_json(
            get_folder(meta, uuid_from(FOLDER).to_string().into())
                .await
                .expect("ok"),
        );
        assert_eq!(body["id"], uuid_from(FOLDER).to_string());

        let (meta, _) = meta_data(vec![]);
        let err = get_folder(meta, "nope".to_string().into())
            .await
            .unwrap_err();
        assert!(err
            .to_string()
            .starts_with("Bad request: invalid folder id"));
    }

    #[actix_rt::test]
    async fn update_folder_renames_the_folder() {
        let (meta, http) = meta_data(vec![
            write_ok(),
            get_item_response(&folder_item_json(uuid_from(FOLDER), uuid_from(OWNER), None)),
        ]);

        let resp = update_folder(
            meta,
            uuid_from(FOLDER).to_string().into(),
            web::Json(UpdateFolderRequest {
                name: Some("Renamed".into()),
                parent_id: None,
            }),
        )
        .await
        .expect("ok");

        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(
            dynamo_bodies(&http)[0]["ExpressionAttributeValues"][":n"]["S"],
            "Renamed"
        );
    }

    #[actix_rt::test]
    async fn update_folder_rejects_a_malformed_id() {
        let (meta, _) = meta_data(vec![]);

        let err = update_folder(
            meta,
            "nope".to_string().into(),
            web::Json(UpdateFolderRequest {
                name: None,
                parent_id: None,
            }),
        )
        .await
        .unwrap_err();

        assert!(err
            .to_string()
            .starts_with("Bad request: invalid folder id"));
    }

    #[actix_rt::test]
    async fn delete_folder_removes_the_row_and_rejects_bad_ids() {
        let (meta, http) = meta_data(vec![write_ok()]);
        let resp = delete_folder(meta, uuid_from(FOLDER).to_string().into())
            .await
            .expect("ok");
        assert_eq!(resp.status(), StatusCode::NO_CONTENT);
        assert_eq!(
            dynamo_bodies(&http)[0]["Key"]["id"]["S"],
            uuid_from(FOLDER).to_string()
        );

        let (meta, _) = meta_data(vec![]);
        let err = delete_folder(meta, "nope".to_string().into())
            .await
            .unwrap_err();
        assert!(err
            .to_string()
            .starts_with("Bad request: invalid folder id"));
    }

    // -- activity --

    #[actix_rt::test]
    async fn list_activity_merges_uploads_and_shares_newest_first() {
        let older_file = file_item_json(uuid_from(FILE), uuid_from(OWNER), None)
            .replace("2024-05-17T12:30:45+00:00", "2024-01-01T00:00:00+00:00");
        let (meta, _) = meta_data(vec![
            scan_response(&[older_file]),
            scan_response(&[
                share_item_json(
                    uuid_from(SHARE),
                    uuid_from(FILE),
                    uuid_from(OTHER_USER),
                    uuid_from(OWNER),
                    "viewer",
                ),
                share_item_json(
                    uuid_from(6),
                    uuid_from(9),
                    uuid_from(OTHER_USER),
                    uuid_from(OWNER),
                    "viewer",
                ),
            ]),
        ]);

        let body = body_json(
            list_activity(
                request_with_user(Some(&uuid_from(OWNER).to_string())),
                meta,
                web::Query(ActivityQuery { limit: None }),
            )
            .await
            .expect("ok"),
        );

        let items = body["items"].as_array().unwrap();
        assert_eq!(items.len(), 3);
        assert_eq!(items[0]["type"], "share", "newest first");
        assert_eq!(items[0]["description"], "Shared report.pdf");
        assert_eq!(
            items[1]["description"], "Shared a file",
            "shares of unknown files fall back to a generic name"
        );
        assert_eq!(items[2]["type"], "upload");
        assert_eq!(items[2]["description"], "Uploaded report.pdf");
        assert_eq!(items[2]["id"], format!("upload-{}", uuid_from(FILE)));
    }

    #[actix_rt::test]
    async fn list_activity_truncates_to_the_requested_limit() {
        let files: Vec<String> = (10..=14)
            .map(|b| file_item_json(uuid_from(b), uuid_from(OWNER), None))
            .collect();
        let (meta, _) = meta_data(vec![scan_response(&files), scan_response(&[])]);

        let body = body_json(
            list_activity(
                request_with_user(Some(&uuid_from(OWNER).to_string())),
                meta,
                web::Query(ActivityQuery { limit: Some(2) }),
            )
            .await
            .expect("ok"),
        );

        assert_eq!(body["items"].as_array().unwrap().len(), 2);
    }

    #[actix_rt::test]
    async fn list_activity_is_empty_when_both_lookups_fail() {
        let (meta, _) = meta_data(vec![
            dynamo_error(500, "InternalServerError"),
            dynamo_error(500, "InternalServerError"),
        ]);

        let body = body_json(
            list_activity(
                request_with_user(Some(&uuid_from(OWNER).to_string())),
                meta,
                web::Query(ActivityQuery { limit: Some(100) }),
            )
            .await
            .expect("failures degrade to an empty feed"),
        );

        assert_eq!(body["items"].as_array().unwrap().len(), 0);
    }

    #[actix_rt::test]
    async fn list_activity_requires_the_user_header() {
        let (meta, _) = meta_data(vec![]);

        let err = list_activity(
            request_with_user(None),
            meta,
            web::Query(ActivityQuery { limit: None }),
        )
        .await
        .unwrap_err();

        assert_eq!(err.to_string(), "Bad request: missing owner context");
    }

    #[actix_rt::test]
    async fn resolve_owner_id_prefers_the_header_and_ignores_junk() {
        let query_owner = Some(uuid_from(OTHER_USER));

        assert_eq!(
            resolve_owner_id(
                &request_with_user(Some(&format!(" {} ", uuid_from(OWNER)))),
                query_owner
            ),
            Some(uuid_from(OWNER)),
            "the header is trimmed and wins"
        );
        assert_eq!(
            resolve_owner_id(&request_with_user(Some("not-a-uuid")), query_owner),
            query_owner,
            "an unparseable header falls back to the query"
        );
        assert_eq!(
            resolve_owner_id(&request_with_user(None), query_owner),
            query_owner
        );
        assert_eq!(resolve_owner_id(&request_with_user(None), None), None);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[actix_rt::test]
    async fn test_health_endpoint() {
        let resp = health().await;
        assert_eq!(resp.status(), actix_web::http::StatusCode::OK);
    }

    #[actix_rt::test]
    async fn test_metrics_endpoint() {
        let resp = metrics().await;
        assert_eq!(resp.status(), actix_web::http::StatusCode::OK);
    }
}
