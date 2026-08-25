//! Fire-and-forget alert delivery to admin-service's Grafana-style webhook
//! ingest endpoint (`POST /api/v1/admin/alerts/ingest`). Each failed upload
//! produces one alert; the payload carries `dedup=false` so admin-service
//! opens a fresh incident (and Devin session) per alert instead of collapsing
//! repeats onto an existing open incident.
//!
//! Delivery is retried with exponential backoff: admin-service is a Rails app
//! that takes tens of seconds to accept connections after a deploy or a wake
//! from scale-to-zero, and an alert dropped in that window silently costs the
//! incident, the Slack notification and the Devin session.

use serde_json::{json, Value};
use std::sync::OnceLock;
use std::time::Duration;

/// Backoff between delivery attempts, spanning ~70s so an admin-service that
/// is still booting still receives the alert.
const RETRY_BACKOFF: &[Duration] = &[
    Duration::from_secs(1),
    Duration::from_secs(2),
    Duration::from_secs(4),
    Duration::from_secs(8),
    Duration::from_secs(16),
    Duration::from_secs(20),
    Duration::from_secs(20),
];

fn http_client() -> &'static reqwest::Client {
    static CLIENT: OnceLock<reqwest::Client> = OnceLock::new();
    CLIENT.get_or_init(|| {
        reqwest::Client::builder()
            // Generous, because ingest handles the incident, the Devin session
            // and the Slack notification synchronously, and a Puma that has
            // bound its socket but not yet booted its workers queues the
            // request instead of refusing it. Waiting it out delivers the
            // alert; timing out would drop it, since a timed-out request may
            // already have been processed and is therefore not retried.
            .timeout(std::time::Duration::from_secs(60))
            // Separate from the overall timeout so a stalled connect surfaces
            // as a connect error (retryable) rather than a response timeout.
            .connect_timeout(std::time::Duration::from_secs(3))
            // Alerts are rare, so a pooled socket is almost always one the
            // server has since reaped; connecting fresh avoids losing an alert
            // to a reset on a dead keep-alive connection.
            .pool_max_idle_per_host(0)
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

/// Whether a response status is worth another attempt. Server-side and
/// throttling failures are transient; other 4xx responses (bad payload, wrong
/// secret) would fail identically on every retry.
fn is_retryable(status: reqwest::StatusCode) -> bool {
    status.is_server_error()
        || status == reqwest::StatusCode::REQUEST_TIMEOUT
        || status == reqwest::StatusCode::TOO_MANY_REQUESTS
}

/// POST the alert, retrying on the given backoff schedule. Only failures that
/// prove admin-service never saw the alert are retried: a refused or timed-out
/// connection, or a transient rejection. A response timeout is not — it means
/// the request was sent and may have been handled; admin-service creates the
/// incident, the Devin session and the Slack notification synchronously before
/// responding, so a slow response may well have been processed, and re-sending
/// a `dedup=false` alert would duplicate all three.
///
/// Returns whether the alert was accepted.
async fn deliver_with_retry(
    kind: &str,
    url: &str,
    secret: Option<&str>,
    payload: &Value,
    backoff: &[Duration],
) -> bool {
    for attempt in 0..=backoff.len() {
        let mut req = http_client().post(url).json(payload);
        if let Some(secret) = secret {
            req = req.header("X-Alert-Secret", secret);
        }
        let retryable = match req.send().await {
            Ok(resp) if resp.status().is_success() => return true,
            Ok(resp) => {
                let status = resp.status();
                tracing::warn!(kind, %status, url = %url, attempt = attempt + 1, "Alert rejected by admin-service");
                is_retryable(status)
            }
            Err(e) => {
                let retryable = e.is_connect();
                tracing::warn!(kind, error = %e, url = %url, attempt = attempt + 1, retryable, "Failed to deliver alert");
                retryable
            }
        };
        match backoff.get(attempt) {
            Some(delay) if retryable => tokio::time::sleep(*delay).await,
            _ => break,
        }
    }
    false
}

pub fn build_share_notification_failure_payload(
    file_name: &str,
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
                "summary": format!("Share notification failed: {file_name}"),
                "description": format!(
                    "Publishing the file_shared notification event for \"{file_name}\" \
                     failed in file-service: {error}. {}",
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
    file_name: &str,
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
        file_name,
        error,
        reporter_email,
        dedup,
        share_recorded,
    );
    let file_name = file_name.to_string();

    tokio::spawn(async move {
        let url = format!("{base_url}/api/v1/admin/alerts/ingest");
        let delivered = deliver_with_retry(
            "share-notification-failure",
            &url,
            secret.as_deref(),
            &payload,
            RETRY_BACKOFF,
        )
        .await;
        if delivered {
            tracing::info!(file_name = %file_name, "Share-notification-failure alert delivered to admin-service");
        } else {
            tracing::error!(file_name = %file_name, url = %url, "Giving up on share-notification-failure alert; no incident will be created");
        }
    });
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
        if deliver_with_retry(
            "upload-failure",
            &url,
            secret.as_deref(),
            &payload,
            RETRY_BACKOFF,
        )
        .await
        {
            tracing::info!(file_name = %file_name, "Upload-failure alert delivered to admin-service");
        } else {
            tracing::error!(file_name = %file_name, url = %url, "Giving up on upload-failure alert; no incident will be created");
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

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

    #[test]
    fn share_notification_payload_has_grafana_shape() {
        let payload = build_share_notification_failure_payload(
            "report.pdf",
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
        let summary = alert["annotations"]["summary"].as_str().unwrap();
        assert!(summary.contains("report.pdf"));
        let description = alert["annotations"]["description"].as_str().unwrap();
        assert!(description.contains("file_shared"));
        assert!(description.contains("NotFound"));
        assert!(alert["startsAt"].is_string());
    }

    #[test]
    fn share_notification_payload_omits_blank_reporter_email() {
        let payload = build_share_notification_failure_payload("a.txt", "boom", None, false, true);
        let alert = &payload["alerts"][0];
        assert!(alert["labels"].get("reporter_email").is_none());
    }

    #[test]
    fn share_notification_payload_dedups_when_not_forced() {
        let payload = build_share_notification_failure_payload("a.txt", "boom", None, true, true);
        assert_eq!(payload["alerts"][0]["labels"]["dedup"], "true");
    }

    #[actix_rt::test]
    async fn notify_with_unreachable_admin_service_does_not_error() {
        let config = AlertConfig {
            admin_service_url: "http://127.0.0.1:1".into(),
            alert_webhook_secret: Some("secret".into()),
        };
        notify_upload_failure(&config, "a.txt", "boom", Some("user@example.com"));
    }

    #[test]
    fn only_transient_statuses_are_retried() {
        use reqwest::StatusCode;
        assert!(is_retryable(StatusCode::SERVICE_UNAVAILABLE));
        assert!(is_retryable(StatusCode::BAD_GATEWAY));
        assert!(is_retryable(StatusCode::TOO_MANY_REQUESTS));
        assert!(!is_retryable(StatusCode::UNAUTHORIZED));
        assert!(!is_retryable(StatusCode::BAD_REQUEST));
    }

    /// Serves one canned response per connection, in order, then hangs up.
    /// Returns the bound address and a counter of served requests.
    async fn stub_server(statuses: Vec<u16>) -> (String, std::sync::Arc<AtomicUsize>) {
        use tokio::io::{AsyncReadExt, AsyncWriteExt};

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        let served = std::sync::Arc::new(AtomicUsize::new(0));
        let counter = served.clone();

        tokio::spawn(async move {
            for status in statuses {
                let Ok((mut socket, _)) = listener.accept().await else {
                    return;
                };
                let mut buf = [0u8; 4096];
                let _ = socket.read(&mut buf).await;
                counter.fetch_add(1, Ordering::SeqCst);
                let body = "{}";
                let response = format!(
                    "HTTP/1.1 {status} X\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                );
                let _ = socket.write_all(response.as_bytes()).await;
                let _ = socket.shutdown().await;
            }
        });

        (format!("http://{addr}/ingest"), served)
    }

    #[actix_rt::test]
    async fn retries_until_admin_service_accepts_the_alert() {
        let (url, served) = stub_server(vec![503, 502, 200]).await;
        let payload = build_upload_failure_payload("a.txt", "boom", None);
        let backoff = [Duration::ZERO, Duration::ZERO, Duration::ZERO];

        assert!(deliver_with_retry("upload-failure", &url, None, &payload, &backoff).await);
        assert_eq!(served.load(Ordering::SeqCst), 3);
    }

    #[actix_rt::test]
    async fn gives_up_immediately_on_a_permanent_rejection() {
        let (url, served) = stub_server(vec![401, 200]).await;
        let payload = build_upload_failure_payload("a.txt", "boom", None);
        let backoff = [Duration::ZERO, Duration::ZERO];

        assert!(
            !deliver_with_retry("upload-failure", &url, Some("wrong"), &payload, &backoff).await
        );
        assert_eq!(served.load(Ordering::SeqCst), 1);
    }

    #[actix_rt::test]
    async fn gives_up_after_exhausting_the_backoff_schedule() {
        let (url, served) = stub_server(vec![503, 503]).await;
        let payload = build_upload_failure_payload("a.txt", "boom", None);
        let backoff = [Duration::ZERO];

        assert!(!deliver_with_retry("upload-failure", &url, None, &payload, &backoff).await);
        assert_eq!(served.load(Ordering::SeqCst), 2);
    }

    #[actix_rt::test]
    async fn retries_while_admin_service_refuses_connections() {
        // Bind then drop the listener so the port is closed but routable: the
        // admin-service-still-booting case.
        let closed_port = {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            listener.local_addr().unwrap().port()
        };
        let url = format!("http://127.0.0.1:{closed_port}/ingest");

        // A refusal classifies as retryable, so the loop keeps trying instead
        // of dropping the alert on the first attempt.
        let err = http_client().post(&url).send().await.unwrap_err();
        assert!(err.is_connect(), "expected a connect error, got {err}");
        assert!(!err.is_timeout());

        let payload = build_upload_failure_payload("a.txt", "boom", None);
        let backoff = [Duration::ZERO, Duration::ZERO];
        assert!(!deliver_with_retry("upload-failure", &url, None, &payload, &backoff).await);
    }

    #[actix_rt::test]
    async fn a_stalled_connect_is_a_connect_error_not_a_response_timeout() {
        // TEST-NET-1 (RFC 5737): no host answers, so the connect phase times
        // out. It must classify as retryable, unlike a response timeout.
        let err = http_client()
            .post("http://192.0.2.1:8089/ingest")
            .send()
            .await
            .unwrap_err();
        assert!(err.is_connect(), "expected a connect error, got {err}");
    }
}
