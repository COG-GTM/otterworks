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

use crate::alerts;
use crate::config::AppConfig;
use crate::errors::ServiceError;
use crate::events::EventPublisher;
use crate::metadata::MetadataClient;
use crate::middleware;
use crate::models::{
    ActivityItem, ActivityQuery, ActivityResponse, CreateFolderRequest, DownloadResponse,
    FileDetailResponse, FileMetadata, FileShare, FileTypeStats, FileVersion, Folder,
    FolderStatsResponse, HealthResponse, ListFilesQuery, ListFilesResponse, ListFoldersQuery,
    ListFoldersResponse, ListVersionsResponse, MoveFileRequest, RenameFileRequest,
    ShareFileRequest, ShareFileResponse, UpdateFolderRequest, UploadResponse,
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

    // Uploader's email, injected by api-gateway from the JWT; carried on
    // upload-failure alerts so admin-service can attribute the incident.
    let reporter_email = req
        .headers()
        .get("X-User-Email")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(String::from);

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
    if let Err(err) = chaos_s3
        .upload_object(&s3_key, file_bytes.freeze(), &content_type)
        .await
    {
        alerts::notify_upload_failure(
            &config.alerts,
            &file_name,
            &err.to_string(),
            reporter_email.as_deref(),
        );
        return Err(err);
    }

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
    s3: web::Data<S3Client>,
    config: web::Data<AppConfig>,
    query: web::Query<ListFilesQuery>,
) -> Result<HttpResponse, ServiceError> {
    let include_trashed = query.include_trashed.unwrap_or(false);
    let owner_id = resolve_owner_id(&req, query.owner_id);
    let mut files = meta
        .list_files(query.folder_id, owner_id, include_trashed)
        .await?;
    // Seeding is only considered when the listing comes back empty, so the
    // common non-empty case costs no extra metadata reads.
    if files.is_empty() && config.server.seed_demo_docs {
        if let Some(owner) = owner_id {
            if crate::seed::maybe_seed_demo_docs(&meta, &s3, owner).await {
                files = meta
                    .list_files(query.folder_id, owner_id, include_trashed)
                    .await?;
            }
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
    req: HttpRequest,
    config: web::Data<AppConfig>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
    body: web::Json<ShareFileRequest>,
) -> Result<HttpResponse, ServiceError> {
    // Sharer's email, injected by api-gateway from the JWT; carried on
    // share-notification alerts so admin-service can attribute the incident.
    let reporter_email = req
        .headers()
        .get("X-User-Email")
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(String::from);

    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    // Ensure file exists
    let file = meta.get_file(&file_id).await?;

    // Recipient is either a resolved user id, or an email the client could
    // not resolve to an OtterWorks account. Unresolved emails are rejected
    // unless the share-event failure switch is on, in which case the
    // notification publish is still attempted (and fails) without persisting
    // a share to a nonexistent user — so the failure fires for any email.
    let (shared_with, recipient_known) = match body.shared_with {
        Some(id) => (id, true),
        None => {
            let email = body
                .shared_with_email
                .as_deref()
                .map(str::trim)
                .filter(|s| !s.is_empty())
                .ok_or_else(|| {
                    ServiceError::BadRequest("shared_with or shared_with_email is required".into())
                })?;
            if !events.share_publish_forced() {
                return Err(ServiceError::BadRequest(format!(
                    "no OtterWorks user found for {email}"
                )));
            }
            (
                Uuid::new_v5(&Uuid::NAMESPACE_DNS, email.to_lowercase().as_bytes()),
                false,
            )
        }
    };

    // Check if share already exists for this file + user
    let (share, created, permission_update) = if !recipient_known {
        let share = FileShare {
            id: Uuid::new_v4(),
            file_id,
            shared_with,
            permission: body.permission.clone(),
            shared_by: body.shared_by,
            created_at: Utc::now(),
        };
        (share, false, false)
    } else if let Some(existing) = meta.find_existing_share(&file_id, &shared_with).await? {
        // Update permission if different, otherwise keep the existing record
        if existing.permission != body.permission {
            let updated = FileShare {
                id: existing.id,
                file_id,
                shared_with,
                permission: body.permission.clone(),
                shared_by: body.shared_by,
                created_at: existing.created_at,
            };
            meta.put_share(&updated).await?;
            tracing::info!(file_id = %file_id, shared_with = %shared_with, "File share updated");
            (updated, false, true)
        } else {
            tracing::info!(file_id = %file_id, shared_with = %shared_with, "File already shared");
            (existing, false, false)
        }
    } else {
        let share = FileShare {
            id: Uuid::new_v4(),
            file_id,
            shared_with,
            permission: body.permission.clone(),
            shared_by: body.shared_by,
            created_at: Utc::now(),
        };
        meta.put_share(&share).await?;
        (share, true, false)
    };

    // The notification event is published for new shares only, so re-shares
    // and permission updates don't send duplicate notifications. When the
    // share-event failure switch is on, every share click (new share or
    // re-share of the same recipient) attempts the publish so a failed
    // attempt can be retried by sharing again; permission updates are not
    // share clicks and are left alone.
    if created || (events.share_publish_forced() && !permission_update) {
        if let Err(err) = events
            .file_shared(&file_id, &file.owner_id, &shared_with)
            .await
        {
            tracing::error!(file_id = %file_id, error = %err, "Failed to publish file_shared event");
            alerts::notify_share_notification_failure(
                &config.alerts,
                &file.name,
                &err.to_string(),
                reporter_email.as_deref(),
                !events.share_publish_forced(),
                recipient_known,
            );
            // Only surface the failure to the caller when the demo switch is
            // on; otherwise event publishing stays fire-and-forget like the
            // other handlers, since the share is already persisted.
            if events.share_publish_forced() {
                return Err(err);
            }
        }
    }

    tracing::info!(file_id = %file_id, shared_with = %shared_with, "File shared");
    if created {
        Ok(HttpResponse::Created().json(ShareFileResponse { share }))
    } else {
        Ok(HttpResponse::Ok().json(ShareFileResponse { share }))
    }
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

/// File count and total size by file type for a folder and all of its
/// subfolders. Folders the caller does not own are reported as not found so
/// their existence is not leaked.
pub async fn folder_stats(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let folder_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid folder id: {e}")))?;
    let user_id = req
        .headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok())
        .ok_or_else(|| ServiceError::BadRequest("missing owner context".into()))?;

    let folder = meta.get_folder(&folder_id).await?;
    ensure_folder_access(&folder, &user_id)?;

    let (folders, files) = futures_util::future::try_join(
        meta.list_folders_by_owner(&user_id),
        meta.list_files(None, Some(user_id), false),
    )
    .await?;

    Ok(HttpResponse::Ok().json(compute_folder_stats(folder_id, &folders, &files)))
}

fn ensure_folder_access(folder: &Folder, user_id: &Uuid) -> Result<(), ServiceError> {
    if folder.owner_id == *user_id {
        Ok(())
    } else {
        Err(ServiceError::FolderNotFound(folder.id.to_string()))
    }
}

fn normalize_file_type(mime_type: &str) -> String {
    let essence = mime_type.split(';').next().unwrap_or("").trim();
    if essence.is_empty() {
        "application/octet-stream".into()
    } else {
        essence.to_ascii_lowercase()
    }
}

fn compute_folder_stats(
    root_id: Uuid,
    folders: &[Folder],
    files: &[FileMetadata],
) -> FolderStatsResponse {
    use std::collections::{BTreeMap, HashMap, HashSet};

    let mut children: HashMap<Uuid, Vec<Uuid>> = HashMap::new();
    for f in folders {
        if let Some(parent) = f.parent_id {
            children.entry(parent).or_default().push(f.id);
        }
    }

    // `update_folder` does not reject parent cycles, so track visited ids.
    let mut subtree: HashSet<Uuid> = HashSet::from([root_id]);
    let mut stack = vec![root_id];
    while let Some(id) = stack.pop() {
        for child in children.get(&id).into_iter().flatten() {
            if subtree.insert(*child) {
                stack.push(*child);
            }
        }
    }

    let mut by_type: BTreeMap<String, (u64, u64)> = BTreeMap::new();
    for file in files {
        if file.is_trashed || !file.folder_id.is_some_and(|id| subtree.contains(&id)) {
            continue;
        }
        let entry = by_type
            .entry(normalize_file_type(&file.mime_type))
            .or_default();
        entry.0 += 1;
        entry.1 += file.size_bytes;
    }

    let mut by_type: Vec<FileTypeStats> = by_type
        .into_iter()
        .map(
            |(file_type, (file_count, total_size_bytes))| FileTypeStats {
                file_type,
                file_count,
                total_size_bytes,
            },
        )
        .collect();
    by_type.sort_by_key(|t| std::cmp::Reverse(t.total_size_bytes));

    FolderStatsResponse {
        folder_id: root_id,
        folder_count: (subtree.len() - 1) as u64,
        file_count: by_type.iter().map(|t| t.file_count).sum(),
        total_size_bytes: by_type.iter().map(|t| t.total_size_bytes).sum(),
        by_type,
    }
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

    fn folder(owner: Uuid, parent: Option<Uuid>) -> Folder {
        let now = Utc::now();
        Folder {
            id: Uuid::new_v4(),
            name: "folder".into(),
            parent_id: parent,
            owner_id: owner,
            created_at: now,
            updated_at: now,
        }
    }

    fn file(owner: Uuid, folder: Option<Uuid>, mime_type: &str, size_bytes: u64) -> FileMetadata {
        let now = Utc::now();
        let id = Uuid::new_v4();
        FileMetadata {
            id,
            name: "file".into(),
            mime_type: mime_type.into(),
            size_bytes,
            s3_key: format!("files/{owner}/{id}"),
            folder_id: folder,
            owner_id: owner,
            version: 1,
            is_trashed: false,
            created_at: now,
            updated_at: now,
        }
    }

    #[test]
    fn test_folder_stats_includes_nested_subfolders() {
        let owner = Uuid::new_v4();
        let root = folder(owner, None);
        let child = folder(owner, Some(root.id));
        let grandchild = folder(owner, Some(child.id));
        let sibling = folder(owner, None);
        let mut trashed = file(owner, Some(child.id), "application/pdf", 9_000);
        trashed.is_trashed = true;
        let files = vec![
            file(owner, Some(root.id), "application/pdf", 100),
            file(owner, Some(child.id), "application/pdf", 200),
            file(owner, Some(grandchild.id), "text/csv; charset=utf-8", 50),
            file(owner, Some(grandchild.id), "TEXT/CSV", 25),
            file(owner, Some(sibling.id), "image/png", 1_000),
            file(owner, None, "image/png", 1_000),
            trashed,
        ];
        let folders = vec![root.clone(), child, grandchild, sibling];

        let stats = compute_folder_stats(root.id, &folders, &files);

        assert_eq!(stats.folder_id, root.id);
        assert_eq!(stats.folder_count, 2);
        assert_eq!(stats.file_count, 4);
        assert_eq!(stats.total_size_bytes, 375);
        assert_eq!(
            stats.by_type,
            vec![
                FileTypeStats {
                    file_type: "application/pdf".into(),
                    file_count: 2,
                    total_size_bytes: 300,
                },
                FileTypeStats {
                    file_type: "text/csv".into(),
                    file_count: 2,
                    total_size_bytes: 75,
                },
            ]
        );
    }

    #[test]
    fn test_folder_stats_subfolder_scope_excludes_parent() {
        let owner = Uuid::new_v4();
        let root = folder(owner, None);
        let child = folder(owner, Some(root.id));
        let files = vec![
            file(owner, Some(root.id), "application/pdf", 100),
            file(owner, Some(child.id), "image/png", 10),
        ];
        let folders = vec![root, child.clone()];

        let stats = compute_folder_stats(child.id, &folders, &files);

        assert_eq!(stats.folder_count, 0);
        assert_eq!(stats.file_count, 1);
        assert_eq!(stats.total_size_bytes, 10);
        assert_eq!(stats.by_type[0].file_type, "image/png");
    }

    #[test]
    fn test_folder_stats_empty_folder_returns_zero_counts() {
        let owner = Uuid::new_v4();
        let root = folder(owner, None);
        let child = folder(owner, Some(root.id));
        let folders = vec![root.clone(), child];

        let stats = compute_folder_stats(root.id, &folders, &[]);

        assert_eq!(stats.folder_count, 1);
        assert_eq!(stats.file_count, 0);
        assert_eq!(stats.total_size_bytes, 0);
        assert!(stats.by_type.is_empty());
    }

    #[test]
    fn test_folder_stats_tolerates_parent_cycles() {
        let owner = Uuid::new_v4();
        let mut a = folder(owner, None);
        let b = folder(owner, Some(a.id));
        a.parent_id = Some(b.id);
        let files = vec![file(owner, Some(b.id), "text/plain", 5)];
        let folders = vec![a.clone(), b];

        let stats = compute_folder_stats(a.id, &folders, &files);

        assert_eq!(stats.folder_count, 1);
        assert_eq!(stats.file_count, 1);
    }

    #[test]
    fn test_folder_access_allows_owner() {
        let owner = Uuid::new_v4();
        assert!(ensure_folder_access(&folder(owner, None), &owner).is_ok());
    }

    #[test]
    fn test_folder_access_denied_is_not_found() {
        let owner = Uuid::new_v4();
        let other = Uuid::new_v4();
        let err = ensure_folder_access(&folder(owner, None), &other).unwrap_err();
        assert!(matches!(err, ServiceError::FolderNotFound(_)));
        assert_eq!(
            actix_web::ResponseError::error_response(&err).status(),
            actix_web::http::StatusCode::NOT_FOUND
        );
    }
}
