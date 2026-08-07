//! Direct Devin API client.
//!
//! When a file upload to S3 fails, file-service opens a Devin session itself
//! instead of routing the incident through admin-service. This is a deliberate
//! shortcut: no `Incident` row, no audit entry and no session-status refresh —
//! those remain admin-service concerns.
//!
//! With `DEVIN_API_KEY` / `DEVIN_ORG_ID` unset the whole module is a no-op.

use std::sync::OnceLock;
use std::time::Duration;

use serde::Deserialize;

const API_HOST: &str = "https://api.devin.ai";
const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

static HTTP_CLIENT: OnceLock<Option<reqwest::Client>> = OnceLock::new();

/// An upload failure worth investigating.
#[derive(Clone, Debug)]
pub struct UploadFailureIncident {
    pub bucket: String,
    pub s3_key: String,
    pub error: String,
    pub owner_id: Option<String>,
    pub file_id: Option<String>,
}

/// The session Devin created for an incident.
#[derive(Clone, Debug, Deserialize)]
pub struct DevinSession {
    pub session_id: Option<String>,
    pub url: Option<String>,
}

/// Resolve the API credentials, warning when the client is disabled.
fn resolve_credentials(
    api_key: Option<String>,
    org_id: Option<String>,
) -> Option<(String, String)> {
    match (api_key, org_id) {
        (Some(key), Some(org)) if !key.is_empty() && !org.is_empty() => Some((key, org)),
        _ => {
            tracing::warn!(
                "DEVIN_API_KEY or DEVIN_ORG_ID not set, skipping Devin session creation"
            );
            None
        }
    }
}

fn credentials_from_env() -> Option<(String, String)> {
    resolve_credentials(
        std::env::var("DEVIN_API_KEY").ok(),
        std::env::var("DEVIN_ORG_ID").ok(),
    )
}

/// Create a Devin session for an upload failure. Returns `None` when the client
/// is unconfigured or the API call fails; failures are logged, never propagated.
pub async fn create_session(incident: &UploadFailureIncident) -> Option<DevinSession> {
    let (api_key, org_id) = credentials_from_env()?;
    post_session(API_HOST, &api_key, &org_id, incident).await
}

/// The shared connection pool, built once. `None` if the TLS backend failed to
/// initialise, in which case the client stays disabled for the process's life.
fn http_client() -> Option<&'static reqwest::Client> {
    HTTP_CLIENT
        .get_or_init(|| {
            reqwest::Client::builder()
                .connect_timeout(CONNECT_TIMEOUT)
                .timeout(REQUEST_TIMEOUT)
                .build()
                .inspect_err(|e| {
                    tracing::error!(error = %e, "Devin session creation failed: HTTP client build error");
                })
                .ok()
        })
        .as_ref()
}

async fn post_session(
    api_host: &str,
    api_key: &str,
    org_id: &str,
    incident: &UploadFailureIncident,
) -> Option<DevinSession> {
    let client = http_client()?;
    let url = format!("{api_host}/v3/organizations/{org_id}/sessions");
    let response = match client
        .post(&url)
        .bearer_auth(api_key)
        .json(&serde_json::json!({ "prompt": build_prompt(incident) }))
        .send()
        .await
    {
        Ok(response) => response,
        Err(e) => {
            tracing::error!(error = %e, "Devin session creation failed");
            return None;
        }
    };

    let status = response.status();
    let body = response.text().await.unwrap_or_default();

    if !status.is_success() {
        tracing::error!(status = %status.as_u16(), body = %body, "Devin API returned an error");
        return None;
    }

    match serde_json::from_str::<DevinSession>(&body) {
        Ok(session) => {
            tracing::info!(
                session_id = session.session_id.as_deref().unwrap_or("unknown"),
                url = session.url.as_deref().unwrap_or("unknown"),
                "Created Devin session for upload failure"
            );
            Some(session)
        }
        Err(e) => {
            tracing::error!(error = %e, "Devin session creation failed: unparseable response");
            None
        }
    }
}

fn build_prompt(incident: &UploadFailureIncident) -> String {
    let owner = incident.owner_id.as_deref().unwrap_or("Unknown");
    let file_id = incident.file_id.as_deref().unwrap_or("Unknown");
    let description = format!(
        "A file upload failed while writing the object to S3. \
         Bucket: {bucket}. S3 key: {key}. Owner: {owner}. File id: {file_id}. \
         Error: {error}",
        bucket = incident.bucket,
        key = incident.s3_key,
        error = incident.error,
    );

    format!(
        "You are investigating an incident in the OtterWorks platform, a collaborative file storage and document editing system (similar to Google Drive + Google Docs) built as a polyglot microservices architecture.

## Incident Details
- **Title**: File upload to S3 failed in file-service
- **Severity**: high
- **Affected Service**: file-service
- **Description**: {description}

## OtterWorks Architecture
The platform has 11 microservices:
- API Gateway (Go/Chi, port 8080) - routing, rate limiting, JWT validation
- Auth Service (Java/Spring Boot, port 8081) - authentication, RBAC
- File Service (Rust/Actix-Web, port 8082) - file upload/download, S3
- Document Service (Python/FastAPI, port 8083) - document CRUD, versioning
- Collaboration Service (Node.js/Socket.io, port 8084) - real-time editing
- Notification Service (Kotlin/Ktor, port 8086) - event-driven notifications
- Search Service (Python/Flask, port 8087) - MeiliSearch full-text search
- Analytics Service (Scala/Akka HTTP, port 8088) - usage analytics
- Admin Service (Ruby/Rails, port 8089) - admin operations
- Audit Service (C#/ASP.NET, port 8090) - audit trail
- Report Service (Java/Spring Boot, port 8091) - report generation

Services communicate via REST (through API Gateway) and async SNS/SQS events.

## Your Task
Investigate this incident, identify the root cause, and implement a fix. Start by examining the affected service's code and logs. Look for recent changes, error patterns, and configuration issues.
"
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::SocketAddr;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    use tokio::net::TcpListener;

    /// Minimal one-shot HTTP stub standing in for the Devin API.
    async fn stub_api(status_line: &'static str, body: &'static str) -> SocketAddr {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let addr = listener.local_addr().unwrap();
        tokio::spawn(async move {
            let (mut socket, _) = listener.accept().await.unwrap();
            // Drain the full request (headers + Content-Length body) before
            // responding, so the client never sees an RST from unread data.
            let mut request = Vec::new();
            let mut buf = [0u8; 4096];
            loop {
                let n = socket.read(&mut buf).await.unwrap_or(0);
                if n == 0 {
                    break;
                }
                request.extend_from_slice(&buf[..n]);
                if let Some(headers_end) = request
                    .windows(4)
                    .position(|window| window == b"\r\n\r\n")
                    .map(|pos| pos + 4)
                {
                    let headers = String::from_utf8_lossy(&request[..headers_end]);
                    let content_length = headers
                        .lines()
                        .filter_map(|line| line.split_once(':'))
                        .find(|(name, _)| name.eq_ignore_ascii_case("content-length"))
                        .and_then(|(_, value)| value.trim().parse::<usize>().ok())
                        .unwrap_or(0);
                    if request.len() >= headers_end + content_length {
                        break;
                    }
                }
            }
            let response = format!(
                "HTTP/1.1 {status_line}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            let _ = socket.write_all(response.as_bytes()).await;
            let _ = socket.flush().await;
        });
        addr
    }

    fn incident() -> UploadFailureIncident {
        UploadFailureIncident {
            bucket: "otterworks-files-chaos-nonexistent".into(),
            s3_key:
                "files/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222"
                    .into(),
            error: "upload failed: NoSuchBucket".into(),
            owner_id: Some("11111111-1111-1111-1111-111111111111".into()),
            file_id: Some("22222222-2222-2222-2222-222222222222".into()),
        }
    }

    #[test]
    fn prompt_contains_incident_and_architecture_sections() {
        let prompt = build_prompt(&incident());

        assert!(prompt.starts_with("You are investigating an incident in the OtterWorks platform"));
        assert!(prompt.contains("## Incident Details"));
        assert!(prompt.contains("## OtterWorks Architecture"));
        assert!(prompt.contains("## Your Task"));
        assert!(prompt.contains("- **Affected Service**: file-service"));
        assert!(prompt.contains("- **Severity**: high"));
        assert!(prompt.contains("File Service (Rust/Actix-Web, port 8082)"));
    }

    #[test]
    fn prompt_describes_the_failed_upload() {
        let prompt = build_prompt(&incident());

        assert!(prompt.contains("Bucket: otterworks-files-chaos-nonexistent"));
        assert!(prompt.contains(
            "S3 key: files/11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222"
        ));
        assert!(prompt.contains("Owner: 11111111-1111-1111-1111-111111111111"));
        assert!(prompt.contains("File id: 22222222-2222-2222-2222-222222222222"));
        assert!(prompt.contains("Error: upload failed: NoSuchBucket"));
    }

    #[test]
    fn prompt_falls_back_when_owner_and_file_are_unknown() {
        let prompt = build_prompt(&UploadFailureIncident {
            owner_id: None,
            file_id: None,
            ..incident()
        });

        assert!(prompt.contains("Owner: Unknown"));
        assert!(prompt.contains("File id: Unknown"));
    }

    #[test]
    fn missing_or_empty_credentials_disable_the_client() {
        assert!(resolve_credentials(None, None).is_none());
        assert!(resolve_credentials(Some("key".into()), None).is_none());
        assert!(resolve_credentials(None, Some("org".into())).is_none());
        assert!(resolve_credentials(Some(String::new()), Some("org".into())).is_none());
        assert!(resolve_credentials(Some("key".into()), Some(String::new())).is_none());
    }

    #[test]
    fn complete_credentials_enable_the_client() {
        assert_eq!(
            resolve_credentials(Some("key".into()), Some("org".into())),
            Some(("key".to_string(), "org".to_string()))
        );
    }

    /// The no-op path: an unconfigured service must not attempt an API call.
    /// Serialized against any other test that touches the same variables.
    #[actix_web::test]
    async fn create_session_is_a_noop_without_credentials() {
        static ENV_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
        let _guard = ENV_LOCK.lock().await;

        let previous_key = std::env::var("DEVIN_API_KEY").ok();
        let previous_org = std::env::var("DEVIN_ORG_ID").ok();
        std::env::remove_var("DEVIN_API_KEY");
        std::env::remove_var("DEVIN_ORG_ID");

        let session = create_session(&incident()).await;

        if let Some(key) = previous_key {
            std::env::set_var("DEVIN_API_KEY", key);
        }
        if let Some(org) = previous_org {
            std::env::set_var("DEVIN_ORG_ID", org);
        }

        assert!(session.is_none());
    }

    #[actix_web::test]
    async fn parses_session_id_and_url_from_a_successful_response() {
        let addr = stub_api(
            "200 OK",
            r#"{"session_id":"devin-abc123","url":"https://app.devin.ai/sessions/abc123"}"#,
        )
        .await;

        let session = post_session(&format!("http://{addr}"), "key", "org", &incident())
            .await
            .expect("session");

        assert_eq!(session.session_id.as_deref(), Some("devin-abc123"));
        assert_eq!(
            session.url.as_deref(),
            Some("https://app.devin.ai/sessions/abc123")
        );
    }

    #[actix_web::test]
    async fn non_2xx_responses_yield_no_session() {
        let addr = stub_api("401 Unauthorized", r#"{"error":"invalid api key"}"#).await;

        assert!(
            post_session(&format!("http://{addr}"), "key", "org", &incident())
                .await
                .is_none()
        );
    }
}
