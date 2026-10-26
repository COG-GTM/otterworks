//! Per-object authorization for file and folder handlers.
//!
//! The api-gateway validates the JWT and forwards the caller as `X-User-ID`.
//! Every `/{file_id}` and `/{folder_id}` handler resolves the caller here and
//! checks the loaded record before reading or mutating it.

use actix_web::HttpRequest;
use uuid::Uuid;

use crate::errors::ServiceError;
use crate::metadata::MetadataClient;
use crate::models::{FileMetadata, FileShare, Folder};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FileAccess {
    /// Read the file: metadata, download, versions. Owner or share recipient.
    View,
    /// Mutate the file or its shares. Owner only.
    Manage,
}

pub fn caller_id(req: &HttpRequest) -> Result<Uuid, ServiceError> {
    req.headers()
        .get("X-User-ID")
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok())
        .ok_or_else(|| ServiceError::Unauthorized("missing or invalid X-User-ID header".into()))
}

/// Callers with no relationship to the file get 404 so ids cannot be probed;
/// share recipients asking for an owner-only action get 403.
pub fn check_file_access(
    file: &FileMetadata,
    caller: &Uuid,
    share: Option<&FileShare>,
    access: FileAccess,
) -> Result<(), ServiceError> {
    if file.owner_id == *caller {
        return Ok(());
    }
    let shared_with_caller = !file.is_trashed
        && share.map_or(false, |s| s.file_id == file.id && s.shared_with == *caller);
    match (shared_with_caller, access) {
        (true, FileAccess::View) => Ok(()),
        (true, FileAccess::Manage) => Err(ServiceError::Forbidden(
            "only the file owner can perform this action".into(),
        )),
        (false, _) => Err(ServiceError::FileNotFound(file.id.to_string())),
    }
}

pub fn check_folder_owner(folder: &Folder, caller: &Uuid) -> Result<(), ServiceError> {
    if folder.owner_id == *caller {
        Ok(())
    } else {
        Err(ServiceError::FolderNotFound(folder.id.to_string()))
    }
}

pub async fn authorize_file(
    meta: &MetadataClient,
    file_id: &Uuid,
    caller: &Uuid,
    access: FileAccess,
) -> Result<FileMetadata, ServiceError> {
    let file = meta.get_file(file_id).await?;
    if file.owner_id != *caller {
        let share = meta.find_existing_share(file_id, caller).await?;
        check_file_access(&file, caller, share.as_ref(), access)?;
    }
    Ok(file)
}

pub async fn authorize_folder(
    meta: &MetadataClient,
    folder_id: &Uuid,
    caller: &Uuid,
) -> Result<Folder, ServiceError> {
    let folder = meta.get_folder(folder_id).await?;
    check_folder_owner(&folder, caller)?;
    Ok(folder)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::models::SharePermission;
    use actix_web::test::TestRequest;
    use chrono::Utc;

    fn file(owner: Uuid) -> FileMetadata {
        FileMetadata {
            id: Uuid::new_v4(),
            name: "contract.pdf".into(),
            mime_type: "application/pdf".into(),
            size_bytes: 1,
            s3_key: "files/x".into(),
            folder_id: None,
            owner_id: owner,
            version: 1,
            is_trashed: false,
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

    fn status(r: Result<(), ServiceError>) -> u16 {
        match r {
            Ok(()) => 200,
            Err(ServiceError::Forbidden(_)) => 403,
            Err(ServiceError::FileNotFound(_)) | Err(ServiceError::FolderNotFound(_)) => 404,
            Err(e) => panic!("unexpected error {e}"),
        }
    }

    #[test]
    fn owner_can_view_and_manage() {
        let alice = Uuid::new_v4();
        let f = file(alice);
        assert_eq!(
            status(check_file_access(&f, &alice, None, FileAccess::View)),
            200
        );
        assert_eq!(
            status(check_file_access(&f, &alice, None, FileAccess::Manage)),
            200
        );
    }

    #[test]
    fn stranger_gets_not_found_for_everything() {
        let f = file(Uuid::new_v4());
        let mallory = Uuid::new_v4();
        assert_eq!(
            status(check_file_access(&f, &mallory, None, FileAccess::View)),
            404
        );
        assert_eq!(
            status(check_file_access(&f, &mallory, None, FileAccess::Manage)),
            404
        );
    }

    #[test]
    fn share_recipient_can_view_but_not_manage() {
        let f = file(Uuid::new_v4());
        let bob = Uuid::new_v4();
        for permission in [SharePermission::Viewer, SharePermission::Editor] {
            let s = share(&f, bob, permission);
            assert_eq!(
                status(check_file_access(&f, &bob, Some(&s), FileAccess::View)),
                200
            );
            assert_eq!(
                status(check_file_access(&f, &bob, Some(&s), FileAccess::Manage)),
                403
            );
        }
    }

    #[test]
    fn share_for_another_user_or_file_grants_nothing() {
        let f = file(Uuid::new_v4());
        let bob = Uuid::new_v4();
        let mallory = Uuid::new_v4();
        let bobs = share(&f, bob, SharePermission::Viewer);
        assert_eq!(
            status(check_file_access(
                &f,
                &mallory,
                Some(&bobs),
                FileAccess::View
            )),
            404
        );
        let other = file(f.owner_id);
        let wrong_file = share(&other, bob, SharePermission::Viewer);
        assert_eq!(
            status(check_file_access(
                &f,
                &bob,
                Some(&wrong_file),
                FileAccess::View
            )),
            404
        );
    }

    #[test]
    fn trashed_file_is_hidden_from_recipients() {
        let mut f = file(Uuid::new_v4());
        f.is_trashed = true;
        let bob = Uuid::new_v4();
        let s = share(&f, bob, SharePermission::Viewer);
        assert_eq!(
            status(check_file_access(&f, &bob, Some(&s), FileAccess::View)),
            404
        );
        assert_eq!(
            status(check_file_access(
                &f,
                &f.owner_id.clone(),
                None,
                FileAccess::View
            )),
            200
        );
    }

    #[test]
    fn folder_is_owner_only() {
        let alice = Uuid::new_v4();
        let folder = Folder {
            id: Uuid::new_v4(),
            name: "Contracts".into(),
            parent_id: None,
            owner_id: alice,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        };
        assert_eq!(status(check_folder_owner(&folder, &alice)), 200);
        assert_eq!(status(check_folder_owner(&folder, &Uuid::new_v4())), 404);
    }

    #[test]
    fn caller_id_requires_a_valid_header() {
        let id = Uuid::new_v4();
        let req = TestRequest::default()
            .insert_header(("X-User-ID", id.to_string()))
            .to_http_request();
        assert_eq!(caller_id(&req).unwrap(), id);
        let missing = TestRequest::default().to_http_request();
        assert!(matches!(
            caller_id(&missing),
            Err(ServiceError::Unauthorized(_))
        ));
        let bad = TestRequest::default()
            .insert_header(("X-User-ID", "not-a-uuid"))
            .to_http_request();
        assert!(matches!(
            caller_id(&bad),
            Err(ServiceError::Unauthorized(_))
        ));
    }
}
