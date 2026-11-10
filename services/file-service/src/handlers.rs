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
use crate::audit::{AuditContext, AuditEmitter, AuditRecord};
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

/// All HTTP routes, shared by `main` and the handler tests.
pub fn configure(cfg: &mut web::ServiceConfig) {
    cfg.route("/health", web::get().to(health))
        .route("/metrics", web::get().to(metrics))
        .service(
            web::scope("/api/v1/files")
                .route("/upload", web::post().to(upload_file))
                .route("/shared", web::get().to(list_shared_files))
                .route("/trash", web::get().to(list_trashed))
                .route("/activity", web::get().to(list_activity))
                .route("", web::get().to(list_files))
                .route("/{file_id}", web::get().to(get_file_metadata))
                .route("/{file_id}", web::delete().to(delete_file))
                .route("/{file_id}/download", web::get().to(download_file))
                .route("/{file_id}/move", web::put().to(move_file))
                .route("/{file_id}/rename", web::patch().to(rename_file))
                .route("/{file_id}/versions", web::get().to(list_versions))
                .route("/{file_id}/trash", web::post().to(trash_file))
                .route("/{file_id}/restore", web::post().to(restore_file))
                .route("/{file_id}/share", web::post().to(share_file))
                .route("/{file_id}/share/{user_id}", web::delete().to(remove_share)),
        )
        .service(
            web::scope("/api/v1/folders")
                .route("", web::get().to(list_folders))
                .route("", web::post().to(create_folder))
                .route("/{folder_id}", web::get().to(get_folder))
                .route("/{folder_id}", web::put().to(update_folder))
                .route("/{folder_id}", web::delete().to(delete_folder)),
        );
}

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

fn parse_id(raw: &str, kind: &str) -> Result<Uuid, ServiceError> {
    raw.parse()
        .map_err(|e| ServiceError::BadRequest(format!("invalid {kind} id: {e}")))
}

/// Rejects callers authenticated as someone other than `owner`.
fn ensure_owner(ctx: &AuditContext, owner: &Uuid) -> Result<(), ServiceError> {
    if ctx.is_not(owner) {
        return Err(ServiceError::Forbidden(
            "only the owner can perform this action".into(),
        ));
    }
    Ok(())
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
    req: HttpRequest,
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    audit: web::Data<AuditEmitter>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let ctx = AuditContext::from_request(&req);
    let raw_id = path.into_inner();
    let mut record = AuditRecord::new("delete", "file", raw_id.clone());
    record.detail("soft", false);

    let result = async {
        let file_id = parse_id(&raw_id, "file")?;
        let file = meta.get_file(&file_id).await?;
        record.detail("ownerId", file.owner_id);
        ensure_owner(&ctx, &file.owner_id)?;
        meta.delete_file(&file_id).await?;
        s3.delete_object(&file.s3_key).await?;

        let _ = events.file_deleted(&file_id, &file.owner_id).await;

        tracing::info!(file_id = %file_id, "File deleted");
        Ok::<_, ServiceError>(HttpResponse::NoContent().finish())
    }
    .await;

    audit.record(&ctx, record, &result);
    result
}

pub async fn download_file(
    req: HttpRequest,
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    audit: web::Data<AuditEmitter>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let ctx = AuditContext::from_request(&req);
    let raw_id = path.into_inner();
    let mut record = AuditRecord::new("export", "file", raw_id.clone());
    record.detail("format", "presigned_url");

    let result = async {
        let file_id = parse_id(&raw_id, "file")?;
        let file = meta.get_file(&file_id).await?;
        record.detail("ownerId", file.owner_id);
        if ctx.is_not(&file.owner_id) {
            // Grantees may download files shared with them.
            let actor = ctx.user_id.as_deref().unwrap_or_default();
            let shared = meta
                .list_shares(&file_id)
                .await?
                .iter()
                .any(|s| s.shared_with.to_string().eq_ignore_ascii_case(actor));
            if !shared {
                return Err(ServiceError::Forbidden(
                    "file is not owned by or shared with the caller".into(),
                ));
            }
            record.detail("access", "share");
        } else {
            record.detail("access", "owner");
        }
        let url = s3.presigned_download_url(&file.s3_key, 3600).await?;

        Ok::<_, ServiceError>(HttpResponse::Ok().json(DownloadResponse {
            url,
            expires_in_secs: 3600,
        }))
    }
    .await;

    audit.record(&ctx, record, &result);
    result
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
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    audit: web::Data<AuditEmitter>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let ctx = AuditContext::from_request(&req);
    let raw_id = path.into_inner();
    let mut record = AuditRecord::new("delete", "file", raw_id.clone());
    record.detail("soft", true);

    let result = async {
        let file_id = parse_id(&raw_id, "file")?;
        let existing = meta.get_file(&file_id).await?;
        record.detail("ownerId", existing.owner_id);
        ensure_owner(&ctx, &existing.owner_id)?;
        let file = meta.trash_file(&file_id).await?;

        let _ = events.file_trashed(&file_id, &file.owner_id).await;

        tracing::info!(file_id = %file_id, "File trashed");
        Ok::<_, ServiceError>(HttpResponse::Ok().json(file))
    }
    .await;

    audit.record(&ctx, record, &result);
    result
}

pub async fn restore_file(
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    audit: web::Data<AuditEmitter>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let ctx = AuditContext::from_request(&req);
    let raw_id = path.into_inner();
    let mut record = AuditRecord::new("file.restore", "file", raw_id.clone());

    let result = async {
        let file_id = parse_id(&raw_id, "file")?;
        let existing = meta.get_file(&file_id).await?;
        record.detail("ownerId", existing.owner_id);
        ensure_owner(&ctx, &existing.owner_id)?;
        let file = meta.restore_file(&file_id).await?;

        let _ = events
            .file_restored(
                &file_id,
                &file.owner_id,
                file.folder_id.as_ref(),
                &file.name,
                &file.mime_type,
                file.size_bytes,
            )
            .await;

        tracing::info!(file_id = %file_id, "File restored");
        Ok::<_, ServiceError>(HttpResponse::Ok().json(file))
    }
    .await;

    audit.record(&ctx, record, &result);
    result
}

pub async fn share_file(
    req: HttpRequest,
    config: web::Data<AppConfig>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    audit: web::Data<AuditEmitter>,
    path: web::Path<String>,
    body: web::Json<ShareFileRequest>,
) -> Result<HttpResponse, ServiceError> {
    let ctx = AuditContext::from_request(&req);
    let raw_id = path.into_inner();
    let mut record = AuditRecord::new("share.create", "file", raw_id.clone());
    record.detail("permission", &body.permission);
    if let Some(id) = body.shared_with {
        record.detail("sharedWith", id);
    }

    let result = share_file_inner(
        &ctx,
        &mut record,
        &raw_id,
        &config,
        &meta,
        &events,
        &body,
        &req,
    )
    .await;
    audit.record(&ctx, record, &result);
    result
}

#[allow(clippy::too_many_arguments)]
async fn share_file_inner(
    ctx: &AuditContext,
    record: &mut AuditRecord,
    raw_id: &str,
    config: &AppConfig,
    meta: &MetadataClient,
    events: &EventPublisher,
    body: &ShareFileRequest,
    req: &HttpRequest,
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

    let file_id = parse_id(raw_id, "file")?;

    // Ensure file exists and the caller owns it
    let file = meta.get_file(&file_id).await?;
    record.detail("ownerId", file.owner_id);
    ensure_owner(ctx, &file.owner_id)?;

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
            record.detail("recipientResolved", false);
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
        record.detail("previousPermission", &existing.permission);
        if existing.permission != body.permission {
            record.action = "permission.change".into();
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
            record.detail("changed", false);
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
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    audit: web::Data<AuditEmitter>,
    path: web::Path<(String, String)>,
) -> Result<HttpResponse, ServiceError> {
    let ctx = AuditContext::from_request(&req);
    let (file_id_str, user_id_str) = path.into_inner();
    let mut record = AuditRecord::new("share.revoke", "file", file_id_str.clone());
    record.detail("sharedWith", &user_id_str);

    let result = async {
        let file_id = parse_id(&file_id_str, "file")?;
        let user_id = parse_id(&user_id_str, "user")?;

        // Ensure file exists; the owner may revoke any share and a grantee
        // may remove their own access.
        let file = meta.get_file(&file_id).await?;
        record.detail("ownerId", file.owner_id);
        if ctx.is_not(&user_id) {
            ensure_owner(&ctx, &file.owner_id)?;
        }

        // Find the existing share
        let share = meta
            .find_existing_share(&file_id, &user_id)
            .await?
            .ok_or_else(|| ServiceError::ShareNotFound("Share not found".into()))?;
        record.detail("permission", &share.permission);

        meta.delete_share(&share.id).await?;

        tracing::info!(file_id = %file_id, user_id = %user_id, "File share removed");
        Ok::<_, ServiceError>(HttpResponse::NoContent().finish())
    }
    .await;

    audit.record(&ctx, record, &result);
    result
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
    req: HttpRequest,
    meta: web::Data<MetadataClient>,
    audit: web::Data<AuditEmitter>,
    path: web::Path<String>,
) -> Result<HttpResponse, ServiceError> {
    let ctx = AuditContext::from_request(&req);
    let raw_id = path.into_inner();
    let mut record = AuditRecord::new("delete", "folder", raw_id.clone());
    record.detail("soft", false);

    let result = async {
        let folder_id = parse_id(&raw_id, "folder")?;
        // Deleting a missing folder stays an idempotent 204.
        match meta.get_folder(&folder_id).await {
            Ok(folder) => {
                record.detail("ownerId", folder.owner_id);
                ensure_owner(&ctx, &folder.owner_id)?;
            }
            Err(ServiceError::FolderNotFound(_)) => {
                record.detail("existed", false);
            }
            Err(err) => return Err(err),
        }

        meta.delete_folder(&folder_id).await?;
        tracing::info!(folder_id = %folder_id, "Folder deleted");
        Ok::<_, ServiceError>(HttpResponse::NoContent().finish())
    }
    .await;

    audit.record(&ctx, record, &result);
    result
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

/// Audit coverage: each audited action is driven through the real routes
/// against a wiremock DynamoDB/S3 and a wiremock audit-service.
#[cfg(test)]
mod audit_tests {
    use std::time::{Duration, Instant};

    use actix_web::http::StatusCode;
    use actix_web::{test, web, App};
    use serde_json::{json, Value};
    use uuid::Uuid;
    use wiremock::matchers::{body_partial_json, header, method, path, path_regex};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    use crate::alerts::AlertConfig;
    use crate::audit::{AuditConfig, AuditEmitter, AUDIT_EMIT_FAILURES_TOTAL};
    use crate::config::{AppConfig, AwsConfig, ServerConfig, SnsConfig};
    use crate::events::EventPublisher;
    use crate::metadata::MetadataClient;
    use crate::middleware;
    use crate::storage::S3Client;

    const TOKEN: &str = "test-audit-token";
    const CLIENT_IP: &str = "203.0.113.7";
    const FILES: &str = "files";
    const FOLDERS: &str = "folders";
    const SHARES: &str = "shares";
    const BUCKET: &str = "bucket";

    fn aws_config(endpoint: &str) -> AwsConfig {
        AwsConfig {
            region: "us-east-1".into(),
            endpoint_url: Some(endpoint.into()),
            s3_bucket: BUCKET.into(),
            dynamodb_table: FILES.into(),
            dynamodb_folders_table: FOLDERS.into(),
            dynamodb_versions_table: "versions".into(),
            dynamodb_shares_table: SHARES.into(),
        }
    }

    async fn sdk_config(endpoint: &str) -> aws_config::SdkConfig {
        aws_config::defaults(aws_config::BehaviorVersion::latest())
            .region(aws_config::Region::new("us-east-1"))
            .endpoint_url(endpoint)
            .credentials_provider(aws_sdk_dynamodb::config::Credentials::new(
                "test", "test", None, None, "test",
            ))
            .retry_config(aws_config::retry::RetryConfig::disabled())
            .load()
            .await
    }

    fn audit_config(url: String) -> AuditConfig {
        AuditConfig {
            url: Some(url),
            token: Some(TOKEN.into()),
            timeout: Duration::from_secs(2),
            max_retries: 1,
            retry_backoff: Duration::from_millis(10),
        }
    }

    struct Harness {
        aws: MockServer,
        audit: MockServer,
    }

    impl Harness {
        async fn new() -> Self {
            let audit = MockServer::start().await;
            Mock::given(method("POST"))
                .and(path("/api/v1/audit/events"))
                .and(header("x-audit-token", TOKEN))
                .respond_with(ResponseTemplate::new(202))
                .mount(&audit)
                .await;
            Self {
                aws: MockServer::start().await,
                audit,
            }
        }

        async fn dynamo(&self, op: &str, table: &str, body: Value) {
            Mock::given(method("POST"))
                .and(header(
                    "x-amz-target",
                    format!("DynamoDB_20120810.{op}").as_str(),
                ))
                .and(body_partial_json(json!({ "TableName": table })))
                .respond_with(
                    ResponseTemplate::new(200)
                        .set_body_raw(body.to_string(), "application/x-amz-json-1.0"),
                )
                .mount(&self.aws)
                .await;
        }

        async fn file(&self, file_id: Uuid, owner: Uuid) {
            self.dynamo(
                "GetItem",
                FILES,
                json!({ "Item": file_item(file_id, owner) }),
            )
            .await;
        }

        async fn shares(&self, items: Vec<Value>) {
            let n = items.len();
            self.dynamo(
                "Scan",
                SHARES,
                json!({ "Items": items, "Count": n, "ScannedCount": n }),
            )
            .await;
        }

        async fn dynamo_ops(&self) -> Vec<String> {
            self.aws
                .received_requests()
                .await
                .unwrap_or_default()
                .iter()
                .filter_map(|r| {
                    r.headers
                        .get("x-amz-target")
                        .and_then(|v| v.to_str().ok())
                        .map(|v| v.trim_start_matches("DynamoDB_20120810.").to_string())
                })
                .collect()
        }

        async fn send(&self, req: test::TestRequest) -> actix_web::dev::ServiceResponse {
            self.send_with(req, AuditEmitter::start(audit_config(self.audit.uri())))
                .await
        }

        async fn send_with(
            &self,
            req: test::TestRequest,
            emitter: AuditEmitter,
        ) -> actix_web::dev::ServiceResponse {
            let aws_cfg = aws_config(&self.aws.uri());
            let sdk = sdk_config(&self.aws.uri()).await;
            let meta = MetadataClient {
                client: aws_sdk_dynamodb::Client::new(&sdk),
                files_table: FILES.into(),
                folders_table: FOLDERS.into(),
                versions_table: "versions".into(),
                shares_table: SHARES.into(),
            };
            let s3 = S3Client {
                client: aws_sdk_s3::Client::from_conf(
                    aws_sdk_s3::config::Builder::from(&sdk)
                        .force_path_style(true)
                        .build(),
                ),
                bucket: BUCKET.into(),
            };
            let sns = SnsConfig {
                topic_arn: None,
                share_event_always_fail: false,
            };
            let events = EventPublisher::new(&sns, &aws_cfg).await;
            let config = AppConfig {
                server: ServerConfig {
                    port: 0,
                    max_upload_bytes: 1024,
                    upload_always_fail: false,
                    seed_demo_docs: false,
                },
                aws: aws_cfg,
                sns,
                alerts: AlertConfig {
                    admin_service_url: String::new(),
                    alert_webhook_secret: None,
                },
            };
            let app = test::init_service(
                App::new()
                    .wrap(middleware::RequestId)
                    .app_data(web::Data::new(config))
                    .app_data(web::Data::new(meta))
                    .app_data(web::Data::new(s3))
                    .app_data(web::Data::new(events))
                    .app_data(web::Data::new(emitter))
                    .configure(super::configure),
            )
            .await;
            test::call_service(&app, req.to_request()).await
        }

        /// Audit requests received, waiting up to 3s for `n` to arrive.
        async fn audit_requests(&self, n: usize) -> Vec<wiremock::Request> {
            wait_for(&self.audit, n).await
        }

        async fn audit_events(&self, n: usize) -> Vec<Value> {
            self.audit_requests(n)
                .await
                .iter()
                .map(|r| serde_json::from_slice(&r.body).expect("audit body is JSON"))
                .collect()
        }
    }

    async fn wait_for(server: &MockServer, n: usize) -> Vec<wiremock::Request> {
        let deadline = Instant::now() + Duration::from_secs(3);
        loop {
            let reqs = server.received_requests().await.unwrap_or_default();
            if reqs.len() >= n || Instant::now() > deadline {
                return reqs;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }

    fn file_item(file_id: Uuid, owner: Uuid) -> Value {
        json!({
            "id": { "S": file_id.to_string() },
            "name": { "S": "q3-report.pdf" },
            "mime_type": { "S": "application/pdf" },
            "size_bytes": { "N": "42" },
            "s3_key": { "S": format!("files/{owner}/{file_id}") },
            "owner_id": { "S": owner.to_string() },
            "version": { "N": "1" },
            "is_trashed": { "BOOL": false },
            "created_at": { "S": "2026-11-10T16:00:00+00:00" },
            "updated_at": { "S": "2026-11-10T16:00:00+00:00" }
        })
    }

    fn share_item(file_id: Uuid, owner: Uuid, grantee: Uuid, permission: &str) -> Value {
        json!({
            "id": { "S": Uuid::new_v4().to_string() },
            "file_id": { "S": file_id.to_string() },
            "shared_with": { "S": grantee.to_string() },
            "permission": { "S": permission },
            "shared_by": { "S": owner.to_string() },
            "created_at": { "S": "2026-11-10T16:00:00+00:00" }
        })
    }

    fn as_user(req: test::TestRequest, user: Uuid, request_id: &str) -> test::TestRequest {
        req.insert_header(("X-User-ID", user.to_string()))
            .insert_header(("X-User-Email", "owner@otterworks.test"))
            .insert_header(("X-Forwarded-For", format!("{CLIENT_IP}, 10.0.0.12")))
            .insert_header(("User-Agent", "audit-test/1.0"))
            .insert_header(("X-Request-ID", request_id))
    }

    fn assert_event(
        event: &Value,
        action: &str,
        actor: Uuid,
        resource_type: &str,
        resource_id: Uuid,
        outcome: &str,
        request_id: &str,
    ) {
        assert_eq!(event["action"], action, "{event}");
        assert_eq!(event["userId"], actor.to_string(), "{event}");
        assert_eq!(event["actorType"], "user", "{event}");
        assert_eq!(event["actorEmail"], "owner@otterworks.test", "{event}");
        assert_eq!(event["resourceType"], resource_type, "{event}");
        assert_eq!(event["resourceId"], resource_id.to_string(), "{event}");
        assert_eq!(event["outcome"], outcome, "{event}");
        assert_eq!(event["ipAddress"], CLIENT_IP, "{event}");
        assert_eq!(event["userAgent"], "audit-test/1.0", "{event}");
        assert_eq!(event["requestId"], request_id, "{event}");
        assert_eq!(event["serviceName"], "file-service", "{event}");
        assert!(
            event["timestamp"].as_str().unwrap().ends_with('Z'),
            "{event}"
        );
    }

    fn share_body(grantee: Uuid, owner: Uuid, permission: &str) -> Value {
        json!({ "shared_with": grantee, "permission": permission, "shared_by": owner })
    }

    #[actix_rt::test]
    async fn share_new_grantee_emits_share_create() {
        let h = Harness::new().await;
        let (file_id, owner, grantee) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.shares(vec![]).await;
        h.dynamo("PutItem", SHARES, json!({})).await;

        let req = as_user(
            test::TestRequest::post()
                .uri(&format!("/api/v1/files/{file_id}/share"))
                .set_json(share_body(grantee, owner, "viewer")),
            owner,
            "req-share-create",
        );
        let resp = h.send(req).await;
        assert_eq!(resp.status(), StatusCode::CREATED);

        let reqs = h.audit_requests(1).await;
        assert_eq!(reqs.len(), 1);
        assert_eq!(
            reqs[0].headers.get("x-request-id").unwrap(),
            "req-share-create"
        );
        assert_eq!(
            reqs[0].headers.get("content-type").unwrap(),
            "application/json"
        );
        let event: Value = serde_json::from_slice(&reqs[0].body).unwrap();
        assert_event(
            &event,
            "share.create",
            owner,
            "file",
            file_id,
            "success",
            "req-share-create",
        );
        assert_eq!(event["details"]["sharedWith"], grantee.to_string());
        assert_eq!(event["details"]["permission"], "viewer");
    }

    #[actix_rt::test]
    async fn share_permission_update_emits_permission_change() {
        let h = Harness::new().await;
        let (file_id, owner, grantee) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.shares(vec![share_item(file_id, owner, grantee, "viewer")])
            .await;
        h.dynamo("PutItem", SHARES, json!({})).await;

        let req = as_user(
            test::TestRequest::post()
                .uri(&format!("/api/v1/files/{file_id}/share"))
                .set_json(share_body(grantee, owner, "editor")),
            owner,
            "req-perm",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::OK);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "permission.change",
            owner,
            "file",
            file_id,
            "success",
            "req-perm",
        );
        assert_eq!(event["details"]["permission"], "editor");
        assert_eq!(event["details"]["previousPermission"], "viewer");
    }

    #[actix_rt::test]
    async fn share_by_non_owner_is_denied_and_audited() {
        let h = Harness::new().await;
        let (file_id, owner, intruder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;

        let req = as_user(
            test::TestRequest::post()
                .uri(&format!("/api/v1/files/{file_id}/share"))
                .set_json(share_body(intruder, intruder, "editor")),
            intruder,
            "req-share-denied",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::FORBIDDEN);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "share.create",
            intruder,
            "file",
            file_id,
            "denied",
            "req-share-denied",
        );
        assert_eq!(event["details"]["reason"], "not_owner");
        assert_eq!(event["details"]["ownerId"], owner.to_string());
        assert!(!h.dynamo_ops().await.contains(&"PutItem".to_string()));
    }

    #[actix_rt::test]
    async fn remove_share_emits_share_revoke() {
        let h = Harness::new().await;
        let (file_id, owner, grantee) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.shares(vec![share_item(file_id, owner, grantee, "editor")])
            .await;
        h.dynamo("DeleteItem", SHARES, json!({})).await;

        let req = as_user(
            test::TestRequest::delete().uri(&format!("/api/v1/files/{file_id}/share/{grantee}")),
            owner,
            "req-revoke",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::NO_CONTENT);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "share.revoke",
            owner,
            "file",
            file_id,
            "success",
            "req-revoke",
        );
        assert_eq!(event["details"]["sharedWith"], grantee.to_string());
        assert_eq!(event["details"]["permission"], "editor");
    }

    #[actix_rt::test]
    async fn remove_share_by_third_party_is_denied() {
        let h = Harness::new().await;
        let (file_id, owner, grantee, intruder) = (
            Uuid::new_v4(),
            Uuid::new_v4(),
            Uuid::new_v4(),
            Uuid::new_v4(),
        );
        h.file(file_id, owner).await;

        let req = as_user(
            test::TestRequest::delete().uri(&format!("/api/v1/files/{file_id}/share/{grantee}")),
            intruder,
            "req-revoke-denied",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::FORBIDDEN);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "share.revoke",
            intruder,
            "file",
            file_id,
            "denied",
            "req-revoke-denied",
        );
        assert!(!h.dynamo_ops().await.contains(&"DeleteItem".to_string()));
    }

    #[actix_rt::test]
    async fn download_emits_export_without_presigned_url() {
        let h = Harness::new().await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;

        let req = as_user(
            test::TestRequest::get().uri(&format!("/api/v1/files/{file_id}/download")),
            owner,
            "req-export",
        );
        let resp = h.send(req).await;
        assert_eq!(resp.status(), StatusCode::OK);
        let body: Value = test::read_body_json(resp).await;
        let url = body["url"].as_str().unwrap().to_string();

        let reqs = h.audit_requests(1).await;
        let event: Value = serde_json::from_slice(&reqs[0].body).unwrap();
        assert_event(
            &event,
            "export",
            owner,
            "file",
            file_id,
            "success",
            "req-export",
        );
        assert_eq!(event["details"]["access"], "owner");
        let raw = String::from_utf8_lossy(&reqs[0].body);
        assert!(!raw.contains(&url), "presigned URL leaked: {raw}");
        assert!(!raw.contains("X-Amz-Signature"), "{raw}");
    }

    #[actix_rt::test]
    async fn download_by_grantee_is_allowed() {
        let h = Harness::new().await;
        let (file_id, owner, grantee) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.shares(vec![share_item(file_id, owner, grantee, "viewer")])
            .await;

        let req = as_user(
            test::TestRequest::get().uri(&format!("/api/v1/files/{file_id}/download")),
            grantee,
            "req-export-share",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::OK);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "export",
            grantee,
            "file",
            file_id,
            "success",
            "req-export-share",
        );
        assert_eq!(event["details"]["access"], "share");
    }

    #[actix_rt::test]
    async fn download_by_stranger_is_denied() {
        let h = Harness::new().await;
        let (file_id, owner, stranger) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.shares(vec![]).await;

        let req = as_user(
            test::TestRequest::get().uri(&format!("/api/v1/files/{file_id}/download")),
            stranger,
            "req-export-denied",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::FORBIDDEN);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "export",
            stranger,
            "file",
            file_id,
            "denied",
            "req-export-denied",
        );
    }

    #[actix_rt::test]
    async fn delete_file_emits_delete() {
        let h = Harness::new().await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.dynamo("DeleteItem", FILES, json!({})).await;
        Mock::given(method("DELETE"))
            .and(path_regex(format!("^/{BUCKET}/files/.*")))
            .respond_with(ResponseTemplate::new(204))
            .mount(&h.aws)
            .await;

        let req = as_user(
            test::TestRequest::delete().uri(&format!("/api/v1/files/{file_id}")),
            owner,
            "req-delete",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::NO_CONTENT);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "delete",
            owner,
            "file",
            file_id,
            "success",
            "req-delete",
        );
        assert_eq!(event["details"]["soft"], "false");
    }

    #[actix_rt::test]
    async fn delete_file_by_non_owner_is_denied() {
        let h = Harness::new().await;
        let (file_id, owner, intruder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;

        let req = as_user(
            test::TestRequest::delete().uri(&format!("/api/v1/files/{file_id}")),
            intruder,
            "req-delete-denied",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::FORBIDDEN);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "delete",
            intruder,
            "file",
            file_id,
            "denied",
            "req-delete-denied",
        );
        assert!(!h.dynamo_ops().await.contains(&"DeleteItem".to_string()));
    }

    #[actix_rt::test]
    async fn delete_missing_file_is_audited_as_failure() {
        let h = Harness::new().await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.dynamo("GetItem", FILES, json!({})).await;

        let req = as_user(
            test::TestRequest::delete().uri(&format!("/api/v1/files/{file_id}")),
            owner,
            "req-delete-missing",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::NOT_FOUND);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "delete",
            owner,
            "file",
            file_id,
            "failure",
            "req-delete-missing",
        );
        assert_eq!(event["details"]["reason"], "file_not_found");
    }

    #[actix_rt::test]
    async fn delete_folder_emits_delete() {
        let h = Harness::new().await;
        let (folder_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.dynamo(
            "GetItem",
            FOLDERS,
            json!({ "Item": {
                "id": { "S": folder_id.to_string() },
                "name": { "S": "Finance" },
                "owner_id": { "S": owner.to_string() },
                "created_at": { "S": "2026-11-10T16:00:00+00:00" },
                "updated_at": { "S": "2026-11-10T16:00:00+00:00" }
            }}),
        )
        .await;
        h.dynamo("DeleteItem", FOLDERS, json!({})).await;

        let req = as_user(
            test::TestRequest::delete().uri(&format!("/api/v1/folders/{folder_id}")),
            owner,
            "req-folder",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::NO_CONTENT);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "delete",
            owner,
            "folder",
            folder_id,
            "success",
            "req-folder",
        );
    }

    #[actix_rt::test]
    async fn delete_folder_by_non_owner_is_denied() {
        let h = Harness::new().await;
        let (folder_id, owner, intruder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.dynamo(
            "GetItem",
            FOLDERS,
            json!({ "Item": {
                "id": { "S": folder_id.to_string() },
                "name": { "S": "Finance" },
                "owner_id": { "S": owner.to_string() },
                "created_at": { "S": "2026-11-10T16:00:00+00:00" },
                "updated_at": { "S": "2026-11-10T16:00:00+00:00" }
            }}),
        )
        .await;

        let req = as_user(
            test::TestRequest::delete().uri(&format!("/api/v1/folders/{folder_id}")),
            intruder,
            "req-folder-denied",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::FORBIDDEN);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "delete",
            intruder,
            "folder",
            folder_id,
            "denied",
            "req-folder-denied",
        );
        assert!(!h.dynamo_ops().await.contains(&"DeleteItem".to_string()));
    }

    #[actix_rt::test]
    async fn trash_emits_soft_delete() {
        let h = Harness::new().await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.dynamo("UpdateItem", FILES, json!({})).await;

        let req = as_user(
            test::TestRequest::post().uri(&format!("/api/v1/files/{file_id}/trash")),
            owner,
            "req-trash",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::OK);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "delete",
            owner,
            "file",
            file_id,
            "success",
            "req-trash",
        );
        assert_eq!(event["details"]["soft"], "true");
    }

    #[actix_rt::test]
    async fn trash_by_non_owner_is_denied() {
        let h = Harness::new().await;
        let (file_id, owner, intruder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;

        let req = as_user(
            test::TestRequest::post().uri(&format!("/api/v1/files/{file_id}/trash")),
            intruder,
            "req-trash-denied",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::FORBIDDEN);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "delete",
            intruder,
            "file",
            file_id,
            "denied",
            "req-trash-denied",
        );
        assert!(!h.dynamo_ops().await.contains(&"UpdateItem".to_string()));
    }

    #[actix_rt::test]
    async fn restore_emits_file_restore() {
        let h = Harness::new().await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.dynamo("UpdateItem", FILES, json!({})).await;

        let req = as_user(
            test::TestRequest::post().uri(&format!("/api/v1/files/{file_id}/restore")),
            owner,
            "req-restore",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::OK);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "file.restore",
            owner,
            "file",
            file_id,
            "success",
            "req-restore",
        );
    }

    #[actix_rt::test]
    async fn restore_by_non_owner_is_denied() {
        let h = Harness::new().await;
        let (file_id, owner, intruder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;

        let req = as_user(
            test::TestRequest::post().uri(&format!("/api/v1/files/{file_id}/restore")),
            intruder,
            "req-restore-denied",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::FORBIDDEN);

        let event = &h.audit_events(1).await[0];
        assert_event(
            event,
            "file.restore",
            intruder,
            "file",
            file_id,
            "denied",
            "req-restore-denied",
        );
    }

    #[actix_rt::test]
    async fn real_ip_and_generated_request_id_are_used_without_forwarded_for() {
        let h = Harness::new().await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;

        let req = test::TestRequest::get()
            .uri(&format!("/api/v1/files/{file_id}/download"))
            .insert_header(("X-User-ID", owner.to_string()))
            .insert_header(("X-Real-IP", "198.51.100.9"));
        assert_eq!(h.send(req).await.status(), StatusCode::OK);

        let event = &h.audit_events(1).await[0];
        assert_eq!(event["ipAddress"], "198.51.100.9");
        assert!(Uuid::parse_str(event["requestId"].as_str().unwrap()).is_ok());
        assert!(event.get("actorEmail").is_none());
    }

    #[actix_rt::test]
    async fn audit_service_5xx_does_not_change_response() {
        let h = Harness::new().await;
        let failing = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(503))
            .mount(&failing)
            .await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.dynamo("UpdateItem", FILES, json!({})).await;
        let before = AUDIT_EMIT_FAILURES_TOTAL
            .with_label_values(&["http_status"])
            .get();

        let req = as_user(
            test::TestRequest::post().uri(&format!("/api/v1/files/{file_id}/trash")),
            owner,
            "req-5xx",
        );
        let resp = h
            .send_with(req, AuditEmitter::start(audit_config(failing.uri())))
            .await;
        assert_eq!(resp.status(), StatusCode::OK);

        // One attempt plus `max_retries` (1) retry, then counted as a failure.
        assert_eq!(wait_for(&failing, 2).await.len(), 2);
        let deadline = Instant::now() + Duration::from_secs(3);
        while AUDIT_EMIT_FAILURES_TOTAL
            .with_label_values(&["http_status"])
            .get()
            <= before
        {
            assert!(Instant::now() < deadline, "failure was not counted");
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }

    #[actix_rt::test]
    async fn slow_audit_service_does_not_delay_response() {
        let h = Harness::new().await;
        let slow = MockServer::start().await;
        Mock::given(method("POST"))
            .respond_with(ResponseTemplate::new(202).set_delay(Duration::from_secs(5)))
            .mount(&slow)
            .await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        let mut cfg = audit_config(slow.uri());
        cfg.timeout = Duration::from_millis(200);

        let started = Instant::now();
        let req = as_user(
            test::TestRequest::get().uri(&format!("/api/v1/files/{file_id}/download")),
            owner,
            "req-slow",
        );
        let resp = h.send_with(req, AuditEmitter::start(cfg)).await;
        assert_eq!(resp.status(), StatusCode::OK);
        assert!(
            started.elapsed() < Duration::from_secs(2),
            "request waited on audit-service: {:?}",
            started.elapsed()
        );
    }

    #[actix_rt::test]
    async fn unreachable_audit_service_does_not_change_status_codes() {
        let h = Harness::new().await;
        let (file_id, owner, intruder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        // A port nothing listens on.
        let port = std::net::TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let unreachable = format!("http://127.0.0.1:{port}");

        let ok = h
            .send_with(
                as_user(
                    test::TestRequest::get().uri(&format!("/api/v1/files/{file_id}/download")),
                    owner,
                    "req-down-ok",
                ),
                AuditEmitter::start(audit_config(unreachable.clone())),
            )
            .await;
        assert_eq!(ok.status(), StatusCode::OK);

        let denied = h
            .send_with(
                as_user(
                    test::TestRequest::delete().uri(&format!("/api/v1/files/{file_id}")),
                    intruder,
                    "req-down-denied",
                ),
                AuditEmitter::start(audit_config(unreachable)),
            )
            .await;
        assert_eq!(denied.status(), StatusCode::FORBIDDEN);
    }

    #[actix_rt::test]
    async fn no_secrets_or_payloads_are_sent() {
        let h = Harness::new().await;
        let (file_id, owner, grantee) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        h.shares(vec![]).await;
        h.dynamo("PutItem", SHARES, json!({})).await;

        let jwt = "eyJhbGciOiJIUzI1NiJ9.secret-jwt-payload.sig";
        let req = as_user(
            test::TestRequest::post()
                .uri(&format!("/api/v1/files/{file_id}/share"))
                .insert_header(("Authorization", format!("Bearer {jwt}")))
                .insert_header(("Cookie", "refresh_token=super-secret-refresh"))
                .insert_header(("X-Share-Token", "share-link-token-123"))
                .set_json(json!({
                    "shared_with": grantee,
                    "permission": "viewer",
                    "shared_by": owner,
                    "password": "hunter2",
                    "token": "body-token-456"
                })),
            owner,
            "req-secrets",
        );
        assert_eq!(h.send(req).await.status(), StatusCode::CREATED);

        let reqs = h.audit_requests(1).await;
        let raw = String::from_utf8_lossy(&reqs[0].body).to_string();
        for secret in [
            jwt,
            "super-secret-refresh",
            "share-link-token-123",
            "hunter2",
            "body-token-456",
            "q3-report.pdf",
        ] {
            assert!(!raw.contains(secret), "{secret} leaked in {raw}");
        }
        let event: Value = serde_json::from_str(&raw).unwrap();
        let keys: Vec<String> = event
            .as_object()
            .unwrap()
            .keys()
            .chain(event["details"].as_object().unwrap().keys())
            .map(|k| k.to_ascii_lowercase())
            .collect();
        for forbidden in [
            "password",
            "token",
            "secret",
            "authorization",
            "cookie",
            "content",
        ] {
            assert!(
                !keys.iter().any(|k| k.contains(forbidden)),
                "{forbidden} key in {keys:?}"
            );
        }
        assert!(reqs[0].headers.get("authorization").is_none());
        assert!(reqs[0].headers.get("cookie").is_none());
    }

    #[actix_rt::test]
    async fn disabled_emitter_keeps_handlers_working() {
        let h = Harness::new().await;
        let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        h.file(file_id, owner).await;
        let req = as_user(
            test::TestRequest::get().uri(&format!("/api/v1/files/{file_id}/download")),
            owner,
            "req-disabled",
        );
        assert_eq!(
            h.send_with(req, AuditEmitter::disabled()).await.status(),
            StatusCode::OK
        );
    }
}
