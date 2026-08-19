//! Fire-and-forget alert delivery to admin-service's Grafana-style webhook
//! ingest endpoint (`POST /api/v1/admin/alerts/ingest`). Each failed upload
//! produces one alert; the payload carries `dedup=false` so admin-service
//! opens a fresh incident (and Devin session) per alert instead of collapsing
//! repeats onto an existing open incident.

use serde_json::{json, Value};
use std::sync::OnceLock;

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
    file_name: &str,
    error: &str,
    reporter_email: Option<&str>,
) -> Value {
    let mut labels = json!({
        "alertname": "FileUploadFailed",
        "severity": "critical",
        "affected_service": "file-service",
        "dedup": "false",
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
                "summary": format!("File upload failed: {file_name}"),
                "description": format!(
                    "Upload of \"{file_name}\" failed in file-service: {error}"
                ),
            },
            "startsAt": chrono::Utc::now().to_rfc3339(),
        }],
    })
}

/// Spawn a background task that POSTs the upload-failure alert to
/// admin-service. Never blocks or alters the caller's response.
pub fn notify_upload_failure(
    config: &AlertConfig,
    file_name: &str,
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
    let payload = build_upload_failure_payload(file_name, error, reporter_email);
    let file_name = file_name.to_string();

    tokio::spawn(async move {
        let url = format!("{base_url}/api/v1/admin/alerts/ingest");
        let mut req = http_client().post(&url).json(&payload);
        if let Some(secret) = secret {
            req = req.header("X-Alert-Secret", secret);
        }
        match req.send().await {
            Ok(resp) if resp.status().is_success() => {
                tracing::info!(file_name = %file_name, "Upload-failure alert delivered to admin-service");
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

    #[test]
    fn payload_has_grafana_shape_with_dedup_disabled() {
        let payload = build_upload_failure_payload("report.pdf", "NoSuchBucket", None);
        assert_eq!(payload["status"], "firing");
        let alert = &payload["alerts"][0];
        assert_eq!(alert["status"], "firing");
        assert_eq!(alert["labels"]["alertname"], "FileUploadFailed");
        assert_eq!(alert["labels"]["severity"], "critical");
        assert_eq!(alert["labels"]["affected_service"], "file-service");
        assert_eq!(alert["labels"]["dedup"], "false");
        let summary = alert["annotations"]["summary"].as_str().unwrap();
        assert!(summary.contains("report.pdf"));
        let description = alert["annotations"]["description"].as_str().unwrap();
        assert!(description.contains("report.pdf"));
        assert!(description.contains("NoSuchBucket"));
        assert!(alert["startsAt"].is_string());
        assert!(alert["labels"].get("reporter_email").is_none());
    }

    #[test]
    fn payload_carries_reporter_email_when_present() {
        let payload =
            build_upload_failure_payload("report.pdf", "NoSuchBucket", Some("user@example.com"));
        let alert = &payload["alerts"][0];
        assert_eq!(alert["labels"]["reporter_email"], "user@example.com");
    }

    #[test]
    fn payload_omits_blank_reporter_email() {
        let payload = build_upload_failure_payload("report.pdf", "NoSuchBucket", Some("  "));
        let alert = &payload["alerts"][0];
        assert!(alert["labels"].get("reporter_email").is_none());
    }

    #[test]
    fn empty_admin_service_url_skips_without_spawning() {
        let config = AlertConfig {
            admin_service_url: "  ".into(),
            alert_webhook_secret: None,
        };
        // Must return without needing a tokio runtime (no task spawned).
        notify_upload_failure(&config, "a.txt", "boom", None);
    }

    #[actix_rt::test]
    async fn notify_with_unreachable_admin_service_does_not_error() {
        let config = AlertConfig {
            admin_service_url: "http://127.0.0.1:1".into(),
            alert_webhook_secret: Some("secret".into()),
        };
        notify_upload_failure(&config, "a.txt", "boom", Some("user@example.com"));
    }
}
