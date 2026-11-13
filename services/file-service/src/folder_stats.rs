use std::collections::{BTreeMap, HashMap, HashSet};

use uuid::Uuid;

use crate::errors::ServiceError;
use crate::models::{FileMetadata, FileTypeStats, Folder, FolderStatsResponse};

const UNKNOWN_FILE_TYPE: &str = "application/octet-stream";

/// Folders are private to their owner. A folder the user cannot access is
/// reported as not found so its existence is not leaked.
pub fn ensure_folder_access(folder: &Folder, user_id: &Uuid) -> Result<(), ServiceError> {
    if folder.owner_id == *user_id {
        Ok(())
    } else {
        Err(ServiceError::FolderNotFound(folder.id.to_string()))
    }
}

/// Aggregate non-trashed files under `root` and every subfolder (at any depth)
/// the user can access, grouped by MIME type.
pub fn compute_folder_stats(
    root: &Folder,
    user_id: &Uuid,
    folders: &[Folder],
    files: &[FileMetadata],
) -> Result<FolderStatsResponse, ServiceError> {
    ensure_folder_access(root, user_id)?;

    let subtree = accessible_subtree(root.id, user_id, folders);

    let mut by_type: BTreeMap<String, (u64, u64)> = BTreeMap::new();
    let mut total_files = 0u64;
    let mut total_size_bytes = 0u64;
    for file in files {
        if file.is_trashed || !file.folder_id.is_some_and(|fid| subtree.contains(&fid)) {
            continue;
        }
        let entry = by_type
            .entry(normalize_file_type(&file.mime_type))
            .or_default();
        entry.0 += 1;
        entry.1 += file.size_bytes;
        total_files += 1;
        total_size_bytes += file.size_bytes;
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

    Ok(FolderStatsResponse {
        folder_id: root.id,
        subfolder_count: (subtree.len() - 1) as u64,
        total_files,
        total_size_bytes,
        by_type,
    })
}

fn accessible_subtree(root_id: Uuid, user_id: &Uuid, folders: &[Folder]) -> HashSet<Uuid> {
    let mut children: HashMap<Uuid, Vec<Uuid>> = HashMap::new();
    for folder in folders.iter().filter(|f| f.owner_id == *user_id) {
        if let Some(parent_id) = folder.parent_id {
            children.entry(parent_id).or_default().push(folder.id);
        }
    }

    let mut subtree = HashSet::from([root_id]);
    let mut stack = vec![root_id];
    while let Some(id) = stack.pop() {
        for child in children.get(&id).into_iter().flatten() {
            if subtree.insert(*child) {
                stack.push(*child);
            }
        }
    }
    subtree
}

fn normalize_file_type(mime_type: &str) -> String {
    let base = mime_type.split(';').next().unwrap_or_default().trim();
    if base.is_empty() {
        UNKNOWN_FILE_TYPE.to_string()
    } else {
        base.to_ascii_lowercase()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn folder(owner_id: Uuid, parent_id: Option<Uuid>) -> Folder {
        let now = Utc::now();
        Folder {
            id: Uuid::new_v4(),
            name: "folder".into(),
            parent_id,
            owner_id,
            created_at: now,
            updated_at: now,
        }
    }

    fn file(folder_id: Option<Uuid>, mime_type: &str, size_bytes: u64) -> FileMetadata {
        let now = Utc::now();
        let id = Uuid::new_v4();
        FileMetadata {
            id,
            name: "file".into(),
            mime_type: mime_type.into(),
            size_bytes,
            s3_key: format!("files/{id}"),
            folder_id,
            owner_id: Uuid::new_v4(),
            version: 1,
            is_trashed: false,
            created_at: now,
            updated_at: now,
        }
    }

    fn type_stats(stats: &FolderStatsResponse, file_type: &str) -> Option<(u64, u64)> {
        stats
            .by_type
            .iter()
            .find(|t| t.file_type == file_type)
            .map(|t| (t.file_count, t.total_size_bytes))
    }

    #[test]
    fn nested_folders_are_included_at_every_depth() {
        let user = Uuid::new_v4();
        let root = folder(user, None);
        let child = folder(user, Some(root.id));
        let grandchild = folder(user, Some(child.id));
        let sibling = folder(user, None);
        let folders = vec![
            root.clone(),
            child.clone(),
            grandchild.clone(),
            sibling.clone(),
        ];
        let files = vec![
            file(Some(root.id), "application/pdf", 100),
            file(Some(child.id), "application/pdf", 50),
            file(Some(child.id), "text/csv; charset=utf-8", 10),
            file(Some(grandchild.id), "image/PNG", 7),
            file(Some(sibling.id), "application/pdf", 1_000),
            file(None, "application/pdf", 1_000),
        ];

        let stats = compute_folder_stats(&root, &user, &folders, &files).unwrap();

        assert_eq!(stats.folder_id, root.id);
        assert_eq!(stats.subfolder_count, 2);
        assert_eq!(stats.total_files, 4);
        assert_eq!(stats.total_size_bytes, 167);
        assert_eq!(type_stats(&stats, "application/pdf"), Some((2, 150)));
        assert_eq!(type_stats(&stats, "text/csv"), Some((1, 10)));
        assert_eq!(type_stats(&stats, "image/png"), Some((1, 7)));
        assert_eq!(stats.by_type[0].file_type, "application/pdf");
    }

    #[test]
    fn stats_for_a_subfolder_exclude_its_parent() {
        let user = Uuid::new_v4();
        let root = folder(user, None);
        let child = folder(user, Some(root.id));
        let folders = vec![root.clone(), child.clone()];
        let files = vec![
            file(Some(root.id), "application/pdf", 100),
            file(Some(child.id), "text/plain", 5),
        ];

        let stats = compute_folder_stats(&child, &user, &folders, &files).unwrap();

        assert_eq!(stats.subfolder_count, 0);
        assert_eq!(stats.total_files, 1);
        assert_eq!(type_stats(&stats, "text/plain"), Some((1, 5)));
    }

    #[test]
    fn folder_owned_by_another_user_is_not_found() {
        let owner = Uuid::new_v4();
        let other = Uuid::new_v4();
        let root = folder(owner, None);
        let files = vec![file(Some(root.id), "application/pdf", 100)];

        let err =
            compute_folder_stats(&root, &other, std::slice::from_ref(&root), &files).unwrap_err();

        assert!(matches!(err, ServiceError::FolderNotFound(id) if id == root.id.to_string()));
        assert!(ensure_folder_access(&root, &owner).is_ok());
    }

    #[test]
    fn subfolders_the_user_cannot_access_are_excluded() {
        let user = Uuid::new_v4();
        let other = Uuid::new_v4();
        let root = folder(user, None);
        let foreign = folder(other, Some(root.id));
        let nested_in_foreign = folder(user, Some(foreign.id));
        let folders = vec![root.clone(), foreign.clone(), nested_in_foreign.clone()];
        let files = vec![
            file(Some(root.id), "text/plain", 1),
            file(Some(foreign.id), "application/pdf", 100),
            file(Some(nested_in_foreign.id), "application/pdf", 100),
        ];

        let stats = compute_folder_stats(&root, &user, &folders, &files).unwrap();

        assert_eq!(stats.subfolder_count, 0);
        assert_eq!(stats.total_files, 1);
        assert_eq!(type_stats(&stats, "application/pdf"), None);
    }

    #[test]
    fn empty_folder_returns_zero_counts() {
        let user = Uuid::new_v4();
        let root = folder(user, None);

        let stats = compute_folder_stats(&root, &user, std::slice::from_ref(&root), &[]).unwrap();

        assert_eq!(
            stats,
            FolderStatsResponse {
                folder_id: root.id,
                subfolder_count: 0,
                total_files: 0,
                total_size_bytes: 0,
                by_type: vec![],
            }
        );
    }

    #[test]
    fn trashed_files_are_excluded() {
        let user = Uuid::new_v4();
        let root = folder(user, None);
        let mut trashed = file(Some(root.id), "application/pdf", 100);
        trashed.is_trashed = true;

        let stats =
            compute_folder_stats(&root, &user, std::slice::from_ref(&root), &[trashed]).unwrap();

        assert_eq!(stats.total_files, 0);
        assert!(stats.by_type.is_empty());
    }

    #[test]
    fn folder_cycles_do_not_loop_forever() {
        let user = Uuid::new_v4();
        let mut a = folder(user, None);
        let b = folder(user, Some(a.id));
        a.parent_id = Some(b.id);
        let folders = vec![a.clone(), b.clone()];
        let files = vec![file(Some(b.id), "text/plain", 3)];

        let stats = compute_folder_stats(&a, &user, &folders, &files).unwrap();

        assert_eq!(stats.subfolder_count, 1);
        assert_eq!(stats.total_files, 1);
    }

    #[test]
    fn missing_mime_type_is_grouped_as_octet_stream() {
        assert_eq!(normalize_file_type(""), UNKNOWN_FILE_TYPE);
        assert_eq!(
            normalize_file_type("Text/Plain; charset=UTF-8"),
            "text/plain"
        );
    }
}
