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

#[cfg(test)]
mod handler_tests {
    use super::*;
    use crate::config::{AwsConfig, ServerConfig, SnsConfig};
    use crate::models::{SharePermission, UpdateFolderRequest};
    use actix_web::body::MessageBody;
    use actix_web::http::StatusCode;
    use actix_web::test::TestRequest;
    use actix_web::ResponseError;
    use aws_smithy_runtime::client::http::test_util::StaticReplayClient;
    use chrono::DateTime;

    const OK_EMPTY: &str = "{}";
    const DYNAMO_ERROR: &str =
        r#"{"__type":"com.amazonaws.dynamodb.v20120810#InternalServerError","message":"boom"}"#;
    const S3_ERROR: &str = "<Error><Code>InternalError</Code></Error>";

    fn ok(body: &str) -> (u16, String) {
        (200, body.to_string())
    }

    fn dynamo_boom() -> (u16, String) {
        (500, DYNAMO_ERROR.to_string())
    }

    fn meta_data(responses: Vec<(u16, String)>) -> web::Data<MetadataClient> {
        let (client, _http) = crate::models::test_support::dynamo_client(responses);
        web::Data::new(MetadataClient {
            client,
            files_table: "files".into(),
            folders_table: "folders".into(),
            versions_table: "versions".into(),
            shares_table: "shares".into(),
        })
    }

    fn meta_data_spy(
        responses: Vec<(u16, String)>,
    ) -> (web::Data<MetadataClient>, StaticReplayClient) {
        let (client, http) = crate::models::test_support::dynamo_client(responses);
        (
            web::Data::new(MetadataClient {
                client,
                files_table: "files".into(),
                folders_table: "folders".into(),
                versions_table: "versions".into(),
                shares_table: "shares".into(),
            }),
            http,
        )
    }

    fn s3_data(responses: Vec<(u16, String)>) -> web::Data<S3Client> {
        let (client, _http) = crate::models::test_support::s3_client(responses);
        web::Data::new(S3Client {
            client,
            bucket: "test-bucket".into(),
        })
    }

    fn events_data() -> web::Data<EventPublisher> {
        let (client, _http) = crate::models::test_support::sns_client(vec![]);
        web::Data::new(EventPublisher::for_tests(client, None))
    }

    fn body_json(resp: HttpResponse) -> serde_json::Value {
        let bytes = resp.into_body().try_into_bytes().unwrap();
        serde_json::from_slice(&bytes).unwrap()
    }

    fn epoch_rfc3339() -> String {
        DateTime::from_timestamp(0, 0).unwrap().to_rfc3339()
    }

    fn file_item(id: Uuid, owner: Uuid, name: &str, trashed: bool) -> String {
        format!(
            r#"{{"id":{{"S":"{id}"}},"name":{{"S":"{name}"}},"mime_type":{{"S":"text/plain"}},"size_bytes":{{"N":"10"}},"s3_key":{{"S":"files/{owner}/{id}"}},"owner_id":{{"S":"{owner}"}},"version":{{"N":"1"}},"is_trashed":{{"BOOL":{trashed}}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}},"updated_at":{{"S":"1970-01-01T00:00:00+00:00"}}}}"#
        )
    }

    fn folder_item(id: Uuid, owner: Uuid, name: &str) -> String {
        format!(
            r#"{{"id":{{"S":"{id}"}},"name":{{"S":"{name}"}},"owner_id":{{"S":"{owner}"}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}},"updated_at":{{"S":"1970-01-01T00:00:00+00:00"}}}}"#
        )
    }

    fn share_item(id: Uuid, file_id: Uuid, user: Uuid, permission: &str) -> String {
        format!(
            r#"{{"id":{{"S":"{id}"}},"file_id":{{"S":"{file_id}"}},"shared_with":{{"S":"{user}"}},"permission":{{"S":"{permission}"}},"shared_by":{{"S":"{user}"}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}}}}"#
        )
    }

    fn version_item(file_id: Uuid, user: Uuid, version: u32) -> String {
        format!(
            r#"{{"file_id":{{"S":"{file_id}"}},"version":{{"N":"{version}"}},"s3_key":{{"S":"files/{file_id}/v{version}"}},"size_bytes":{{"N":"10"}},"created_by":{{"S":"{user}"}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}}}}"#
        )
    }

    fn item_response(item: &str) -> String {
        format!(r#"{{"Item":{item}}}"#)
    }

    fn scan_response(items: &[String]) -> String {
        format!(
            r#"{{"Items":[{}],"Count":{}}}"#,
            items.join(","),
            items.len()
        )
    }

    fn query<T: serde::de::DeserializeOwned>(qs: &str) -> web::Query<T> {
        web::Query::<T>::from_query(qs).expect("query parses")
    }

    fn path(value: Uuid) -> web::Path<String> {
        web::Path::from(value.to_string())
    }

    fn user_request(user_id: Option<Uuid>) -> HttpRequest {
        match user_id {
            Some(id) => TestRequest::default()
                .insert_header(("X-User-ID", id.to_string()))
                .to_http_request(),
            None => TestRequest::default().to_http_request(),
        }
    }

    #[actix_web::test]
    async fn health_reports_the_service_identity() {
        let body = body_json(health().await);
        assert_eq!(body["status"], "healthy");
        assert_eq!(body["service"], "file-service");
        assert_eq!(body["version"], env!("CARGO_PKG_VERSION"));
    }

    #[actix_web::test]
    async fn metrics_serves_the_prometheus_exposition_format() {
        middleware::HTTP_REQUESTS_TOTAL
            .with_label_values(&["GET", "/handler-metrics-test", "200"])
            .inc();

        let resp = metrics().await;
        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(
            resp.headers().get("content-type").unwrap(),
            "text/plain; charset=utf-8"
        );
        let body = resp.into_body().try_into_bytes().unwrap();
        assert!(String::from_utf8(body.to_vec())
            .unwrap()
            .contains("path=\"/handler-metrics-test\""));
    }

    // -- get_file_metadata --

    #[actix_web::test]
    async fn get_file_metadata_returns_the_file_and_its_shares() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            ok(&scan_response(&[share_item(
                Uuid::new_v4(),
                id,
                Uuid::new_v4(),
                "viewer",
            )])),
        ]);

        let body = body_json(
            get_file_metadata(meta, path(id))
                .await
                .expect("metadata is returned"),
        );

        assert_eq!(body["id"], id.to_string());
        assert_eq!(body["name"], "a.txt");
        assert_eq!(body["shared_with"].as_array().unwrap().len(), 1);
    }

    #[actix_web::test]
    async fn get_file_metadata_tolerates_a_failing_share_lookup() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            dynamo_boom(),
        ]);

        let body = body_json(get_file_metadata(meta, path(id)).await.expect("still 200"));

        assert!(body["shared_with"].as_array().unwrap().is_empty());
    }

    #[actix_web::test]
    async fn get_file_metadata_rejects_a_malformed_id() {
        let meta = meta_data(vec![]);
        let err = get_file_metadata(meta, web::Path::from("nope".to_string()))
            .await
            .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn get_file_metadata_propagates_a_missing_file() {
        let meta = meta_data(vec![ok(OK_EMPTY)]);
        let err = get_file_metadata(meta, path(Uuid::new_v4()))
            .await
            .expect_err("missing");
        assert_eq!(err.error_response().status(), StatusCode::NOT_FOUND);
    }

    // -- list_files --

    #[actix_web::test]
    async fn list_files_prefers_the_authenticated_user_over_the_query_string() {
        let (header_owner, query_owner) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = meta_data_spy(vec![ok(&scan_response(&[file_item(
            Uuid::new_v4(),
            header_owner,
            "a.txt",
            false,
        )]))]);

        let resp = list_files(
            user_request(Some(header_owner)),
            meta,
            query(&format!("owner_id={query_owner}")),
        )
        .await
        .expect("list");

        let body = body_json(resp);
        assert_eq!(body["total"], 1);
        assert_eq!(body["page"], 1);
        assert_eq!(body["page_size"], 50);
        let sent = String::from_utf8(
            http.actual_requests()
                .next()
                .unwrap()
                .body()
                .bytes()
                .unwrap()
                .to_vec(),
        )
        .unwrap();
        assert!(sent.contains(&header_owner.to_string()), "{sent}");
        assert!(
            !sent.contains(&query_owner.to_string()),
            "the query string cannot spoof another owner: {sent}"
        );
    }

    #[actix_web::test]
    async fn list_files_paginates_and_caps_the_page_size() {
        let owner = Uuid::new_v4();
        let items: Vec<String> = (0..3)
            .map(|i| file_item(Uuid::new_v4(), owner, &format!("f{i}.txt"), false))
            .collect();
        let meta = meta_data(vec![ok(&scan_response(&items))]);

        let body = body_json(
            list_files(
                user_request(None),
                meta,
                query("page=2&page_size=2&include_trashed=true"),
            )
            .await
            .expect("list"),
        );

        assert_eq!(body["total"], 3);
        assert_eq!(body["page"], 2);
        assert_eq!(
            body["files"].as_array().unwrap().len(),
            1,
            "the second page holds the remaining file"
        );
    }

    #[actix_web::test]
    async fn list_files_propagates_dynamo_failures() {
        let meta = meta_data(vec![dynamo_boom()]);
        let err = list_files(user_request(None), meta, query(""))
            .await
            .expect_err("500");
        assert_eq!(
            err.error_response().status(),
            StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    // -- list_shared_files --

    #[actix_web::test]
    async fn list_shared_files_requires_the_user_header() {
        let meta = meta_data(vec![]);
        let err = list_shared_files(meta, user_request(None), query(""))
            .await
            .expect_err("no header");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn list_shared_files_deduplicates_shares_and_hides_trashed_files() {
        let user = Uuid::new_v4();
        let (visible, trashed) = (Uuid::new_v4(), Uuid::new_v4());
        let owner = Uuid::new_v4();
        let shares = scan_response(&[
            share_item(Uuid::new_v4(), visible, user, "viewer"),
            share_item(Uuid::new_v4(), visible, user, "editor"),
            share_item(Uuid::new_v4(), trashed, user, "viewer"),
        ]);
        let meta = meta_data(vec![
            ok(&shares),
            ok(&item_response(&file_item(
                visible,
                owner,
                "shared.txt",
                false,
            ))),
            ok(&item_response(&file_item(trashed, owner, "gone.txt", true))),
        ]);

        let body = body_json(
            list_shared_files(meta, user_request(Some(user)), query(""))
                .await
                .expect("list"),
        );

        assert_eq!(body["total"], 1);
        assert_eq!(body["files"][0]["name"], "shared.txt");
    }

    #[actix_web::test]
    async fn list_shared_files_propagates_dynamo_failures() {
        let meta = meta_data(vec![dynamo_boom()]);
        let err = list_shared_files(meta, user_request(Some(Uuid::new_v4())), query(""))
            .await
            .expect_err("500");
        assert_eq!(
            err.error_response().status(),
            StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    // -- list_trashed --

    #[actix_web::test]
    async fn list_trashed_returns_the_owners_trash() {
        let owner = Uuid::new_v4();
        let meta = meta_data(vec![ok(&scan_response(&[file_item(
            Uuid::new_v4(),
            owner,
            "deleted.txt",
            true,
        )]))]);

        let body = body_json(
            list_trashed(user_request(Some(owner)), meta, query("page=0"))
                .await
                .expect("list"),
        );

        assert_eq!(body["total"], 1);
        assert_eq!(body["page"], 1, "page numbers start at one");
        assert_eq!(body["files"][0]["name"], "deleted.txt");
    }

    #[actix_web::test]
    async fn list_trashed_propagates_dynamo_failures() {
        let meta = meta_data(vec![dynamo_boom()]);
        let err = list_trashed(user_request(None), meta, query(""))
            .await
            .expect_err("500");
        assert_eq!(
            err.error_response().status(),
            StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    // -- delete / download --

    #[actix_web::test]
    async fn delete_file_removes_the_row_and_the_object() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            ok(OK_EMPTY),
        ]);
        let s3 = s3_data(vec![(204, String::new())]);

        let resp = delete_file(s3, meta, events_data(), path(id))
            .await
            .expect("delete");

        assert_eq!(resp.status(), StatusCode::NO_CONTENT);
    }

    #[actix_web::test]
    async fn delete_file_rejects_a_malformed_id() {
        let err = delete_file(
            s3_data(vec![]),
            meta_data(vec![]),
            events_data(),
            web::Path::from("nope".to_string()),
        )
        .await
        .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn delete_file_surfaces_an_s3_failure() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            ok(OK_EMPTY),
        ]);
        let s3 = s3_data(vec![(500, S3_ERROR.to_string())]);

        let err = delete_file(s3, meta, events_data(), path(id))
            .await
            .expect_err("s3 down");

        assert!(err.to_string().starts_with("S3 error"), "{err}");
    }

    #[actix_web::test]
    async fn download_file_returns_a_presigned_url_valid_for_an_hour() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![ok(&item_response(&file_item(
            id, owner, "a.txt", false,
        )))]);

        let body = body_json(
            download_file(s3_data(vec![]), meta, path(id))
                .await
                .expect("download"),
        );

        assert_eq!(body["expires_in_secs"], 3600);
        let url = body["url"].as_str().unwrap();
        assert!(url.contains(&format!("files/{owner}/{id}")), "{url}");
        assert!(url.contains("X-Amz-Signature="), "{url}");
    }

    #[actix_web::test]
    async fn download_file_rejects_a_malformed_id() {
        let err = download_file(
            s3_data(vec![]),
            meta_data(vec![]),
            web::Path::from("nope".to_string()),
        )
        .await
        .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    // -- move / rename --

    #[actix_web::test]
    async fn move_file_updates_the_folder_and_returns_the_file() {
        let (id, owner, folder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
        ]);

        let body = body_json(
            move_file(
                meta,
                events_data(),
                path(id),
                web::Json(MoveFileRequest {
                    folder_id: Some(folder),
                }),
            )
            .await
            .expect("move"),
        );

        assert_eq!(body["id"], id.to_string());
    }

    #[actix_web::test]
    async fn move_file_rejects_a_malformed_id() {
        let err = move_file(
            meta_data(vec![]),
            events_data(),
            web::Path::from("nope".to_string()),
            web::Json(MoveFileRequest { folder_id: None }),
        )
        .await
        .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn rename_file_rejects_a_blank_name() {
        let err = rename_file(
            meta_data(vec![]),
            events_data(),
            path(Uuid::new_v4()),
            web::Json(RenameFileRequest { name: "   ".into() }),
        )
        .await
        .expect_err("blank name");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn rename_file_stores_the_trimmed_name() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = meta_data_spy(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item(id, owner, "renamed.txt", false))),
        ]);

        let body = body_json(
            rename_file(
                meta,
                events_data(),
                path(id),
                web::Json(RenameFileRequest {
                    name: "  renamed.txt  ".into(),
                }),
            )
            .await
            .expect("rename"),
        );

        assert_eq!(body["name"], "renamed.txt");
        let sent = String::from_utf8(
            http.actual_requests()
                .next()
                .unwrap()
                .body()
                .bytes()
                .unwrap()
                .to_vec(),
        )
        .unwrap();
        assert!(sent.contains(r#"{"S":"renamed.txt"}"#), "{sent}");
    }

    #[actix_web::test]
    async fn rename_file_rejects_a_malformed_id() {
        let err = rename_file(
            meta_data(vec![]),
            events_data(),
            web::Path::from("nope".to_string()),
            web::Json(RenameFileRequest { name: "a".into() }),
        )
        .await
        .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    // -- versions / trash / restore --

    #[actix_web::test]
    async fn list_versions_returns_the_stored_versions() {
        let (id, user) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![ok(&scan_response(&[
            version_item(id, user, 2),
            version_item(id, user, 1),
        ]))]);

        let body = body_json(list_versions(meta, path(id)).await.expect("versions"));

        assert_eq!(body["versions"].as_array().unwrap().len(), 2);
        assert_eq!(body["versions"][0]["version"], 2);
    }

    #[actix_web::test]
    async fn list_versions_rejects_a_malformed_id() {
        let err = list_versions(meta_data(vec![]), web::Path::from("nope".to_string()))
            .await
            .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn trash_file_returns_the_trashed_file() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item(id, owner, "a.txt", true))),
        ]);

        let body = body_json(
            trash_file(meta, events_data(), path(id))
                .await
                .expect("trash"),
        );

        assert_eq!(body["is_trashed"], true);
    }

    #[actix_web::test]
    async fn trash_file_rejects_a_malformed_id() {
        let err = trash_file(
            meta_data(vec![]),
            events_data(),
            web::Path::from("nope".to_string()),
        )
        .await
        .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn restore_file_returns_the_restored_file() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
        ]);

        let body = body_json(
            restore_file(meta, events_data(), path(id))
                .await
                .expect("restore"),
        );

        assert_eq!(body["is_trashed"], false);
    }

    #[actix_web::test]
    async fn restore_file_rejects_a_malformed_id() {
        let err = restore_file(
            meta_data(vec![]),
            events_data(),
            web::Path::from("nope".to_string()),
        )
        .await
        .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    // -- sharing --

    fn share_request(user: Uuid, permission: SharePermission) -> web::Json<ShareFileRequest> {
        web::Json(ShareFileRequest {
            shared_with: user,
            permission,
            shared_by: Uuid::new_v4(),
        })
    }

    #[actix_web::test]
    async fn share_file_creates_a_new_share() {
        let (id, owner, user) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            ok(&scan_response(&[])),
            ok(OK_EMPTY),
        ]);

        let resp = share_file(
            meta,
            events_data(),
            path(id),
            share_request(user, SharePermission::Viewer),
        )
        .await
        .expect("share");

        assert_eq!(resp.status(), StatusCode::CREATED);
        let body = body_json(resp);
        assert_eq!(body["share"]["shared_with"], user.to_string());
        assert_eq!(body["share"]["permission"], "viewer");
    }

    #[actix_web::test]
    async fn share_file_returns_the_existing_share_unchanged() {
        let (id, owner, user, share_id) = (
            Uuid::new_v4(),
            Uuid::new_v4(),
            Uuid::new_v4(),
            Uuid::new_v4(),
        );
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            ok(&scan_response(&[share_item(share_id, id, user, "viewer")])),
        ]);

        let resp = share_file(
            meta,
            events_data(),
            path(id),
            share_request(user, SharePermission::Viewer),
        )
        .await
        .expect("share");

        assert_eq!(resp.status(), StatusCode::OK);
        assert_eq!(body_json(resp)["share"]["id"], share_id.to_string());
    }

    #[actix_web::test]
    async fn share_file_upgrades_the_permission_of_an_existing_share() {
        let (id, owner, user, share_id) = (
            Uuid::new_v4(),
            Uuid::new_v4(),
            Uuid::new_v4(),
            Uuid::new_v4(),
        );
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            ok(&scan_response(&[share_item(share_id, id, user, "viewer")])),
            ok(OK_EMPTY),
        ]);

        let resp = share_file(
            meta,
            events_data(),
            path(id),
            share_request(user, SharePermission::Editor),
        )
        .await
        .expect("share");

        assert_eq!(resp.status(), StatusCode::OK);
        let body = body_json(resp);
        assert_eq!(body["share"]["id"], share_id.to_string());
        assert_eq!(body["share"]["permission"], "editor");
    }

    #[actix_web::test]
    async fn share_file_requires_the_file_to_exist() {
        let meta = meta_data(vec![ok(OK_EMPTY)]);
        let err = share_file(
            meta,
            events_data(),
            path(Uuid::new_v4()),
            share_request(Uuid::new_v4(), SharePermission::Viewer),
        )
        .await
        .expect_err("missing file");
        assert_eq!(err.error_response().status(), StatusCode::NOT_FOUND);
    }

    #[actix_web::test]
    async fn share_file_rejects_a_malformed_id() {
        let err = share_file(
            meta_data(vec![]),
            events_data(),
            web::Path::from("nope".to_string()),
            share_request(Uuid::new_v4(), SharePermission::Viewer),
        )
        .await
        .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn remove_share_deletes_the_matching_share() {
        let (id, owner, user) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            ok(&scan_response(&[share_item(
                Uuid::new_v4(),
                id,
                user,
                "viewer",
            )])),
            ok(OK_EMPTY),
        ]);

        let resp = remove_share(meta, web::Path::from((id.to_string(), user.to_string())))
            .await
            .expect("remove");

        assert_eq!(resp.status(), StatusCode::NO_CONTENT);
    }

    #[actix_web::test]
    async fn remove_share_reports_a_missing_share() {
        let (id, owner, user) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(&item_response(&file_item(id, owner, "a.txt", false))),
            ok(&scan_response(&[])),
        ]);

        let err = remove_share(meta, web::Path::from((id.to_string(), user.to_string())))
            .await
            .expect_err("no share");

        assert_eq!(err.error_response().status(), StatusCode::NOT_FOUND);
    }

    #[actix_web::test]
    async fn remove_share_rejects_malformed_ids() {
        let bad_file = remove_share(
            meta_data(vec![]),
            web::Path::from(("nope".to_string(), Uuid::new_v4().to_string())),
        )
        .await
        .expect_err("bad file id");
        assert_eq!(bad_file.error_response().status(), StatusCode::BAD_REQUEST);

        let bad_user = remove_share(
            meta_data(vec![]),
            web::Path::from((Uuid::new_v4().to_string(), "nope".to_string())),
        )
        .await
        .expect_err("bad user id");
        assert_eq!(bad_user.error_response().status(), StatusCode::BAD_REQUEST);
    }

    // -- folders --

    #[actix_web::test]
    async fn list_folders_returns_the_owners_folders() {
        let owner = Uuid::new_v4();
        let meta = meta_data(vec![ok(&scan_response(&[folder_item(
            Uuid::new_v4(),
            owner,
            "Finance",
        )]))]);

        let body = body_json(
            list_folders(user_request(Some(owner)), meta, query(""))
                .await
                .expect("list"),
        );

        assert_eq!(body["folders"][0]["name"], "Finance");
    }

    #[actix_web::test]
    async fn list_folders_propagates_dynamo_failures() {
        let err = list_folders(
            user_request(None),
            meta_data(vec![dynamo_boom()]),
            query(""),
        )
        .await
        .expect_err("500");
        assert_eq!(
            err.error_response().status(),
            StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    #[actix_web::test]
    async fn create_folder_persists_and_echoes_the_new_folder() {
        let owner = Uuid::new_v4();
        let parent = Uuid::new_v4();
        let meta = meta_data(vec![ok(OK_EMPTY)]);

        let resp = create_folder(
            meta,
            web::Json(CreateFolderRequest {
                name: "Reports".into(),
                parent_id: Some(parent),
                owner_id: owner,
            }),
        )
        .await
        .expect("create");

        assert_eq!(resp.status(), StatusCode::CREATED);
        let body = body_json(resp);
        assert_eq!(body["name"], "Reports");
        assert_eq!(body["parent_id"], parent.to_string());
        assert_eq!(body["owner_id"], owner.to_string());
    }

    #[actix_web::test]
    async fn create_folder_propagates_dynamo_failures() {
        let err = create_folder(
            meta_data(vec![dynamo_boom()]),
            web::Json(CreateFolderRequest {
                name: "Reports".into(),
                parent_id: None,
                owner_id: Uuid::new_v4(),
            }),
        )
        .await
        .expect_err("500");
        assert_eq!(
            err.error_response().status(),
            StatusCode::INTERNAL_SERVER_ERROR
        );
    }

    #[actix_web::test]
    async fn get_folder_returns_the_folder() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![ok(&item_response(&folder_item(id, owner, "Finance")))]);

        let body = body_json(get_folder(meta, path(id)).await.expect("folder"));

        assert_eq!(body["id"], id.to_string());
        assert_eq!(body["name"], "Finance");
    }

    #[actix_web::test]
    async fn get_folder_rejects_a_malformed_id() {
        let err = get_folder(meta_data(vec![]), web::Path::from("nope".to_string()))
            .await
            .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn update_folder_returns_the_updated_folder() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let meta = meta_data(vec![
            ok(OK_EMPTY),
            ok(&item_response(&folder_item(id, owner, "Renamed"))),
        ]);

        let body = body_json(
            update_folder(
                meta,
                path(id),
                web::Json(UpdateFolderRequest {
                    name: Some("Renamed".into()),
                    parent_id: None,
                }),
            )
            .await
            .expect("update"),
        );

        assert_eq!(body["name"], "Renamed");
    }

    #[actix_web::test]
    async fn update_folder_rejects_a_malformed_id() {
        let err = update_folder(
            meta_data(vec![]),
            web::Path::from("nope".to_string()),
            web::Json(UpdateFolderRequest {
                name: None,
                parent_id: None,
            }),
        )
        .await
        .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn delete_folder_returns_no_content() {
        let meta = meta_data(vec![ok(OK_EMPTY)]);
        let resp = delete_folder(meta, path(Uuid::new_v4()))
            .await
            .expect("delete");
        assert_eq!(resp.status(), StatusCode::NO_CONTENT);
    }

    #[actix_web::test]
    async fn delete_folder_rejects_a_malformed_id() {
        let err = delete_folder(meta_data(vec![]), web::Path::from("nope".to_string()))
            .await
            .expect_err("bad id");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    // -- activity --

    /// An item carrying both file and share attributes, so the two concurrent
    /// scans behind `list_activity` can be answered with the same payload.
    fn file_and_share_item(id: Uuid, owner: Uuid, name: &str) -> String {
        format!(
            r#"{{"id":{{"S":"{id}"}},"name":{{"S":"{name}"}},"mime_type":{{"S":"text/plain"}},"size_bytes":{{"N":"10"}},"s3_key":{{"S":"files/{id}"}},"owner_id":{{"S":"{owner}"}},"version":{{"N":"1"}},"is_trashed":{{"BOOL":false}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}},"updated_at":{{"S":"1970-01-01T00:00:00+00:00"}},"file_id":{{"S":"{id}"}},"shared_with":{{"S":"{owner}"}},"shared_by":{{"S":"{owner}"}},"permission":{{"S":"viewer"}}}}"#
        )
    }

    #[actix_web::test]
    async fn list_activity_requires_the_user_header() {
        let err = list_activity(user_request(None), meta_data(vec![]), query(""))
            .await
            .expect_err("no header");
        assert_eq!(err.error_response().status(), StatusCode::BAD_REQUEST);
    }

    #[actix_web::test]
    async fn list_activity_combines_uploads_and_shares() {
        let (owner, file_id) = (Uuid::new_v4(), Uuid::new_v4());
        let payload = scan_response(&[file_and_share_item(file_id, owner, "report.pdf")]);
        let meta = meta_data(vec![ok(&payload), ok(&payload)]);

        let body = body_json(
            list_activity(user_request(Some(owner)), meta, query(""))
                .await
                .expect("activity"),
        );

        let items = body["items"].as_array().unwrap();
        assert_eq!(items.len(), 2);
        let kinds: Vec<&str> = items.iter().map(|i| i["type"].as_str().unwrap()).collect();
        assert!(kinds.contains(&"upload"), "{kinds:?}");
        assert!(kinds.contains(&"share"), "{kinds:?}");
        for item in items {
            assert_eq!(item["resource_name"], "report.pdf");
            assert_eq!(item["actor_name"], "You");
            assert_eq!(item["created_at"], epoch_rfc3339());
        }
    }

    #[actix_web::test]
    async fn list_activity_truncates_to_the_requested_limit() {
        let (owner, file_id) = (Uuid::new_v4(), Uuid::new_v4());
        let payload = scan_response(&[file_and_share_item(file_id, owner, "report.pdf")]);
        let meta = meta_data(vec![ok(&payload), ok(&payload)]);

        let body = body_json(
            list_activity(user_request(Some(owner)), meta, query("limit=1"))
                .await
                .expect("activity"),
        );

        assert_eq!(body["items"].as_array().unwrap().len(), 1);
    }

    #[actix_web::test]
    async fn list_activity_is_empty_when_both_lookups_fail() {
        let owner = Uuid::new_v4();
        let meta = meta_data(vec![dynamo_boom(), dynamo_boom()]);

        let body = body_json(
            list_activity(user_request(Some(owner)), meta, query(""))
                .await
                .expect("activity still renders"),
        );

        assert!(body["items"].as_array().unwrap().is_empty());
    }

    // -- config plumbing used by upload --

    fn app_config(max_upload_bytes: u64, upload_always_fail: bool) -> web::Data<AppConfig> {
        web::Data::new(AppConfig {
            server: ServerConfig {
                port: 8082,
                max_upload_bytes,
                upload_always_fail,
            },
            aws: AwsConfig {
                region: "us-east-1".into(),
                endpoint_url: None,
                s3_bucket: "test-bucket".into(),
                dynamodb_table: "files".into(),
                dynamodb_folders_table: "folders".into(),
                dynamodb_versions_table: "versions".into(),
                dynamodb_shares_table: "shares".into(),
            },
            sns: SnsConfig { topic_arn: None },
        })
    }

    /// Minimal in-process Redis stand-in: answers `EXISTS` with a fixed
    /// integer, so the chaos-flag lookup is deterministic and offline.
    async fn fake_redis(exists: i64) -> web::Data<redis::aio::ConnectionManager> {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            while let Ok((mut socket, _)) = listener.accept().await {
                tokio::spawn(async move {
                    use tokio::io::{AsyncReadExt, AsyncWriteExt};
                    let mut buf = [0u8; 4096];
                    loop {
                        let n = match socket.read(&mut buf).await {
                            Ok(0) | Err(_) => break,
                            Ok(n) => n,
                        };
                        // Answer every pipelined command in the chunk: redis-rs
                        // sends CLIENT SETINFO alongside the first command.
                        let text = String::from_utf8_lossy(&buf[..n]).to_string();
                        let mut lines = text.split("\r\n").filter(|l| !l.is_empty());
                        let mut reply = String::new();
                        while let Some(line) = lines.next() {
                            let Some(argc) =
                                line.strip_prefix('*').and_then(|c| c.parse::<usize>().ok())
                            else {
                                continue;
                            };
                            let mut args = Vec::new();
                            for _ in 0..argc {
                                lines.next();
                                if let Some(arg) = lines.next() {
                                    args.push(arg.to_uppercase());
                                }
                            }
                            match args.first().map(String::as_str) {
                                Some("EXISTS") => reply.push_str(&format!(":{exists}\r\n")),
                                Some("PING") => reply.push_str("+PONG\r\n"),
                                _ => reply.push_str("+OK\r\n"),
                            }
                        }
                        if socket.write_all(reply.as_bytes()).await.is_err() {
                            break;
                        }
                    }
                });
            }
        });

        let client = redis::Client::open(format!("redis://{addr}")).unwrap();
        web::Data::new(
            redis::aio::ConnectionManager::new(client)
                .await
                .expect("the stub accepts connections"),
        )
    }

    #[actix_web::test]
    async fn the_redis_stub_answers_the_chaos_flag_lookup() {
        let cm = fake_redis(1).await;
        assert!(chaos_active(&mut cm.get_ref().clone(), "flag").await);

        let cm = fake_redis(0).await;
        assert!(!chaos_active(&mut cm.get_ref().clone(), "flag").await);
    }

    const BOUNDARY: &str = "test-boundary";

    fn multipart_body(parts: &[(&str, Option<&str>, &str)]) -> Vec<u8> {
        let mut body = String::new();
        for (name, filename, value) in parts {
            body.push_str(&format!("--{BOUNDARY}\r\n"));
            match filename {
                Some(f) => body.push_str(&format!(
                    "Content-Disposition: form-data; name=\"{name}\"; filename=\"{f}\"\r\nContent-Type: text/plain\r\n\r\n"
                )),
                None => body.push_str(&format!(
                    "Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                )),
            }
            body.push_str(value);
            body.push_str("\r\n");
        }
        body.push_str(&format!("--{BOUNDARY}--\r\n"));
        body.into_bytes()
    }

    fn upload_request(
        user_id: Option<Uuid>,
        parts: &[(&str, Option<&str>, &str)],
    ) -> (HttpRequest, Multipart) {
        let mut builder = TestRequest::default()
            .insert_header((
                "content-type",
                format!("multipart/form-data; boundary={BOUNDARY}"),
            ))
            .set_payload(multipart_body(parts));
        if let Some(id) = user_id {
            builder = builder.insert_header(("X-User-ID", id.to_string()));
        }
        let (req, payload) = builder.to_http_parts();
        let multipart = Multipart::new(req.headers(), payload);
        (req, multipart)
    }

    async fn upload(
        user_id: Option<Uuid>,
        parts: &[(&str, Option<&str>, &str)],
        s3: web::Data<S3Client>,
        meta: web::Data<MetadataClient>,
        config: web::Data<AppConfig>,
        redis_reply: i64,
    ) -> Result<HttpResponse, ServiceError> {
        let (req, multipart) = upload_request(user_id, parts);
        upload_file(
            req,
            s3,
            meta,
            events_data(),
            config,
            fake_redis(redis_reply).await,
            multipart,
        )
        .await
    }

    #[actix_web::test]
    async fn upload_file_stores_the_object_metadata_and_first_version() {
        let owner = Uuid::new_v4();
        let (s3_client, s3_http) =
            crate::models::test_support::s3_client(vec![(200, String::new())]);
        let s3 = web::Data::new(S3Client {
            client: s3_client,
            bucket: "test-bucket".into(),
        });
        let (meta, dynamo_http) = meta_data_spy(vec![ok(OK_EMPTY), ok(OK_EMPTY)]);

        let resp = upload(
            None,
            &[
                ("file", Some("notes.txt"), "hello world"),
                ("owner_id", None, &owner.to_string()),
            ],
            s3,
            meta,
            app_config(1024, false),
            0,
        )
        .await
        .expect("upload succeeds");

        assert_eq!(resp.status(), StatusCode::CREATED);
        let body = body_json(resp);
        assert_eq!(body["file"]["name"], "notes.txt");
        assert_eq!(body["file"]["size_bytes"], 11);
        assert_eq!(body["file"]["version"], 1);
        assert_eq!(body["file"]["owner_id"], owner.to_string());

        let put = s3_http.actual_requests().next().expect("one PUT");
        assert_eq!(put.method(), "PUT");
        assert!(put.uri().contains("test-bucket"), "{}", put.uri());
        assert_eq!(
            dynamo_http.actual_requests().count(),
            2,
            "the file row and its first version are both written"
        );
    }

    #[actix_web::test]
    async fn upload_file_prefers_the_authenticated_owner_and_accepts_a_folder() {
        let (header_owner, body_owner, folder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());

        let body = body_json(
            upload(
                Some(header_owner),
                &[
                    ("file", Some("notes.txt"), "hi"),
                    ("owner_id", None, &body_owner.to_string()),
                    ("folder_id", None, &folder.to_string()),
                    ("unexpected", None, "ignored"),
                ],
                s3_data(vec![(200, String::new())]),
                meta_data(vec![ok(OK_EMPTY), ok(OK_EMPTY)]),
                app_config(1024, false),
                0,
            )
            .await
            .expect("upload succeeds"),
        );

        assert_eq!(body["file"]["owner_id"], header_owner.to_string());
        assert_eq!(body["file"]["folder_id"], folder.to_string());
    }

    #[actix_web::test]
    async fn upload_file_requires_an_owner() {
        let err = upload(
            None,
            &[("file", Some("notes.txt"), "hi")],
            s3_data(vec![]),
            meta_data(vec![]),
            app_config(1024, false),
            0,
        )
        .await
        .expect_err("no owner");

        assert_eq!(err.to_string(), "Bad request: owner_id is required");
    }

    #[actix_web::test]
    async fn upload_file_requires_a_file_part() {
        let owner = Uuid::new_v4();
        let err = upload(
            Some(owner),
            &[("owner_id", None, &owner.to_string())],
            s3_data(vec![]),
            meta_data(vec![]),
            app_config(1024, false),
            0,
        )
        .await
        .expect_err("no file");

        assert_eq!(err.to_string(), "Bad request: file field is required");
    }

    #[actix_web::test]
    async fn upload_file_rejects_a_payload_over_the_configured_limit() {
        let err = upload(
            Some(Uuid::new_v4()),
            &[("file", Some("big.txt"), "0123456789")],
            s3_data(vec![]),
            meta_data(vec![]),
            app_config(4, false),
            0,
        )
        .await
        .expect_err("too large");

        assert_eq!(err.error_response().status(), StatusCode::PAYLOAD_TOO_LARGE);
    }

    #[actix_web::test]
    async fn upload_file_rejects_malformed_identifiers() {
        let bad_owner = upload(
            None,
            &[
                ("file", Some("a.txt"), "hi"),
                ("owner_id", None, "not-a-uuid"),
            ],
            s3_data(vec![]),
            meta_data(vec![]),
            app_config(1024, false),
            0,
        )
        .await
        .expect_err("bad owner id");
        assert!(
            bad_owner
                .to_string()
                .starts_with("Bad request: invalid owner_id"),
            "{bad_owner}"
        );

        let bad_folder = upload(
            Some(Uuid::new_v4()),
            &[
                ("file", Some("a.txt"), "hi"),
                ("folder_id", None, "not-a-uuid"),
            ],
            s3_data(vec![]),
            meta_data(vec![]),
            app_config(1024, false),
            0,
        )
        .await
        .expect_err("bad folder id");
        assert!(
            bad_folder
                .to_string()
                .starts_with("Bad request: invalid folder_id"),
            "{bad_folder}"
        );
    }

    #[actix_web::test]
    async fn upload_file_treats_a_blank_folder_id_as_the_root() {
        let body = body_json(
            upload(
                Some(Uuid::new_v4()),
                &[("file", Some("a.txt"), "hi"), ("folder_id", None, "  ")],
                s3_data(vec![(200, String::new())]),
                meta_data(vec![ok(OK_EMPTY), ok(OK_EMPTY)]),
                app_config(1024, false),
                0,
            )
            .await
            .expect("upload succeeds"),
        );

        assert!(body["file"]["folder_id"].is_null());
    }

    #[actix_web::test]
    async fn upload_file_targets_the_chaos_bucket_when_the_kill_switch_is_on() {
        let (s3_client, s3_http) =
            crate::models::test_support::s3_client(vec![(200, String::new())]);
        let s3 = web::Data::new(S3Client {
            client: s3_client,
            bucket: "test-bucket".into(),
        });

        upload(
            Some(Uuid::new_v4()),
            &[("file", Some("a.txt"), "hi")],
            s3,
            meta_data(vec![ok(OK_EMPTY), ok(OK_EMPTY)]),
            app_config(1024, true),
            0,
        )
        .await
        .expect("upload still reaches S3");

        let put = s3_http.actual_requests().next().unwrap();
        assert!(
            put.uri().contains("otterworks-files-chaos-nonexistent"),
            "{}",
            put.uri()
        );
    }

    #[actix_web::test]
    async fn upload_file_targets_the_chaos_bucket_when_the_redis_flag_is_set() {
        let (s3_client, s3_http) =
            crate::models::test_support::s3_client(vec![(200, String::new())]);
        let s3 = web::Data::new(S3Client {
            client: s3_client,
            bucket: "test-bucket".into(),
        });

        upload(
            Some(Uuid::new_v4()),
            &[("file", Some("a.txt"), "hi")],
            s3,
            meta_data(vec![ok(OK_EMPTY), ok(OK_EMPTY)]),
            app_config(1024, false),
            1,
        )
        .await
        .expect("upload still reaches S3");

        let put = s3_http.actual_requests().next().unwrap();
        assert!(
            put.uri().contains("otterworks-files-chaos-nonexistent"),
            "{}",
            put.uri()
        );
    }

    #[actix_web::test]
    async fn upload_file_surfaces_an_s3_failure() {
        let err = upload(
            Some(Uuid::new_v4()),
            &[("file", Some("a.txt"), "hi")],
            s3_data(vec![(500, S3_ERROR.to_string())]),
            meta_data(vec![]),
            app_config(1024, false),
            0,
        )
        .await
        .expect_err("s3 down");

        assert!(err.to_string().starts_with("S3 error"), "{err}");
    }

    #[actix_web::test]
    async fn upload_file_surfaces_a_metadata_failure() {
        let err = upload(
            Some(Uuid::new_v4()),
            &[("file", Some("a.txt"), "hi")],
            s3_data(vec![(200, String::new())]),
            meta_data(vec![dynamo_boom()]),
            app_config(1024, false),
            0,
        )
        .await
        .expect_err("dynamo down");

        assert!(err.to_string().starts_with("DynamoDB error"), "{err}");
    }
}
