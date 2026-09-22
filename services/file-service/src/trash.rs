use std::collections::{HashMap, HashSet};

use chrono::{DateTime, Duration, Utc};
use uuid::Uuid;

use crate::errors::ServiceError;
use crate::metadata::MetadataClient;
use crate::models::{FileMetadata, Folder};
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

/// Permanently remove a file. The stored object goes first so that a failed
/// S3 delete leaves the metadata — and therefore the only record of the key —
/// in place for the next attempt.
pub async fn purge_file(
    meta: &MetadataClient,
    s3: &S3Client,
    file: &FileMetadata,
) -> Result<(), ServiceError> {
    s3.delete_object(&file.s3_key).await?;
    meta.delete_file(&file.id).await
}

/// Permanently remove a folder together with every descendant folder and file,
/// so nothing is left pointing at a parent that no longer exists. Returns the
/// number of records removed.
pub async fn purge_folder_tree(
    meta: &MetadataClient,
    s3: &S3Client,
    folder_id: &Uuid,
) -> Result<usize, ServiceError> {
    let mut children: HashMap<Uuid, Vec<Uuid>> = HashMap::new();
    for folder in meta.list_all_folders(None).await? {
        if let Some(parent) = folder.parent_id {
            children.entry(parent).or_default().push(folder.id);
        }
    }

    // Breadth-first so the subtree comes out parents-first; deleting in reverse
    // then works from the leaves up. `seen` guards against a cyclic chain.
    let mut seen: HashSet<Uuid> = HashSet::from([*folder_id]);
    let mut subtree = vec![*folder_id];
    let mut cursor = 0;
    while cursor < subtree.len() {
        let current = subtree[cursor];
        cursor += 1;
        for child in children.get(&current).into_iter().flatten() {
            if seen.insert(*child) {
                subtree.push(*child);
            }
        }
    }

    let mut purged = 0usize;
    for id in subtree.iter().rev() {
        for file in meta.list_files(Some(*id), None, true).await? {
            purge_file(meta, s3, &file).await?;
            purged += 1;
        }
        meta.delete_folder(id).await?;
        purged += 1;
    }

    Ok(purged)
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
        // A failure here is not fatal to the run: leave the record alone and
        // let the next tick retry it.
        match purge_file(meta, s3, &file).await {
            Ok(()) => purged += 1,
            Err(err) => tracing::warn!(file_id = %file.id, error = %err, "Failed to purge file"),
        }
    }

    for folder in meta.list_trashed_folders(None).await? {
        if folder.deleted_at() >= cutoff {
            continue;
        }
        match purge_folder_tree(meta, s3, &folder.id).await {
            Ok(count) => purged += count,
            Err(err) => {
                tracing::warn!(folder_id = %folder.id, error = %err, "Failed to purge folder")
            }
        }
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
