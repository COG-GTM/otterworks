//! Object-level authorization for file and folder endpoints.
//!
//! The api-gateway strips any client-supplied `X-User-ID` and injects the
//! authenticated JWT subject, so that header is the caller identity. Every
//! object endpoint resolves the caller and checks it against the object's
//! `owner_id` (or a share grant) before touching metadata or storage.

use actix_web::HttpRequest;
use uuid::Uuid;

use crate::errors::ServiceError;
use crate::models::{FileMetadata, FileShare, Folder, SharePermission};

/// What the caller wants to do with a file.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileAction {
    /// Metadata, download URL, version history.
    Read,
    /// Rename.
    Edit,
    /// Delete, move, trash, restore, share, unshare.
    Manage,
}

/// Resolve the authenticated caller from the gateway-injected `X-User-ID`.
pub fn caller_id(req: &HttpRequest) -> Result<Uuid, ServiceError> {
    req.headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok())
        .ok_or_else(|| ServiceError::Unauthorized("missing or invalid X-User-ID".into()))
}

/// Decide whether `caller` may perform `action` on `file`.
///
/// `share` is the caller's own share grant on the file, if any. Callers with
/// no relationship to the file get `FileNotFound` so file ids cannot be probed;
/// share recipients asking for more than their grant allows get `Forbidden`.
pub fn authorize_file(
    file: &FileMetadata,
    caller: &Uuid,
    share: Option<&FileShare>,
    action: FileAction,
) -> Result<(), ServiceError> {
    if file.owner_id == *caller {
        return Ok(());
    }
    let share = match share {
        Some(s) if s.file_id == file.id && s.shared_with == *caller => s,
        _ => return Err(ServiceError::FileNotFound(file.id.to_string())),
    };
    let allowed = match action {
        FileAction::Read => !file.is_trashed,
        FileAction::Edit => !file.is_trashed && share.permission == SharePermission::Editor,
        FileAction::Manage => false,
    };
    if allowed {
        Ok(())
    } else if file.is_trashed {
        Err(ServiceError::FileNotFound(file.id.to_string()))
    } else {
        Err(ServiceError::Forbidden(
            "only the file owner may perform this action".into(),
        ))
    }
}

/// Folders are not shareable: only the owner may see or change one.
pub fn authorize_folder(folder: &Folder, caller: &Uuid) -> Result<(), ServiceError> {
    if folder.owner_id == *caller {
        Ok(())
    } else {
        Err(ServiceError::FolderNotFound(folder.id.to_string()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::test::TestRequest;
    use chrono::Utc;

    fn file(owner: Uuid, trashed: bool) -> FileMetadata {
        let now = Utc::now();
        FileMetadata {
            id: Uuid::new_v4(),
            name: "report.pdf".into(),
            mime_type: "application/pdf".into(),
            size_bytes: 10,
            s3_key: "files/x/y".into(),
            folder_id: None,
            owner_id: owner,
            version: 1,
            is_trashed: trashed,
            created_at: now,
            updated_at: now,
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

    fn status(err: ServiceError) -> u16 {
        use actix_web::ResponseError;
        err.error_response().status().as_u16()
    }

    const ALL: [FileAction; 3] = [FileAction::Read, FileAction::Edit, FileAction::Manage];

    #[test]
    fn caller_id_requires_valid_header() {
        let req = TestRequest::default().to_http_request();
        assert_eq!(status(caller_id(&req).unwrap_err()), 401);

        let req = TestRequest::default()
            .insert_header(("X-User-ID", "not-a-uuid"))
            .to_http_request();
        assert_eq!(status(caller_id(&req).unwrap_err()), 401);

        let id = Uuid::new_v4();
        let req = TestRequest::default()
            .insert_header(("X-User-ID", id.to_string()))
            .to_http_request();
        assert_eq!(caller_id(&req).unwrap(), id);
    }

    #[test]
    fn owner_may_do_everything() {
        let owner = Uuid::new_v4();
        for trashed in [false, true] {
            let f = file(owner, trashed);
            for action in ALL {
                assert!(authorize_file(&f, &owner, None, action).is_ok());
            }
        }
    }

    #[test]
    fn stranger_gets_not_found_for_every_action() {
        let f = file(Uuid::new_v4(), false);
        let attacker = Uuid::new_v4();
        for action in ALL {
            let err = authorize_file(&f, &attacker, None, action).unwrap_err();
            assert_eq!(status(err), 404, "{action:?}");
        }
    }

    #[test]
    fn share_grant_for_someone_else_is_ignored() {
        let f = file(Uuid::new_v4(), false);
        let attacker = Uuid::new_v4();
        let other = share(&f, Uuid::new_v4(), SharePermission::Editor);
        let err = authorize_file(&f, &attacker, Some(&other), FileAction::Read).unwrap_err();
        assert_eq!(status(err), 404);

        let mut wrong_file = share(&f, attacker, SharePermission::Editor);
        wrong_file.file_id = Uuid::new_v4();
        let err = authorize_file(&f, &attacker, Some(&wrong_file), FileAction::Read).unwrap_err();
        assert_eq!(status(err), 404);
    }

    #[test]
    fn viewer_may_only_read() {
        let f = file(Uuid::new_v4(), false);
        let viewer = Uuid::new_v4();
        let s = share(&f, viewer, SharePermission::Viewer);
        assert!(authorize_file(&f, &viewer, Some(&s), FileAction::Read).is_ok());
        assert_eq!(
            status(authorize_file(&f, &viewer, Some(&s), FileAction::Edit).unwrap_err()),
            403
        );
        assert_eq!(
            status(authorize_file(&f, &viewer, Some(&s), FileAction::Manage).unwrap_err()),
            403
        );
    }

    #[test]
    fn editor_may_read_and_edit_but_not_manage() {
        let f = file(Uuid::new_v4(), false);
        let editor = Uuid::new_v4();
        let s = share(&f, editor, SharePermission::Editor);
        assert!(authorize_file(&f, &editor, Some(&s), FileAction::Read).is_ok());
        assert!(authorize_file(&f, &editor, Some(&s), FileAction::Edit).is_ok());
        assert_eq!(
            status(authorize_file(&f, &editor, Some(&s), FileAction::Manage).unwrap_err()),
            403
        );
    }

    #[test]
    fn trashed_file_is_hidden_from_share_recipients() {
        let f = file(Uuid::new_v4(), true);
        let editor = Uuid::new_v4();
        let s = share(&f, editor, SharePermission::Editor);
        for action in ALL {
            let err = authorize_file(&f, &editor, Some(&s), action).unwrap_err();
            assert_eq!(status(err), 404, "{action:?}");
        }
    }

    #[test]
    fn folder_is_owner_only() {
        let owner = Uuid::new_v4();
        let now = Utc::now();
        let folder = Folder {
            id: Uuid::new_v4(),
            name: "Private".into(),
            parent_id: None,
            owner_id: owner,
            created_at: now,
            updated_at: now,
        };
        assert!(authorize_folder(&folder, &owner).is_ok());
        let err = authorize_folder(&folder, &Uuid::new_v4()).unwrap_err();
        assert_eq!(status(err), 404);
    }
}
