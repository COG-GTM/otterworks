use std::time::Duration as StdDuration;

use chrono::{DateTime, Utc};

use crate::errors::ServiceError;
use crate::events::EventPublisher;
use crate::metadata::MetadataClient;
use crate::storage::S3Client;

/// How often the background purge sweep runs.
pub const PURGE_INTERVAL: StdDuration = StdDuration::from_secs(60 * 60);

/// Permanently delete every trashed item whose retention window has elapsed,
/// removing both the stored object and its metadata. Returns how many items
/// were purged.
pub async fn purge_expired_trash(
    meta: &MetadataClient,
    s3: &S3Client,
    events: &EventPublisher,
    now: DateTime<Utc>,
) -> Result<usize, ServiceError> {
    let expired = meta.list_expired_trashed(now).await?;
    let mut purged = 0;

    for file in expired {
        if let Err(e) = s3.delete_object(&file.s3_key).await {
            tracing::warn!(file_id = %file.id, error = %e, "Trash purge: object delete failed");
            continue;
        }
        if let Err(e) = meta.delete_file(&file.id).await {
            tracing::warn!(file_id = %file.id, error = %e, "Trash purge: metadata delete failed");
            continue;
        }
        let _ = events.file_deleted(&file.id, &file.owner_id).await;
        purged += 1;
        tracing::info!(file_id = %file.id, "Trash purge: item permanently deleted");
    }

    Ok(purged)
}

/// Run the purge sweep on a fixed interval for the lifetime of the process.
pub async fn run_purge_loop(meta: MetadataClient, s3: S3Client, events: EventPublisher) {
    let mut ticker = tokio::time::interval(PURGE_INTERVAL);
    loop {
        ticker.tick().await;
        match purge_expired_trash(&meta, &s3, &events, Utc::now()).await {
            Ok(purged) if purged > 0 => {
                tracing::info!(purged, "Trash purge sweep complete")
            }
            Ok(_) => {}
            Err(e) => tracing::warn!(error = %e, "Trash purge sweep failed"),
        }
    }
}
