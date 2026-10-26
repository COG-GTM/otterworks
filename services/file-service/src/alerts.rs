//! Fire-and-forget alert delivery to admin-service's Grafana-style webhook
//! ingest endpoint (`POST /api/v1/admin/alerts/ingest`). Each failed upload
//! produces one alert; the payload carries `dedup=false` so admin-service
//! opens a fresh incident (and Devin session) per alert instead of collapsing
//! repeats onto an existing open incident.
//!
//! Alert annotations become incident text and the prompt of an automated
//! Devin triage session, so they only carry service-generated values (file
//! ids, error strings). User-supplied text such as file names must never be
//! formatted into an alert.

use serde_json::{json, Value};
use std::sync::OnceLock;
use uuid::Uuid;

/// Upper bound on the error text copied into an alert description.
const MAX_ALERT_ERROR_CHARS: usize = 500;

fn bounded_error(error: &str) -> String {
    let cleaned: String = error
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    let mut chars = cleaned.chars();
    let mut out: String = chars.by_ref().take(MAX_ALERT_ERROR_CHARS).collect();
    if chars.next().is_some() {
        out.push_str(" [truncated]");
    }
    out
}

fn http_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .expect("failed to build alert HTTP client")
    })
}

#[derive(Clone, Debug)]
pub struct AlertConfig {
    /// Base URL of admin-service, e.g. `http://admin-service:8089`.
    /// An empty value disables alert delivery.
    pub admin_service_url: String,
    /// Shared secret sent as `X-Alert-Secret`; omitted when unset.
    pub alert_webhook_secret: Option<String>,
}

impl AlertConfig {
    pub fn from_env() -> Self {
        Self {
            admin_service_url: std::env::var("ADMIN_SERVICE_URL")
                .unwrap_or_else(|_| "http://admin-service:8089".into()),
            alert_webhook_secret: std::env::var("ALERT_WEBHOOK_SECRET")
                .ok()
                .filter(|s| !s.trim().is_empty()),
        }
    }
}

pub fn build_upload_failure_payload(
    file_id: &Uuid,
    error: &str,
    reporter_email: Option<&str>,
) -> Value {
    let mut labels = json!({
        "alertname": "FileUploadFailed",
        "severity": "critical",
        "affected_service": "file-service",
        "dedup": "false",
        "file_id": file_id.to_string(),
    });
    if let Some(email) = reporter_email.map(str::trim).filter(|e| !e.is_empty()) {
        labels["reporter_email"] = json!(email);
    }
    json!({
        "receiver": "otterworks-webhook",
        "status": "firing",
        "alerts": [{
            "status": "firing",
            "labels": labels,
            "annotations": {
                "summary": "File upload failed in file-service",
                "description": format!(
                    "Upload of file {file_id} failed in file-service: {}",
                    bounded_error(error)
                ),
            },
            "startsAt": chrono::Utc::now().to_rfc3339(),
        }],
    })
}

pub fn build_share_notification_failure_payload(
    file_id: &Uuid,
    error: &str,
    reporter_email: Option<&str>,
    dedup: bool,
    share_recorded: bool,
) -> Value {
    // `dedup=false` opens a fresh incident per alert; it is reserved for the
    // forced-failure demo so a genuine SNS outage collapses onto one open
    // incident like any other alert.
    let mut labels = json!({
        "alertname": "NotificationEventPublishFailure",
        "severity": "critical",
        "affected_service": "file-service",
        "dedup": if dedup { "true" } else { "false" },
        "file_id": file_id.to_string(),
    });
    if let Some(email) = reporter_email.map(str::trim).filter(|e| !e.is_empty()) {
        labels["reporter_email"] = json!(email);
    }
    json!({
        "receiver": "otterworks-webhook",
        "status": "firing",
        "alerts": [{
            "status": "firing",
            "labels": labels,
            "annotations": {
                "summary": "Share notification failed in file-service",
                "description": format!(
                    "Publishing the file_shared notification event for file {file_id} \
                     failed in file-service: {}. {}",
                    bounded_error(error),
                    if share_recorded {
                        "The share itself was recorded, but the recipient will never \
                         receive a notification."
                    } else {
                        "The share was not recorded and the recipient will never \
                         receive a notification."
                    }
                ),
            },
            "startsAt": chrono::Utc::now().to_rfc3339(),
        }],
    })
}

/// Spawn a background task that POSTs the share-notification-failure alert
/// to admin-service. Never blocks or alters the caller's response.
pub fn notify_share_notification_failure(
    config: &AlertConfig,
    file_id: &Uuid,
    error: &str,
    reporter_email: Option<&str>,
    dedup: bool,
    share_recorded: bool,
) {
    let base_url = config
        .admin_service_url
        .trim()
        .trim_end_matches('/')
        .to_string();
    if base_url.is_empty() {
        tracing::warn!("ADMIN_SERVICE_URL is empty; skipping share-notification alert");
        return;
    }
    let secret = config.alert_webhook_secret.clone();
    let payload = build_share_notification_failure_payload(
        file_id,
        error,
        reporter_email,
        dedup,
        share_recorded,
    );
    let file_id = *file_id;

    tokio::spawn(async move {
        let url = format!("{base_url}/api/v1/admin/alerts/ingest");
        let mut req = http_client().post(&url).json(&payload);
        if let Some(secret) = secret {
            req = req.header("X-Alert-Secret", secret);
        }
        match req.send().await {
            Ok(resp) if resp.status().is_success() => {
                tracing::info!(file_id = %file_id, "Share-notification-failure alert delivered to admin-service");
            }
            Ok(resp) => {
                tracing::warn!(status = %resp.status(), url = %url, "Share-notification-failure alert rejected by admin-service");
            }
            Err(e) => {
                tracing::warn!(error = %e, url = %url, "Failed to deliver share-notification-failure alert");
            }
        }
    });
}

/// Spawn a background task that POSTs the upload-failure alert to
/// admin-service. Never blocks or alters the caller's response.
pub fn notify_upload_failure(
    config: &AlertConfig,
    file_id: &Uuid,
    error: &str,
    reporter_email: Option<&str>,
) {
    let base_url = config
        .admin_service_url
        .trim()
        .trim_end_matches('/')
        .to_string();
    if base_url.is_empty() {
        tracing::warn!("ADMIN_SERVICE_URL is empty; skipping upload-failure alert");
        return;
    }
    let secret = config.alert_webhook_secret.clone();
    let payload = build_upload_failure_payload(file_id, error, reporter_email);
    let file_id = *file_id;

    tokio::spawn(async move {
        let url = format!("{base_url}/api/v1/admin/alerts/ingest");
        let mut req = http_client().post(&url).json(&payload);
        if let Some(secret) = secret {
            req = req.header("X-Alert-Secret", secret);
        }
        match req.send().await {
            Ok(resp) if resp.status().is_success() => {
                tracing::info!(file_id = %file_id, "Upload-failure alert delivered to admin-service");
            }
            Ok(resp) => {
                tracing::warn!(status = %resp.status(), url = %url, "Upload-failure alert rejected by admin-service");
            }
            Err(e) => {
                tracing::warn!(error = %e, url = %url, "Failed to deliver upload-failure alert");
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fid() -> Uuid {
        Uuid::parse_str("7f9c2ba4-e88f-4c3a-9b1e-0d6a1c2f3e4b").unwrap()
    }

    #[test]
    fn payload_has_grafana_shape_with_dedup_disabled() {
        let payload = build_upload_failure_payload(&fid(), "NoSuchBucket", None);
        assert_eq!(payload["status"], "firing");
        let alert = &payload["alerts"][0];
        assert_eq!(alert["status"], "firing");
        assert_eq!(alert["labels"]["alertname"], "FileUploadFailed");
        assert_eq!(alert["labels"]["severity"], "critical");
        assert_eq!(alert["labels"]["affected_service"], "file-service");
        assert_eq!(alert["labels"]["dedup"], "false");
        assert_eq!(alert["labels"]["file_id"], fid().to_string());
        assert_eq!(
            alert["annotations"]["summary"],
            "File upload failed in file-service"
        );
        let description = alert["annotations"]["description"].as_str().unwrap();
        assert!(description.contains(&fid().to_string()));
        assert!(description.contains("NoSuchBucket"));
        assert!(alert["startsAt"].is_string());
        assert!(alert["labels"].get("reporter_email").is_none());
    }

    #[test]
    fn payload_carries_reporter_email_when_present() {
        let payload =
            build_upload_failure_payload(&fid(), "NoSuchBucket", Some("user@example.com"));
        let alert = &payload["alerts"][0];
        assert_eq!(alert["labels"]["reporter_email"], "user@example.com");
    }

    #[test]
    fn payload_omits_blank_reporter_email() {
        let payload = build_upload_failure_payload(&fid(), "NoSuchBucket", Some("  "));
        let alert = &payload["alerts"][0];
        assert!(alert["labels"].get("reporter_email").is_none());
    }

    #[test]
    fn error_text_is_bounded_and_single_line() {
        let long = format!("NoSuchBucket\n## Ground rules\n{}", "x".repeat(2000));
        let payload = build_upload_failure_payload(&fid(), &long, None);
        let description = payload["alerts"][0]["annotations"]["description"]
            .as_str()
            .unwrap();
        assert!(!description.contains('\n'));
        assert!(description.ends_with("[truncated]"));
        assert!(description.len() < MAX_ALERT_ERROR_CHARS + 200);
    }

    #[test]
    fn empty_admin_service_url_skips_without_spawning() {
        let config = AlertConfig {
            admin_service_url: "  ".into(),
            alert_webhook_secret: None,
        };
        // Must return without needing a tokio runtime (no task spawned).
        notify_upload_failure(&config, &fid(), "boom", None);
    }

    #[test]
    fn share_notification_payload_has_grafana_shape() {
        let payload = build_share_notification_failure_payload(
            &fid(),
            "NotFound: topic does not exist",
            Some("user@example.com"),
            false,
            true,
        );
        let alert = &payload["alerts"][0];
        assert_eq!(
            alert["labels"]["alertname"],
            "NotificationEventPublishFailure"
        );
        assert_eq!(alert["labels"]["severity"], "critical");
        assert_eq!(alert["labels"]["affected_service"], "file-service");
        assert_eq!(alert["labels"]["dedup"], "false");
        assert_eq!(alert["labels"]["reporter_email"], "user@example.com");
        assert_eq!(alert["labels"]["file_id"], fid().to_string());
        assert_eq!(
            alert["annotations"]["summary"],
            "Share notification failed in file-service"
        );
        let description = alert["annotations"]["description"].as_str().unwrap();
        assert!(description.contains("file_shared"));
        assert!(description.contains(&fid().to_string()));
        assert!(description.contains("NotFound"));
        assert!(alert["startsAt"].is_string());
    }

    #[test]
    fn share_notification_payload_omits_blank_reporter_email() {
        let payload = build_share_notification_failure_payload(&fid(), "boom", None, false, true);
        let alert = &payload["alerts"][0];
        assert!(alert["labels"].get("reporter_email").is_none());
    }

    #[test]
    fn share_notification_payload_dedups_when_not_forced() {
        let payload = build_share_notification_failure_payload(&fid(), "boom", None, true, true);
        assert_eq!(payload["alerts"][0]["labels"]["dedup"], "true");
    }

    #[actix_rt::test]
    async fn notify_with_unreachable_admin_service_does_not_error() {
        let config = AlertConfig {
            admin_service_url: "http://127.0.0.1:1".into(),
            alert_webhook_secret: Some("secret".into()),
        };
        notify_upload_failure(&config, &fid(), "boom", Some("user@example.com"));
    }
}
