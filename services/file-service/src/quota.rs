//! Per-owner storage quota accounting.
//!
//! Usage counts every object an owner still has in S3, trashed or not:
//! trashing a file keeps its bytes, only a permanent delete gives them back.

use serde::Serialize;

use crate::errors::ServiceError;
use crate::models::FileMetadata;

#[derive(Debug, Clone, Copy, Serialize)]
pub struct QuotaStatus {
    pub used: u64,
    pub limit: u64,
    pub percent_used: f64,
}

/// Bytes charged to the owner's quota, trashed files included.
pub fn used_bytes(files: &[FileMetadata]) -> u64 {
    files.iter().map(|f| f.size_bytes).sum()
}

pub fn percent_used(used: u64, limit: u64) -> f64 {
    if limit == 0 {
        return 100.0;
    }
    (used as f64 / limit as f64) * 100.0
}

pub fn status(used: u64, limit: u64) -> QuotaStatus {
    QuotaStatus {
        used,
        limit,
        percent_used: percent_used(used, limit),
    }
}

/// An upload of `incoming` bytes fits when it lands exactly on the limit or below.
pub fn check_upload(used: u64, incoming: u64, limit: u64) -> Result<(), ServiceError> {
    if used.saturating_add(incoming) > limit {
        return Err(ServiceError::QuotaExceeded { used, limit });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::{check_upload, percent_used, used_bytes};
    use crate::errors::ServiceError;
    use crate::models::FileMetadata;
    use chrono::Utc;
    use uuid::Uuid;

    fn file(size_bytes: u64, is_trashed: bool) -> FileMetadata {
        let now = Utc::now();
        FileMetadata {
            id: Uuid::new_v4(),
            name: "f".into(),
            mime_type: "application/octet-stream".into(),
            size_bytes,
            s3_key: "files/x".into(),
            folder_id: None,
            owner_id: Uuid::new_v4(),
            version: 1,
            is_trashed,
            created_at: now,
            updated_at: now,
        }
    }

    #[test]
    fn upload_that_fits_is_accepted() {
        assert!(check_upload(400, 100, 1000).is_ok());
    }

    #[test]
    fn upload_landing_exactly_on_the_limit_is_accepted() {
        assert!(check_upload(900, 100, 1000).is_ok());
    }

    #[test]
    fn upload_one_byte_over_the_limit_is_rejected() {
        match check_upload(900, 101, 1000) {
            Err(ServiceError::QuotaExceeded { used, limit }) => {
                assert_eq!(used, 900);
                assert_eq!(limit, 1000);
            }
            other => panic!("expected QuotaExceeded, got {other:?}"),
        }
    }

    #[test]
    fn upload_is_rejected_when_already_over_the_limit() {
        assert!(check_upload(1200, 1, 1000).is_err());
    }

    #[test]
    fn oversized_upload_does_not_overflow() {
        assert!(check_upload(u64::MAX, u64::MAX, 1000).is_err());
    }

    #[test]
    fn trashed_files_still_count_towards_usage() {
        let files = vec![file(100, false), file(250, true)];
        assert_eq!(used_bytes(&files), 350);
    }

    #[test]
    fn percent_used_is_capped_at_nothing_and_handles_zero_limit() {
        assert_eq!(percent_used(0, 1000), 0.0);
        assert_eq!(percent_used(500, 1000), 50.0);
        assert_eq!(percent_used(2000, 1000), 200.0);
        assert_eq!(percent_used(1, 0), 100.0);
    }
}
