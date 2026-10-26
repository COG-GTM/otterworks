//! Caller identity for file-service requests.
//!
//! The api-gateway strips any client-supplied `X-User-ID` and re-injects the
//! subject of the verified JWT, so that header is the only identity source.
//! Query-string and body `owner_id` values are never trusted as identity.
//! The only exception is the search-service reindex crawl, which presents
//! `X-Internal-Token` (matching `FILE_SERVICE_INTERNAL_TOKEN`) to list files
//! across owners; with no token configured that path is disabled.

use actix_web::http::header::HeaderMap;
use uuid::Uuid;

use crate::errors::ServiceError;

pub const USER_ID_HEADER: &str = "X-User-ID";
pub const INTERNAL_TOKEN_HEADER: &str = "X-Internal-Token";

/// The authenticated caller, or 401 when the gateway identity header is
/// missing or not a UUID.
pub fn caller_id(headers: &HeaderMap) -> Result<Uuid, ServiceError> {
    headers
        .get(USER_ID_HEADER)
        .and_then(|v| v.to_str().ok())
        .and_then(|s| s.trim().parse::<Uuid>().ok())
        .ok_or_else(|| ServiceError::Unauthorized(format!("missing {USER_ID_HEADER} header")))
}

/// The owner a caller may act as: always the caller. A client-supplied
/// `owner_id` naming anyone else is rejected rather than silently ignored.
pub fn owner_for_caller(
    headers: &HeaderMap,
    requested: Option<Uuid>,
) -> Result<Uuid, ServiceError> {
    let caller = caller_id(headers)?;
    match requested {
        Some(owner) if owner != caller => Err(ServiceError::Forbidden(
            "owner_id must match the authenticated caller".into(),
        )),
        _ => Ok(caller),
    }
}

/// Owner scope for listing files. Users are pinned to themselves; an
/// internal caller holding the configured token may list any owner (or all
/// owners when `requested` is `None`).
pub fn listing_owner(
    headers: &HeaderMap,
    requested: Option<Uuid>,
    internal_token: Option<&str>,
) -> Result<Option<Uuid>, ServiceError> {
    if headers.contains_key(USER_ID_HEADER) {
        return owner_for_caller(headers, requested).map(Some);
    }
    if has_internal_token(headers, internal_token) {
        return Ok(requested);
    }
    Err(ServiceError::Unauthorized(format!(
        "missing {USER_ID_HEADER} header"
    )))
}

pub fn has_internal_token(headers: &HeaderMap, expected: Option<&str>) -> bool {
    let Some(expected) = expected.filter(|t| !t.is_empty()) else {
        return false;
    };
    headers
        .get(INTERNAL_TOKEN_HEADER)
        .and_then(|v| v.to_str().ok())
        .is_some_and(|presented| constant_time_eq(presented.as_bytes(), expected.as_bytes()))
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

#[cfg(test)]
mod tests {
    use super::*;
    use actix_web::http::header::{HeaderName, HeaderValue};

    const ALICE: &str = "11111111-1111-1111-1111-111111111111";
    const MALLORY: &str = "22222222-2222-2222-2222-222222222222";

    fn headers(pairs: &[(&'static str, &str)]) -> HeaderMap {
        let mut map = HeaderMap::new();
        for (name, value) in pairs {
            map.insert(
                HeaderName::from_static(name),
                HeaderValue::from_str(value).unwrap(),
            );
        }
        map
    }

    fn uuid(s: &str) -> Uuid {
        s.parse().unwrap()
    }

    #[test]
    fn caller_id_requires_header() {
        assert!(matches!(
            caller_id(&HeaderMap::new()),
            Err(ServiceError::Unauthorized(_))
        ));
        assert!(matches!(
            caller_id(&headers(&[("x-user-id", "not-a-uuid")])),
            Err(ServiceError::Unauthorized(_))
        ));
        assert_eq!(
            caller_id(&headers(&[("x-user-id", ALICE)])).unwrap(),
            uuid(ALICE)
        );
    }

    #[test]
    fn requested_owner_is_never_identity() {
        assert!(matches!(
            owner_for_caller(&HeaderMap::new(), Some(uuid(ALICE))),
            Err(ServiceError::Unauthorized(_))
        ));
        assert!(matches!(
            owner_for_caller(&headers(&[("x-user-id", MALLORY)]), Some(uuid(ALICE))),
            Err(ServiceError::Forbidden(_))
        ));
        let alice = headers(&[("x-user-id", ALICE)]);
        assert_eq!(owner_for_caller(&alice, None).unwrap(), uuid(ALICE));
        assert_eq!(
            owner_for_caller(&alice, Some(uuid(ALICE))).unwrap(),
            uuid(ALICE)
        );
    }

    #[test]
    fn listing_owner_without_identity_is_unauthorized() {
        assert!(matches!(
            listing_owner(&HeaderMap::new(), Some(uuid(ALICE)), None),
            Err(ServiceError::Unauthorized(_))
        ));
        assert!(matches!(
            listing_owner(&HeaderMap::new(), None, Some("s3cret")),
            Err(ServiceError::Unauthorized(_))
        ));
        let wrong = headers(&[("x-internal-token", "guess")]);
        assert!(matches!(
            listing_owner(&wrong, Some(uuid(ALICE)), Some("s3cret")),
            Err(ServiceError::Unauthorized(_))
        ));
    }

    #[test]
    fn listing_owner_scopes_users_and_internal_callers() {
        assert_eq!(
            listing_owner(&headers(&[("x-user-id", ALICE)]), None, None).unwrap(),
            Some(uuid(ALICE))
        );
        let internal = headers(&[("x-internal-token", "s3cret")]);
        assert_eq!(
            listing_owner(&internal, None, Some("s3cret")).unwrap(),
            None
        );
        assert_eq!(
            listing_owner(&internal, Some(uuid(ALICE)), Some("s3cret")).unwrap(),
            Some(uuid(ALICE))
        );
        assert!(!has_internal_token(&internal, Some("")));
        assert!(!has_internal_token(&internal, None));
    }
}
