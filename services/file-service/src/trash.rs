use std::collections::HashMap;

use chrono::{DateTime, Duration, Utc};
use uuid::Uuid;

use crate::errors::ServiceError;
use crate::metadata::MetadataClient;
use crate::models::Folder;
use crate::storage::S3Client;

/// Guard against a cyclic parent chain while building a folder path.
const MAX_PATH_DEPTH: usize = 32;

/// Where an item lived when it was deleted.
pub struct Location {
    pub path: String,
    /// False when the folder (or one of its ancestors) is gone or itself
    /// trashed, so a restore has to fall back to the root.
    pub exists: bool,
}

/// Items deleted before this instant have outlived the retention window.
pub fn purge_cutoff(retention_days: i64, now: DateTime<Utc>) -> DateTime<Utc> {
    now - Duration::days(retention_days)
}

pub fn purge_at(deleted_at: DateTime<Utc>, retention_days: i64) -> DateTime<Utc> {
    deleted_at + Duration::days(retention_days)
}

/// Build the display path of the folder an item lived in. `folders` holds
/// every folder of the owner, trashed ones included.
pub fn resolve_location(folder_id: Option<Uuid>, folders: &HashMap<Uuid, Folder>) -> Location {
    let Some(mut current) = folder_id else {
        return Location {
            path: "/".into(),
            exists: true,
        };
    };

    let mut names: Vec<String> = Vec::new();
    let mut exists = true;

    for _ in 0..MAX_PATH_DEPTH {
        match folders.get(&current) {
            Some(folder) => {
                if folder.is_trashed {
                    exists = false;
                }
                names.push(folder.name.clone());
                match folder.parent_id {
                    Some(parent) => current = parent,
                    None => break,
                }
            }
            None => {
                exists = false;
                break;
            }
        }
    }

    names.reverse();
    Location {
        path: format!("/{}", names.join("/")),
        exists,
    }
}

/// Permanently remove trashed files and folders past the retention window.
pub async fn purge_expired(
    meta: &MetadataClient,
    s3: &S3Client,
    retention_days: i64,
) -> Result<usize, ServiceError> {
    let cutoff = purge_cutoff(retention_days, Utc::now());
    let mut purged = 0usize;

    for file in meta.list_trashed(None).await? {
        if file.deleted_at() >= cutoff {
            continue;
        }
        meta.delete_file(&file.id).await?;
        if let Err(err) = s3.delete_object(&file.s3_key).await {
            tracing::warn!(file_id = %file.id, error = %err, "Failed to purge file object");
        }
        purged += 1;
    }

    for folder in meta.list_trashed_folders(None).await? {
        if folder.deleted_at() >= cutoff {
            continue;
        }
        meta.delete_folder(&folder.id).await?;
        purged += 1;
    }

    if purged > 0 {
        tracing::info!(purged, retention_days, "Purged expired trash");
    }
    Ok(purged)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn folder(name: &str, parent_id: Option<Uuid>, is_trashed: bool) -> Folder {
        let now = Utc::now();
        Folder {
            id: Uuid::new_v4(),
            name: name.into(),
            parent_id,
            owner_id: Uuid::new_v4(),
            is_trashed,
            trashed_at: is_trashed.then_some(now),
            trashed_by: None,
            created_at: now,
            updated_at: now,
        }
    }

    fn index(folders: Vec<Folder>) -> HashMap<Uuid, Folder> {
        folders.into_iter().map(|f| (f.id, f)).collect()
    }

    #[test]
    fn root_items_resolve_to_root() {
        let location = resolve_location(None, &HashMap::new());
        assert_eq!(location.path, "/");
        assert!(location.exists);
    }

    #[test]
    fn nested_folders_build_a_full_path() {
        let reports = folder("Reports", None, false);
        let year = folder("2026", Some(reports.id), false);
        let year_id = year.id;
        let folders = index(vec![reports, year]);

        let location = resolve_location(Some(year_id), &folders);
        assert_eq!(location.path, "/Reports/2026");
        assert!(location.exists);
    }

    #[test]
    fn missing_folder_is_reported_as_gone() {
        let location = resolve_location(Some(Uuid::new_v4()), &HashMap::new());
        assert!(!location.exists);
    }

    #[test]
    fn trashed_folder_is_reported_as_gone() {
        let reports = folder("Reports", None, true);
        let reports_id = reports.id;
        let folders = index(vec![reports]);

        let location = resolve_location(Some(reports_id), &folders);
        assert_eq!(location.path, "/Reports");
        assert!(!location.exists);
    }

    #[test]
    fn retention_window_spans_the_configured_days() {
        let now = Utc::now();
        let cutoff = purge_cutoff(30, now);
        assert!(now - Duration::days(29) > cutoff);
        assert!(now - Duration::days(31) < cutoff);
        assert_eq!(purge_at(now, 30), now + Duration::days(30));
    }
}
