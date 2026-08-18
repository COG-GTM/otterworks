use uuid::Uuid;

use crate::errors::ServiceError;

/// Client for fetching a user's storage quota from auth-service.
#[derive(Clone)]
pub struct QuotaClient {
    http: reqwest::Client,
    auth_base_url: String,
}

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
struct UserLookupResponse {
    quota_bytes: u64,
}

impl QuotaClient {
    pub fn new(auth_base_url: &str) -> Self {
        Self {
            http: reqwest::Client::builder()
                .connect_timeout(std::time::Duration::from_secs(2))
                .timeout(std::time::Duration::from_secs(5))
                .build()
                .expect("failed to build quota HTTP client"),
            auth_base_url: auth_base_url.trim_end_matches('/').to_string(),
        }
    }

    /// Fetch the user's quota in bytes. Returns `None` when auth-service is
    /// unreachable or responds unexpectedly, so callers can fail open.
    pub async fn fetch_quota_bytes(&self, user_id: &Uuid, bearer: Option<&str>) -> Option<u64> {
        let url = format!("{}/api/v1/auth/users/by-id/{}", self.auth_base_url, user_id);
        let mut request = self.http.get(&url);
        if let Some(token) = bearer {
            request = request.header("Authorization", token);
        }

        match request.send().await {
            Ok(resp) if resp.status().is_success() => {
                match resp.json::<UserLookupResponse>().await {
                    Ok(body) => Some(body.quota_bytes),
                    Err(e) => {
                        tracing::warn!(user_id = %user_id, error = %e, "Failed to parse quota response");
                        None
                    }
                }
            }
            Ok(resp) => {
                tracing::warn!(user_id = %user_id, status = %resp.status(), "Quota lookup failed");
                None
            }
            Err(e) => {
                tracing::warn!(user_id = %user_id, error = %e, "Quota lookup unreachable");
                None
            }
        }
    }
}

/// Reject an upload when the user's current usage plus the incoming size
/// would exceed their quota.
pub fn check_quota(
    quota_bytes: u64,
    used_bytes: u64,
    incoming_bytes: u64,
) -> Result<(), ServiceError> {
    let over = used_bytes
        .checked_add(incoming_bytes)
        .is_none_or(|total| total > quota_bytes);
    if over {
        return Err(ServiceError::QuotaExceeded {
            quota_bytes,
            used_bytes,
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allows_upload_within_quota() {
        assert!(check_quota(100, 50, 50).is_ok());
        assert!(check_quota(100, 0, 100).is_ok());
    }

    #[test]
    fn rejects_upload_over_quota() {
        let err = check_quota(100, 50, 51).unwrap_err();
        match err {
            ServiceError::QuotaExceeded {
                quota_bytes,
                used_bytes,
            } => {
                assert_eq!(quota_bytes, 100);
                assert_eq!(used_bytes, 50);
            }
            other => panic!("expected QuotaExceeded, got {other:?}"),
        }
    }

    #[test]
    fn rejects_when_already_at_quota() {
        assert!(check_quota(100, 100, 1).is_err());
    }

    #[test]
    fn does_not_overflow_on_huge_incoming_size() {
        assert!(check_quota(u64::MAX, u64::MAX, u64::MAX).is_err());
    }

    #[test]
    fn quota_exceeded_serializes_structured_json() {
        use actix_web::ResponseError;
        let err = ServiceError::QuotaExceeded {
            quota_bytes: 100,
            used_bytes: 90,
        };
        let resp = err.error_response();
        assert_eq!(
            resp.status(),
            actix_web::http::StatusCode::PAYLOAD_TOO_LARGE
        );
        let body = actix_web::body::to_bytes(resp.into_body());
        let body = futures_util::FutureExt::now_or_never(body)
            .expect("body ready")
            .expect("body bytes");
        let json: serde_json::Value = serde_json::from_slice(&body).unwrap();
        assert_eq!(json["error"], "quota_exceeded");
        assert_eq!(json["quota_bytes"], 100);
        assert_eq!(json["used_bytes"], 90);
    }
}
