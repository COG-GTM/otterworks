use aws_sdk_sns::error::ProvideErrorMetadata;
use chrono::Utc;
use serde::Serialize;
use uuid::Uuid;

use crate::config::SnsConfig;
use crate::errors::ServiceError;

/// Publisher for file-service domain events via SNS.
#[derive(Clone)]
pub struct EventPublisher {
    client: aws_sdk_sns::Client,
    topic_arn: Option<String>,
    /// Topic the `file_shared` event is published to when the share-event
    /// failure switch is on: a topic that does not exist in any account, so
    /// SNS rejects the publish with a real AWS error.
    share_fail_topic_arn: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FileEvent {
    pub event_type: String,
    pub file_id: String,
    pub owner_id: String,
    pub folder_id: Option<String>,
    #[serde(rename = "sharedWithUserId")]
    pub shared_with: Option<String>,
    pub timestamp: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mime_type: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub size_bytes: Option<u64>,
}

impl EventPublisher {
    pub async fn new(sns_config: &SnsConfig, aws_config: &crate::config::AwsConfig) -> Self {
        let mut aws_cfg_builder = aws_config::defaults(aws_config::BehaviorVersion::latest())
            .region(aws_config::Region::new(aws_config.region.clone()));

        if let Some(endpoint) = &aws_config.endpoint_url {
            aws_cfg_builder = aws_cfg_builder.endpoint_url(endpoint);
        }

        let aws_cfg = aws_cfg_builder.load().await;
        let client = aws_sdk_sns::Client::new(&aws_cfg);

        let share_fail_topic_arn = if sns_config.share_event_always_fail {
            Some(match &sns_config.topic_arn {
                Some(arn) => format!("{arn}-chaos-nonexistent"),
                None => format!(
                    "arn:aws:sns:{}:000000000000:otterworks-file-events-chaos-nonexistent",
                    aws_config.region
                ),
            })
        } else {
            None
        };

        Self {
            client,
            topic_arn: sns_config.topic_arn.clone(),
            share_fail_topic_arn,
        }
    }

    async fn publish(&self, event: &FileEvent) -> Result<(), ServiceError> {
        self.publish_to(event, self.topic_arn.as_deref()).await
    }

    async fn publish_to(
        &self,
        event: &FileEvent,
        topic_arn: Option<&str>,
    ) -> Result<(), ServiceError> {
        let topic_arn = match topic_arn {
            Some(arn) => arn,
            None => {
                tracing::debug!("SNS topic not configured, skipping event publish");
                return Ok(());
            }
        };

        let message =
            serde_json::to_string(event).map_err(|e| ServiceError::Internal(e.to_string()))?;

        let mut req = self.client.publish().topic_arn(topic_arn).message(&message);

        // message_group_id and message_deduplication_id are only valid for FIFO topics
        if topic_arn.ends_with(".fifo") {
            let dedup_id = format!("{}_{}", event.file_id, event.timestamp);
            req = req
                .message_group_id(&event.event_type)
                .message_deduplication_id(&dedup_id);
        }

        req.send().await.map_err(|e| {
            let detail = match (e.code(), e.message()) {
                (Some(code), Some(msg)) => format!("{code}: {msg}"),
                _ => e.to_string(),
            };
            ServiceError::SnsError(format!("publish to {topic_arn} failed: {detail}"))
        })?;

        tracing::info!(
            event_type = %event.event_type,
            file_id = %event.file_id,
            "Published event to SNS"
        );
        Ok(())
    }

    pub async fn file_uploaded(
        &self,
        file_id: &Uuid,
        owner_id: &Uuid,
        folder_id: Option<&Uuid>,
        name: &str,
        mime_type: &str,
        size_bytes: u64,
    ) -> Result<(), ServiceError> {
        let event = FileEvent {
            event_type: "file_uploaded".into(),
            file_id: file_id.to_string(),
            owner_id: owner_id.to_string(),
            folder_id: folder_id.map(|f| f.to_string()),
            shared_with: None,
            timestamp: Utc::now().to_rfc3339(),
            name: Some(name.to_string()),
            mime_type: Some(mime_type.to_string()),
            size_bytes: Some(size_bytes),
        };
        self.publish(&event).await
    }

    pub async fn file_deleted(&self, file_id: &Uuid, owner_id: &Uuid) -> Result<(), ServiceError> {
        let event = FileEvent {
            event_type: "file_deleted".into(),
            file_id: file_id.to_string(),
            owner_id: owner_id.to_string(),
            folder_id: None,
            shared_with: None,
            timestamp: Utc::now().to_rfc3339(),
            name: None,
            mime_type: None,
            size_bytes: None,
        };
        self.publish(&event).await
    }

    pub async fn file_shared(
        &self,
        file_id: &Uuid,
        owner_id: &Uuid,
        shared_with: &Uuid,
    ) -> Result<(), ServiceError> {
        let event = FileEvent {
            event_type: "file_shared".into(),
            file_id: file_id.to_string(),
            owner_id: owner_id.to_string(),
            folder_id: None,
            shared_with: Some(shared_with.to_string()),
            timestamp: Utc::now().to_rfc3339(),
            name: None,
            mime_type: None,
            size_bytes: None,
        };
        self.publish_to(
            &event,
            self.share_fail_topic_arn
                .as_deref()
                .or(self.topic_arn.as_deref()),
        )
        .await
    }

    pub async fn file_trashed(&self, file_id: &Uuid, owner_id: &Uuid) -> Result<(), ServiceError> {
        let event = FileEvent {
            event_type: "file_trashed".into(),
            file_id: file_id.to_string(),
            owner_id: owner_id.to_string(),
            folder_id: None,
            shared_with: None,
            timestamp: Utc::now().to_rfc3339(),
            name: None,
            mime_type: None,
            size_bytes: None,
        };
        self.publish(&event).await
    }

    pub async fn file_restored(
        &self,
        file_id: &Uuid,
        owner_id: &Uuid,
        folder_id: Option<&Uuid>,
        name: &str,
        mime_type: &str,
        size_bytes: u64,
    ) -> Result<(), ServiceError> {
        let event = FileEvent {
            event_type: "file_restored".into(),
            file_id: file_id.to_string(),
            owner_id: owner_id.to_string(),
            folder_id: folder_id.map(|f| f.to_string()),
            shared_with: None,
            timestamp: Utc::now().to_rfc3339(),
            name: Some(name.to_string()),
            mime_type: Some(mime_type.to_string()),
            size_bytes: Some(size_bytes),
        };
        self.publish(&event).await
    }

    pub async fn file_updated(
        &self,
        file_id: &Uuid,
        owner_id: &Uuid,
        folder_id: Option<&Uuid>,
        name: &str,
        mime_type: &str,
        size_bytes: u64,
    ) -> Result<(), ServiceError> {
        let event = FileEvent {
            event_type: "file_updated".into(),
            file_id: file_id.to_string(),
            owner_id: owner_id.to_string(),
            folder_id: folder_id.map(|f| f.to_string()),
            shared_with: None,
            timestamp: Utc::now().to_rfc3339(),
            name: Some(name.to_string()),
            mime_type: Some(mime_type.to_string()),
            size_bytes: Some(size_bytes),
        };
        self.publish(&event).await
    }

    pub async fn file_moved(
        &self,
        file_id: &Uuid,
        owner_id: &Uuid,
        folder_id: Option<&Uuid>,
    ) -> Result<(), ServiceError> {
        let event = FileEvent {
            event_type: "file_moved".into(),
            file_id: file_id.to_string(),
            owner_id: owner_id.to_string(),
            folder_id: folder_id.map(|f| f.to_string()),
            shared_with: None,
            timestamp: Utc::now().to_rfc3339(),
            name: None,
            mime_type: None,
            size_bytes: None,
        };
        self.publish(&event).await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_file_event_serialization() {
        let event = FileEvent {
            event_type: "file_uploaded".into(),
            file_id: Uuid::new_v4().to_string(),
            owner_id: Uuid::new_v4().to_string(),
            folder_id: None,
            shared_with: None,
            timestamp: Utc::now().to_rfc3339(),
            name: Some("test.txt".to_string()),
            mime_type: Some("text/plain".to_string()),
            size_bytes: Some(100),
        };
        let json = serde_json::to_string(&event).unwrap();
        assert!(json.contains("file_uploaded"));
        assert!(json.contains("eventType"));
        assert!(json.contains("fileId"));
        assert!(json.contains("ownerId"));
    }

    #[test]
    fn test_file_event_with_folder() {
        let folder = Uuid::new_v4();
        let event = FileEvent {
            event_type: "file_moved".into(),
            file_id: Uuid::new_v4().to_string(),
            owner_id: Uuid::new_v4().to_string(),
            folder_id: Some(folder.to_string()),
            shared_with: None,
            timestamp: Utc::now().to_rfc3339(),
            name: None,
            mime_type: None,
            size_bytes: None,
        };
        let json = serde_json::to_string(&event).unwrap();
        assert!(json.contains(&folder.to_string()));
        assert!(json.contains("folderId"));
    }
}
