//! Structured audit events for sensitive file actions, delivered to
//! audit-service (`POST {AUDIT_SERVICE_URL}/api/v1/audit/events`).
//!
//! Emitting never blocks a request: handlers push onto a bounded mpsc channel
//! and a background task delivers each event with a short timeout and a
//! bounded retry. Failures are logged and counted in
//! `audit_emit_failures_total`.

use std::collections::BTreeMap;
use std::time::Duration;

use actix_web::{HttpMessage, HttpRequest};
use chrono::{SecondsFormat, Utc};
use lazy_static::lazy_static;
use prometheus::{register_int_counter_vec, IntCounterVec};
use serde::Serialize;
use tokio::sync::mpsc;

use crate::errors::ServiceError;
use crate::middleware::RequestIdValue;

pub const SERVICE_NAME: &str = "file-service";
const EVENTS_PATH: &str = "/api/v1/audit/events";
const QUEUE_CAPACITY: usize = 1024;
const MAX_USER_AGENT_LEN: usize = 512;

lazy_static! {
    pub static ref AUDIT_EMIT_FAILURES_TOTAL: IntCounterVec = register_int_counter_vec!(
        "audit_emit_failures_total",
        "Audit events that could not be delivered to audit-service",
        &["reason"]
    )
    .expect("metric can be created");
    pub static ref AUDIT_EVENTS_SENT_TOTAL: IntCounterVec = register_int_counter_vec!(
        "audit_events_sent_total",
        "Audit events accepted by audit-service",
        &["action"]
    )
    .expect("metric can be created");
}

/// Detail keys that could carry secrets or payloads are never sent.
const FORBIDDEN_DETAIL_KEYS: &[&str] = &[
    "password",
    "token",
    "secret",
    "credential",
    "authorization",
    "cookie",
    "jwt",
    "content",
    "body",
    "url",
];

#[derive(Clone, Debug)]
pub struct AuditConfig {
    /// Base URL of audit-service; `None` disables emitting.
    pub url: Option<String>,
    pub token: Option<String>,
    pub timeout: Duration,
    /// Extra attempts after the first one, for 5xx and transport errors.
    pub max_retries: u32,
    pub retry_backoff: Duration,
}

impl AuditConfig {
    pub fn from_env() -> Self {
        let non_empty = |key: &str| {
            std::env::var(key)
                .ok()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
        };
        Self {
            url: non_empty("AUDIT_SERVICE_URL"),
            token: non_empty("AUDIT_SERVICE_TOKEN"),
            timeout: Duration::from_millis(
                non_empty("AUDIT_TIMEOUT_MS")
                    .and_then(|v| v.parse().ok())
                    .unwrap_or(2000),
            ),
            max_retries: non_empty("AUDIT_MAX_RETRIES")
                .and_then(|v| v.parse().ok())
                .unwrap_or(2),
            retry_backoff: Duration::from_millis(200),
        }
    }
}

/// Wire format of the v2 audit contract (camelCase).
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuditEvent {
    pub user_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub actor_email: Option<String>,
    pub actor_type: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tenant_id: Option<String>,
    pub action: String,
    pub resource_type: String,
    pub resource_id: String,
    pub outcome: String,
    pub details: BTreeMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ip_address: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub user_agent: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
    pub service_name: String,
    pub timestamp: String,
}

/// Who and from where, taken from the gateway-injected headers.
#[derive(Clone, Debug, Default)]
pub struct AuditContext {
    pub user_id: Option<String>,
    pub actor_email: Option<String>,
    pub ip_address: Option<String>,
    pub user_agent: Option<String>,
    pub request_id: Option<String>,
    pub tenant_id: Option<String>,
}

fn header(req: &HttpRequest, name: &str) -> Option<String> {
    req.headers()
        .get(name)
        .and_then(|v| v.to_str().ok())
        .map(str::trim)
        .filter(|s| !s.is_empty())
        .map(String::from)
}

impl AuditContext {
    pub fn from_request(req: &HttpRequest) -> Self {
        let ip_address = header(req, "X-Forwarded-For")
            .and_then(|v| {
                v.split(',')
                    .next()
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
            })
            .or_else(|| header(req, "X-Real-IP"))
            .or_else(|| req.peer_addr().map(|a| a.ip().to_string()));
        let request_id = header(req, "X-Request-ID").or_else(|| {
            req.extensions()
                .get::<RequestIdValue>()
                .map(|r| r.0.clone())
        });
        Self {
            user_id: header(req, "X-User-ID"),
            actor_email: header(req, "X-User-Email"),
            ip_address,
            user_agent: header(req, "User-Agent")
                .map(|ua| ua.chars().take(MAX_USER_AGENT_LEN).collect()),
            request_id,
            tenant_id: header(req, "X-Tenant-ID"),
        }
    }

    /// True when the request carries an authenticated identity that is not
    /// `owner`. Requests without `X-User-ID` (direct/internal callers) keep
    /// the previous unauthenticated behaviour.
    pub fn is_not(&self, owner: &uuid::Uuid) -> bool {
        match &self.user_id {
            Some(id) => id.parse::<uuid::Uuid>().map_or(true, |id| id != *owner),
            None => false,
        }
    }
}

/// What is being audited; the outcome is filled in from the handler result.
#[derive(Clone, Debug)]
pub struct AuditRecord {
    pub action: String,
    pub resource_type: String,
    pub resource_id: String,
    pub details: BTreeMap<String, String>,
}

impl AuditRecord {
    pub fn new(action: &str, resource_type: &str, resource_id: impl Into<String>) -> Self {
        Self {
            action: action.into(),
            resource_type: resource_type.into(),
            resource_id: resource_id.into(),
            details: BTreeMap::new(),
        }
    }

    pub fn detail(&mut self, key: &str, value: impl ToString) -> &mut Self {
        self.details.insert(key.into(), value.to_string());
        self
    }
}

pub fn outcome_for<T>(result: &Result<T, ServiceError>) -> &'static str {
    match result {
        Ok(_) => "success",
        Err(ServiceError::Forbidden(_)) | Err(ServiceError::Unauthorized(_)) => "denied",
        Err(_) => "failure",
    }
}

fn error_kind(err: &ServiceError) -> &'static str {
    match err {
        ServiceError::FileNotFound(_) => "file_not_found",
        ServiceError::FolderNotFound(_) => "folder_not_found",
        ServiceError::VersionNotFound(_) => "version_not_found",
        ServiceError::ShareNotFound(_) => "share_not_found",
        ServiceError::BadRequest(_) => "bad_request",
        ServiceError::FileTooLarge { .. } => "file_too_large",
        ServiceError::Unauthorized(_) => "unauthorized",
        ServiceError::Forbidden(_) => "not_owner",
        ServiceError::S3Error(_) => "storage_error",
        ServiceError::DynamoError(_) => "metadata_error",
        ServiceError::SnsError(_) => "event_error",
        ServiceError::Internal(_) => "internal_error",
    }
}

pub fn build_event(ctx: &AuditContext, record: AuditRecord, outcome: &str) -> AuditEvent {
    let details = record
        .details
        .into_iter()
        .filter(|(k, _)| {
            let k = k.to_ascii_lowercase();
            !FORBIDDEN_DETAIL_KEYS.iter().any(|f| k.contains(f))
        })
        .collect();
    AuditEvent {
        user_id: ctx.user_id.clone().unwrap_or_else(|| "anonymous".into()),
        actor_email: ctx.actor_email.clone(),
        actor_type: if ctx.user_id.is_some() {
            "user"
        } else {
            "anonymous"
        }
        .into(),
        tenant_id: ctx.tenant_id.clone(),
        action: record.action,
        resource_type: record.resource_type,
        resource_id: record.resource_id,
        outcome: outcome.into(),
        details,
        ip_address: ctx.ip_address.clone(),
        user_agent: ctx.user_agent.clone(),
        request_id: ctx.request_id.clone(),
        service_name: SERVICE_NAME.into(),
        timestamp: Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true),
    }
}

/// Handle shared by all handlers; cheap to clone.
#[derive(Clone)]
pub struct AuditEmitter {
    tx: Option<mpsc::Sender<AuditEvent>>,
}

impl AuditEmitter {
    /// Starts the background delivery task. Must be called inside a Tokio
    /// runtime. Returns a no-op emitter when `AUDIT_SERVICE_URL` is unset.
    pub fn start(config: AuditConfig) -> Self {
        let Some(base_url) = config.url.clone() else {
            tracing::warn!("AUDIT_SERVICE_URL not set; audit events are disabled");
            return Self::disabled();
        };
        if config.token.is_none() {
            tracing::warn!("AUDIT_SERVICE_TOKEN not set; audit events are sent without a token");
        }
        let client = match reqwest::Client::builder().timeout(config.timeout).build() {
            Ok(c) => c,
            Err(err) => {
                tracing::error!(error = %err, "failed to build audit HTTP client; audit disabled");
                return Self::disabled();
            }
        };
        let endpoint = format!("{}{}", base_url.trim_end_matches('/'), EVENTS_PATH);
        let (tx, mut rx) = mpsc::channel::<AuditEvent>(QUEUE_CAPACITY);
        tokio::spawn(async move {
            while let Some(event) = rx.recv().await {
                tokio::spawn(deliver(
                    client.clone(),
                    endpoint.clone(),
                    config.clone(),
                    event,
                ));
            }
        });
        Self { tx: Some(tx) }
    }

    pub fn disabled() -> Self {
        Self { tx: None }
    }

    /// Queues an event without waiting. Never fails the caller.
    pub fn emit(&self, event: AuditEvent) {
        let Some(tx) = &self.tx else { return };
        if let Err(err) = tx.try_send(event) {
            AUDIT_EMIT_FAILURES_TOTAL
                .with_label_values(&["queue_full"])
                .inc();
            tracing::warn!(error = %err, "audit queue unavailable; dropping audit event");
        }
    }

    /// Emits one event whose outcome is derived from the handler result.
    pub fn record<T>(
        &self,
        ctx: &AuditContext,
        mut record: AuditRecord,
        result: &Result<T, ServiceError>,
    ) {
        if let Err(err) = result {
            record.detail("reason", error_kind(err));
        }
        self.emit(build_event(ctx, record, outcome_for(result)));
    }
}

async fn deliver(
    client: reqwest::Client,
    endpoint: String,
    config: AuditConfig,
    event: AuditEvent,
) {
    let attempts = config.max_retries + 1;
    for attempt in 1..=attempts {
        let mut req = client
            .post(&endpoint)
            .header("Content-Type", "application/json")
            .json(&event);
        if let Some(token) = &config.token {
            req = req.header("X-Audit-Token", token);
        }
        if let Some(request_id) = &event.request_id {
            req = req.header("X-Request-ID", request_id);
        }
        let (reason, retryable) = match req.send().await {
            Ok(resp) if resp.status().is_success() => {
                AUDIT_EVENTS_SENT_TOTAL
                    .with_label_values(&[&event.action])
                    .inc();
                return;
            }
            Ok(resp) => {
                let status = resp.status();
                tracing::warn!(
                    action = %event.action,
                    status = %status,
                    attempt,
                    "audit-service rejected audit event"
                );
                (
                    "http_status",
                    status.is_server_error() || status.as_u16() == 429,
                )
            }
            Err(err) => {
                tracing::warn!(
                    action = %event.action,
                    error = %err,
                    attempt,
                    "audit event delivery failed"
                );
                (
                    if err.is_timeout() {
                        "timeout"
                    } else {
                        "transport"
                    },
                    true,
                )
            }
        };
        if !retryable || attempt == attempts {
            AUDIT_EMIT_FAILURES_TOTAL.with_label_values(&[reason]).inc();
            tracing::error!(
                action = %event.action,
                resource_id = %event.resource_id,
                reason,
                "giving up on audit event"
            );
            return;
        }
        tokio::time::sleep(config.retry_backoff * attempt).await;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn forbidden_detail_keys_are_dropped() {
        let mut record = AuditRecord::new("share.create", "file", "f1");
        record
            .detail("permission", "viewer")
            .detail("shareToken", "abc")
            .detail("password", "hunter2")
            .detail("fileContent", "bytes");
        let event = build_event(&AuditContext::default(), record, "success");
        assert_eq!(event.details.len(), 1);
        assert_eq!(event.details["permission"], "viewer");
    }

    #[test]
    fn anonymous_actor_when_no_identity() {
        let event = build_event(
            &AuditContext::default(),
            AuditRecord::new("delete", "file", "f1"),
            "failure",
        );
        assert_eq!(event.user_id, "anonymous");
        assert_eq!(event.actor_type, "anonymous");
        assert_eq!(event.service_name, SERVICE_NAME);
        assert!(event.timestamp.ends_with('Z'));
    }

    #[test]
    fn owner_match_accepts_any_uuid_form() {
        let owner = uuid::Uuid::new_v4();
        let ctx = |id: String| AuditContext {
            user_id: Some(id),
            ..AuditContext::default()
        };
        assert!(!ctx(owner.to_string()).is_not(&owner));
        assert!(!ctx(owner.simple().to_string()).is_not(&owner));
        assert!(!ctx(owner.to_string().to_uppercase()).is_not(&owner));
        assert!(ctx(uuid::Uuid::new_v4().to_string()).is_not(&owner));
        assert!(ctx("not-a-uuid".into()).is_not(&owner));
        assert!(!AuditContext::default().is_not(&owner));
    }

    #[test]
    fn outcome_maps_forbidden_to_denied() {
        let denied: Result<(), ServiceError> = Err(ServiceError::Forbidden("x".into()));
        let failed: Result<(), ServiceError> = Err(ServiceError::FileNotFound("x".into()));
        assert_eq!(outcome_for(&denied), "denied");
        assert_eq!(outcome_for(&failed), "failure");
        assert_eq!(outcome_for(&Ok::<(), ServiceError>(())), "success");
    }
}
