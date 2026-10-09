use actix_web::HttpRequest;
use uuid::Uuid;

use crate::errors::ServiceError;
use crate::metadata::MetadataClient;
use crate::models::{FileMetadata, FileShare, SharePermission};

/// What a caller wants to do with a file.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileAccess {
    /// Read metadata or download: owner, or any share on a non-trashed file.
    Read,
    /// Change content-level attributes: owner, or an `editor` share.
    Edit,
    /// Manage the file itself (delete, trash, move, share, versions): owner only.
    Owner,
}

/// The authenticated caller, from the `X-User-ID` header the api-gateway
/// derives from the validated JWT (and strips from client requests).
pub fn caller_id(req: &HttpRequest) -> Result<Uuid, ServiceError> {
    req.headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok())
        .ok_or_else(|| ServiceError::Unauthorized("missing or invalid X-User-ID".into()))
}

/// Pure access decision. `share` must be the caller's own share on this file.
pub fn is_permitted(
    file: &FileMetadata,
    caller: &Uuid,
    share: Option<&FileShare>,
    access: FileAccess,
) -> bool {
    if file.owner_id == *caller {
        return true;
    }
    let share = match share {
        Some(s) if s.file_id == file.id && s.shared_with == *caller => s,
        _ => return false,
    };
    if file.is_trashed {
        return false;
    }
    match access {
        FileAccess::Read => true,
        FileAccess::Edit => share.permission == SharePermission::Editor,
        FileAccess::Owner => false,
    }
}

/// Load a file and check the caller may perform `access` on it. Ids the
/// caller may not touch are reported as not found, so existence is not leaked.
pub async fn authorize_file(
    meta: &MetadataClient,
    file_id: &Uuid,
    caller: &Uuid,
    access: FileAccess,
) -> Result<FileMetadata, ServiceError> {
    let file = meta.get_file(file_id).await?;
    if file.owner_id == *caller {
        return Ok(file);
    }
    let share = if access == FileAccess::Owner {
        None
    } else {
        meta.find_existing_share(file_id, caller).await?
    };
    if is_permitted(&file, caller, share.as_ref(), access) {
        Ok(file)
    } else {
        tracing::warn!(file_id = %file_id, caller = %caller, ?access, "File access denied");
        Err(ServiceError::FileNotFound(file_id.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::test::TestRequest;
    use chrono::Utc;

    fn file(owner: Uuid, trashed: bool) -> FileMetadata {
        let id = Uuid::new_v4();
        FileMetadata {
            id,
            name: "a.txt".into(),
            mime_type: "text/plain".into(),
            size_bytes: 1,
            s3_key: format!("files/{owner}/{id}"),
            folder_id: None,
            owner_id: owner,
            version: 1,
            is_trashed: trashed,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        }
    }

    fn share(file: &FileMetadata, with: Uuid, permission: SharePermission) -> FileShare {
        FileShare {
            id: Uuid::new_v4(),
            file_id: file.id,
            shared_with: with,
            permission,
            shared_by: file.owner_id,
            created_at: Utc::now(),
        }
    }

    const ALL: [FileAccess; 3] = [FileAccess::Read, FileAccess::Edit, FileAccess::Owner];

    #[test]
    fn owner_has_every_access_even_when_trashed() {
        let owner = Uuid::new_v4();
        for trashed in [false, true] {
            let f = file(owner, trashed);
            for access in ALL {
                assert!(is_permitted(&f, &owner, None, access), "{access:?}");
            }
        }
    }

    #[test]
    fn stranger_without_share_is_denied_everything() {
        let f = file(Uuid::new_v4(), false);
        let stranger = Uuid::new_v4();
        for access in ALL {
            assert!(!is_permitted(&f, &stranger, None, access), "{access:?}");
        }
    }

    #[test]
    fn viewer_can_only_read() {
        let f = file(Uuid::new_v4(), false);
        let viewer = Uuid::new_v4();
        let s = share(&f, viewer, SharePermission::Viewer);
        assert!(is_permitted(&f, &viewer, Some(&s), FileAccess::Read));
        assert!(!is_permitted(&f, &viewer, Some(&s), FileAccess::Edit));
        assert!(!is_permitted(&f, &viewer, Some(&s), FileAccess::Owner));
    }

    #[test]
    fn editor_can_read_and_edit_but_not_manage() {
        let f = file(Uuid::new_v4(), false);
        let editor = Uuid::new_v4();
        let s = share(&f, editor, SharePermission::Editor);
        assert!(is_permitted(&f, &editor, Some(&s), FileAccess::Read));
        assert!(is_permitted(&f, &editor, Some(&s), FileAccess::Edit));
        assert!(!is_permitted(&f, &editor, Some(&s), FileAccess::Owner));
    }

    #[test]
    fn share_recipients_lose_access_to_trashed_files() {
        let f = file(Uuid::new_v4(), true);
        let editor = Uuid::new_v4();
        let s = share(&f, editor, SharePermission::Editor);
        for access in ALL {
            assert!(!is_permitted(&f, &editor, Some(&s), access), "{access:?}");
        }
    }

    #[test]
    fn share_for_another_user_or_file_does_not_grant_access() {
        let f = file(Uuid::new_v4(), false);
        let attacker = Uuid::new_v4();
        let someone_elses = share(&f, Uuid::new_v4(), SharePermission::Editor);
        assert!(!is_permitted(
            &f,
            &attacker,
            Some(&someone_elses),
            FileAccess::Read
        ));

        let other_file = file(f.owner_id, false);
        let other_files_share = share(&other_file, attacker, SharePermission::Editor);
        assert!(!is_permitted(
            &f,
            &attacker,
            Some(&other_files_share),
            FileAccess::Read
        ));
    }

    #[test]
    fn caller_id_requires_a_valid_x_user_id() {
        let id = Uuid::new_v4();
        let req = TestRequest::default()
            .insert_header(("X-User-ID", format!(" {id} ")))
            .to_http_request();
        assert_eq!(caller_id(&req).unwrap(), id);

        let missing = TestRequest::default().to_http_request();
        assert!(matches!(
            caller_id(&missing),
            Err(ServiceError::Unauthorized(_))
        ));

        let garbage = TestRequest::default()
            .insert_header(("X-User-ID", "not-a-uuid"))
            .to_http_request();
        assert!(matches!(
            caller_id(&garbage),
            Err(ServiceError::Unauthorized(_))
        ));
    }
}
