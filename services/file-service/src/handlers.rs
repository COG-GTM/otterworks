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
    FileDetailResponse, FileMetadata, FileShare, FileVersion, Folder, HealthResponse,
    ListFilesQuery, ListFilesResponse, ListFoldersQuery, ListFoldersResponse, ListVersionsResponse,
    MoveFileRequest, RenameFileRequest, ShareFileRequest, ShareFileResponse, SharePermission,
    UpdateFolderRequest, UploadResponse,
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

// -- Authorization --

/// Caller identity injected by the api-gateway from the validated JWT.
fn caller_id(req: &HttpRequest) -> Result<Uuid, ServiceError> {
    req.headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok())
        .ok_or_else(|| ServiceError::Unauthorized("missing caller identity".into()))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
enum FileAccess {
    None,
    Viewer,
    Editor,
    Owner,
}

fn file_access(file: &FileMetadata, caller: &Uuid, share: Option<&FileShare>) -> FileAccess {
    if file.owner_id == *caller {
        return FileAccess::Owner;
    }
    if file.is_trashed {
        return FileAccess::None;
    }
    match share {
        Some(s) if s.file_id == file.id && s.shared_with == *caller => match s.permission {
            SharePermission::Viewer => FileAccess::Viewer,
            SharePermission::Editor => FileAccess::Editor,
        },
        _ => FileAccess::None,
    }
}

/// Load a file and require the caller to hold at least `required` access.
/// Callers with no access get 404 so file ids cannot be probed for existence.
async fn authorize_file(
    meta: &MetadataClient,
    file_id: &Uuid,
    caller: &Uuid,
    required: FileAccess,
) -> Result<FileMetadata, ServiceError> {
    let file = meta.get_file(file_id).await?;
    let share = if file.owner_id == *caller {
        None
    } else {
        meta.find_existing_share(file_id, caller).await?
    };
    match file_access(&file, caller, share.as_ref()) {
        FileAccess::None => Err(ServiceError::FileNotFound(file_id.to_string())),
        access if access < required => Err(ServiceError::Forbidden(
            "insufficient permission for this file".into(),
        )),
        _ => Ok(file),
    }
}

/// Load a folder owned by the caller; other users' folders are reported as 404.
async fn authorize_folder(
    meta: &MetadataClient,
    folder_id: &Uuid,
    caller: &Uuid,
) -> Result<Folder, ServiceError> {
    let folder = meta.get_folder(folder_id).await?;
    if folder.owner_id != *caller {
        return Err(ServiceError::FolderNotFound(folder_id.to_string()));
    }
    Ok(folder)
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

    if let Some(fid) = &folder_id {
        authorize_folder(&meta, fid, &owner).await?;
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
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;
    let caller = caller_id(&req)?;
    let file = authorize_file(&meta, &file_id, &caller, FileAccess::Viewer).await?;
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
    req: HttpRequest,
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let caller = caller_id(&req)?;
    let file = authorize_file(&meta, &file_id, &caller, FileAccess::Owner).await?;
    meta.delete_file(&file_id).await?;
    s3.delete_object(&file.s3_key).await?;

    let _ = events.file_deleted(&file_id, &file.owner_id).await;

    tracing::info!(file_id = %file_id, "File deleted");
    Ok(HttpResponse::NoContent().finish())
}

pub async fn download_file(
    req: HttpRequest,
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let caller = caller_id(&req)?;
    let file = authorize_file(&meta, &file_id, &caller, FileAccess::Viewer).await?;
    let url = s3.presigned_download_url(&file.s3_key, 3600).await?;

    Ok(HttpResponse::Ok().json(DownloadResponse {
        url,
        expires_in_secs: 3600,
    }))
}

pub async fn move_file(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
    body: web::Json<MoveFileRequest>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let caller = caller_id(&req)?;
    authorize_file(&meta, &file_id, &caller, FileAccess::Owner).await?;
    if let Some(fid) = &body.folder_id {
        authorize_folder(&meta, fid, &caller).await?;
    }

    let file = meta.move_file(&file_id, body.folder_id).await?;

    let _ = events
        .file_moved(&file_id, &file.owner_id, body.folder_id.as_ref())
        .await;

    tracing::info!(file_id = %file_id, folder_id = ?body.folder_id, "File moved");
    Ok(HttpResponse::Ok().json(file))
}

pub async fn rename_file(
    req: HttpRequest,
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

    let caller = caller_id(&req)?;
    authorize_file(&meta, &file_id, &caller, FileAccess::Editor).await?;

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
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let caller = caller_id(&req)?;
    authorize_file(&meta, &file_id, &caller, FileAccess::Viewer).await?;

    let versions = meta.list_versions(&file_id).await?;
    Ok(HttpResponse::Ok().json(ListVersionsResponse { versions }))
}

pub async fn trash_file(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let caller = caller_id(&req)?;
    authorize_file(&meta, &file_id, &caller, FileAccess::Owner).await?;

    let file = meta.trash_file(&file_id).await?;

    let _ = events.file_trashed(&file_id, &file.owner_id).await;

    tracing::info!(file_id = %file_id, "File trashed");
    Ok(HttpResponse::Ok().json(file))
}

pub async fn restore_file(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let file_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid file id: {e}")))?;

    let caller = caller_id(&req)?;
    authorize_file(&meta, &file_id, &caller, FileAccess::Owner).await?;

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

    // Only the owner may grant access; the sharer is always the caller.
    let caller = caller_id(&req)?;
    let file = authorize_file(&meta, &file_id, &caller, FileAccess::Owner).await?;

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
            shared_by: caller,
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
                shared_by: caller,
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
            shared_by: caller,
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
    req: HttpRequest,
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

    // The owner may revoke any share; a recipient may only remove their own.
    let caller = caller_id(&req)?;
    let required = if user_id == caller {
        FileAccess::Viewer
    } else {
        FileAccess::Owner
    };
    authorize_file(&meta, &file_id, &caller, required).await?;

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
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    body: web::Json<CreateFolderRequest>,
) -> Result<HttpResponse, ServiceError> {
    let caller = caller_id(&req)?;
    if let Some(pid) = &body.parent_id {
        authorize_folder(&meta, pid, &caller).await?;
    }

    let now = Utc::now();
    let folder = Folder {
        id: Uuid::new_v4(),
        name: body.name.clone(),
        parent_id: body.parent_id,
        owner_id: caller,
        created_at: now,
        updated_at: now,
    };

    meta.put_folder(&folder).await?;
    tracing::info!(folder_id = %folder.id, name = %folder.name, "Folder created");
    Ok(HttpResponse::Created().json(folder))
}

pub async fn get_folder(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let folder_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid folder id: {e}")))?;

    let caller = caller_id(&req)?;
    let folder = authorize_folder(&meta, &folder_id, &caller).await?;
    Ok(HttpResponse::Ok().json(folder))
}

pub async fn update_folder(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
    body: web::Json<UpdateFolderRequest>,
) -> Result<HttpResponse, ServiceError> {
    let folder_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid folder id: {e}")))?;

    let caller = caller_id(&req)?;
    authorize_folder(&meta, &folder_id, &caller).await?;
    if let Some(pid) = &body.parent_id {
        if *pid == folder_id {
            return Err(ServiceError::BadRequest(
                "folder cannot be its own parent".into(),
            ));
        }
        authorize_folder(&meta, pid, &caller).await?;
    }

    let folder = meta
        .update_folder(&folder_id, body.name.clone(), body.parent_id)
        .await?;
    Ok(HttpResponse::Ok().json(folder))
}

pub async fn delete_folder(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let folder_id: Uuid = path
        .into_inner()
        .parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid folder id: {e}")))?;

    let caller = caller_id(&req)?;
    authorize_folder(&meta, &folder_id, &caller).await?;

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

    fn file_owned_by(owner: Uuid) -> FileMetadata {
        let now = Utc::now();
        FileMetadata {
            id: Uuid::new_v4(),
            name: "report.pdf".into(),
            mime_type: "application/pdf".into(),
            size_bytes: 10,
            s3_key: format!("files/{owner}/x"),
            folder_id: None,
            owner_id: owner,
            version: 1,
            is_trashed: false,
            created_at: now,
            updated_at: now,
        }
    }

    fn share_of(file: &FileMetadata, with: Uuid, permission: SharePermission) -> FileShare {
        FileShare {
            id: Uuid::new_v4(),
            file_id: file.id,
            shared_with: with,
            permission,
            shared_by: file.owner_id,
            created_at: Utc::now(),
        }
    }

    #[test]
    fn test_file_access_owner() {
        let owner = Uuid::new_v4();
        let file = file_owned_by(owner);
        assert_eq!(file_access(&file, &owner, None), FileAccess::Owner);
    }

    #[test]
    fn test_file_access_denies_non_owner_without_share() {
        let file = file_owned_by(Uuid::new_v4());
        let attacker = Uuid::new_v4();
        assert_eq!(file_access(&file, &attacker, None), FileAccess::None);
    }

    #[test]
    fn test_file_access_follows_share_permission() {
        let file = file_owned_by(Uuid::new_v4());
        let viewer = Uuid::new_v4();
        let editor = Uuid::new_v4();
        let v = share_of(&file, viewer, SharePermission::Viewer);
        let e = share_of(&file, editor, SharePermission::Editor);
        assert_eq!(file_access(&file, &viewer, Some(&v)), FileAccess::Viewer);
        assert_eq!(file_access(&file, &editor, Some(&e)), FileAccess::Editor);
        assert!(FileAccess::Viewer < FileAccess::Editor);
        assert!(FileAccess::Editor < FileAccess::Owner);
    }

    #[test]
    fn test_file_access_ignores_share_for_other_user_or_file() {
        let file = file_owned_by(Uuid::new_v4());
        let attacker = Uuid::new_v4();
        let someone_elses = share_of(&file, Uuid::new_v4(), SharePermission::Editor);
        assert_eq!(
            file_access(&file, &attacker, Some(&someone_elses)),
            FileAccess::None
        );
        let other_file = file_owned_by(file.owner_id);
        let other_share = share_of(&other_file, attacker, SharePermission::Editor);
        assert_eq!(
            file_access(&file, &attacker, Some(&other_share)),
            FileAccess::None
        );
    }

    #[test]
    fn test_file_access_hides_trashed_file_from_collaborators() {
        let mut file = file_owned_by(Uuid::new_v4());
        file.is_trashed = true;
        let viewer = Uuid::new_v4();
        let share = share_of(&file, viewer, SharePermission::Viewer);
        assert_eq!(file_access(&file, &viewer, Some(&share)), FileAccess::None);
        assert_eq!(file_access(&file, &file.owner_id, None), FileAccess::Owner);
    }

    #[test]
    fn test_caller_id_requires_valid_header() {
        let missing = actix_web::test::TestRequest::default().to_http_request();
        assert!(matches!(
            caller_id(&missing),
            Err(ServiceError::Unauthorized(_))
        ));

        let garbage = actix_web::test::TestRequest::default()
            .insert_header(("X-User-ID", "not-a-uuid"))
            .to_http_request();
        assert!(matches!(
            caller_id(&garbage),
            Err(ServiceError::Unauthorized(_))
        ));

        let id = Uuid::new_v4();
        let ok = actix_web::test::TestRequest::default()
            .insert_header(("X-User-ID", id.to_string()))
            .to_http_request();
        assert_eq!(caller_id(&ok).unwrap(), id);
    }

    #[test]
    fn test_share_request_ignores_client_supplied_shared_by() {
        let body = serde_json::json!({
            "shared_with": Uuid::new_v4(),
            "permission": "viewer",
            "shared_by": Uuid::new_v4(),
        });
        let parsed: ShareFileRequest = serde_json::from_value(body).unwrap();
        assert_eq!(parsed.permission, SharePermission::Viewer);
    }

    async fn unreachable_metadata() -> web::Data<MetadataClient> {
        let aws = crate::config::AwsConfig {
            region: "us-east-1".into(),
            endpoint_url: Some("http://127.0.0.1:1".into()),
            s3_bucket: "b".into(),
            dynamodb_table: "f".into(),
            dynamodb_folders_table: "d".into(),
            dynamodb_versions_table: "v".into(),
            dynamodb_shares_table: "s".into(),
        };
        web::Data::new(MetadataClient::new(&aws).await)
    }

    #[actix_rt::test]
    async fn test_object_endpoints_reject_missing_caller() {
        use actix_web::{http::StatusCode, test, App};

        let app = test::init_service(
            App::new()
                .app_data(unreachable_metadata().await)
                .route("/files/{file_id}", web::get().to(get_file_metadata))
                .route("/files/{file_id}/versions", web::get().to(list_versions))
                .route("/files/{file_id}/trash", web::post().to(trash_file))
                .route("/folders", web::post().to(create_folder))
                .route("/folders/{folder_id}", web::get().to(get_folder))
                .route("/folders/{folder_id}", web::delete().to(delete_folder)),
        )
        .await;

        let id = Uuid::new_v4();
        let requests = vec![
            test::TestRequest::get().uri(&format!("/files/{id}")),
            test::TestRequest::get().uri(&format!("/files/{id}/versions")),
            test::TestRequest::post().uri(&format!("/files/{id}/trash")),
            test::TestRequest::post()
                .uri("/folders")
                .set_json(serde_json::json!({"name": "x", "owner_id": Uuid::new_v4()})),
            test::TestRequest::get().uri(&format!("/folders/{id}")),
            test::TestRequest::delete().uri(&format!("/folders/{id}")),
        ];
        for r in requests {
            let resp = test::call_service(&app, r.to_request()).await;
            assert_eq!(resp.status(), StatusCode::UNAUTHORIZED);
        }
    }
}
