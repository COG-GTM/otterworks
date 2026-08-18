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

        Self {
            client,
            topic_arn: sns_config.topic_arn.clone(),
        }
    }

    async fn publish(&self, event: &FileEvent) -> Result<(), ServiceError> {
        let topic_arn = match &self.topic_arn {
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

        req.send()
            .await
            .map_err(|e| ServiceError::SnsError(e.to_string()))?;

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
        self.publish(&event).await
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

#[cfg(test)]
mod publish_tests {
    use super::*;
    use crate::config::AwsConfig;
    use crate::models::test_support::sns_client;
    use aws_smithy_runtime::client::http::test_util::StaticReplayClient;

    const PUBLISH_OK: &str = "<PublishResponse><PublishResult><MessageId>m-1</MessageId></PublishResult></PublishResponse>";
    const PUBLISH_ERR: &str =
        "<ErrorResponse><Error><Code>InternalError</Code><Message>boom</Message></Error></ErrorResponse>";

    fn fake_publisher(
        topic_arn: Option<&str>,
        responses: Vec<(u16, String)>,
    ) -> (EventPublisher, StaticReplayClient) {
        let (client, http) = sns_client(responses);
        (
            EventPublisher {
                client,
                topic_arn: topic_arn.map(|a| a.to_string()),
            },
            http,
        )
    }

    fn ok_response() -> Vec<(u16, String)> {
        vec![(200, PUBLISH_OK.to_string())]
    }

    fn sent_body(http: &StaticReplayClient) -> String {
        let req = http.actual_requests().next().expect("one request");
        String::from_utf8(req.body().bytes().expect("in-memory body").to_vec()).unwrap()
    }

    fn ids() -> (Uuid, Uuid) {
        (Uuid::new_v4(), Uuid::new_v4())
    }

    fn aws_config() -> AwsConfig {
        AwsConfig {
            region: "us-east-1".into(),
            endpoint_url: Some("http://localstack:4566".into()),
            s3_bucket: "b".into(),
            dynamodb_table: "files".into(),
            dynamodb_folders_table: "folders".into(),
            dynamodb_versions_table: "versions".into(),
            dynamodb_shares_table: "shares".into(),
        }
    }

    #[tokio::test]
    async fn new_carries_the_configured_topic_arn() {
        let publisher = EventPublisher::new(
            &SnsConfig {
                topic_arn: Some("arn:aws:sns:us-east-1:1:files".into()),
            },
            &aws_config(),
        )
        .await;
        assert_eq!(
            publisher.topic_arn.as_deref(),
            Some("arn:aws:sns:us-east-1:1:files")
        );
    }

    #[tokio::test]
    async fn publish_is_skipped_when_no_topic_is_configured() {
        let (publisher, http) = fake_publisher(None, vec![]);
        let (file, owner) = ids();

        publisher
            .file_uploaded(&file, &owner, None, "a.txt", "text/plain", 1)
            .await
            .expect("no topic is not an error");

        assert_eq!(http.actual_requests().count(), 0, "nothing is sent to SNS");
    }

    #[tokio::test]
    async fn file_uploaded_publishes_the_full_event_payload() {
        let (publisher, http) =
            fake_publisher(Some("arn:aws:sns:us-east-1:1:files"), ok_response());
        let (file, owner) = ids();
        let folder = Uuid::new_v4();

        publisher
            .file_uploaded(&file, &owner, Some(&folder), "a.txt", "text/plain", 99)
            .await
            .expect("publish");

        let body = sent_body(&http);
        assert!(body.contains("Action=Publish"), "{body}");
        assert!(body.contains("file_uploaded"), "{body}");
        assert!(body.contains(&file.to_string()), "{body}");
        assert!(body.contains(&owner.to_string()), "{body}");
        assert!(body.contains(&folder.to_string()), "{body}");
        assert!(body.contains("99"), "{body}");
        assert!(
            !body.contains("MessageGroupId"),
            "standard topics take no FIFO parameters: {body}"
        );
    }

    #[tokio::test]
    async fn fifo_topics_get_a_group_and_deduplication_id() {
        let (publisher, http) =
            fake_publisher(Some("arn:aws:sns:us-east-1:1:files.fifo"), ok_response());
        let (file, owner) = ids();

        publisher
            .file_deleted(&file, &owner)
            .await
            .expect("publish");

        let body = sent_body(&http);
        assert!(body.contains("MessageGroupId=file_deleted"), "{body}");
        assert!(body.contains("MessageDeduplicationId="), "{body}");
    }

    #[tokio::test]
    async fn sns_failures_surface_as_service_errors() {
        let (publisher, _http) = fake_publisher(
            Some("arn:aws:sns:us-east-1:1:files"),
            vec![(500, PUBLISH_ERR.to_string())],
        );
        let (file, owner) = ids();

        let err = publisher
            .file_deleted(&file, &owner)
            .await
            .expect_err("a 500 from SNS is an error");

        assert!(matches!(err, ServiceError::SnsError(_)), "got {err:?}");
    }

    #[tokio::test]
    async fn file_shared_carries_the_recipient() {
        let (publisher, http) =
            fake_publisher(Some("arn:aws:sns:us-east-1:1:files"), ok_response());
        let (file, owner) = ids();
        let recipient = Uuid::new_v4();

        publisher
            .file_shared(&file, &owner, &recipient)
            .await
            .expect("publish");

        let body = sent_body(&http);
        assert!(body.contains("file_shared"), "{body}");
        assert!(body.contains(&recipient.to_string()), "{body}");
    }

    #[tokio::test]
    async fn file_trashed_publishes_a_minimal_event() {
        let (publisher, http) =
            fake_publisher(Some("arn:aws:sns:us-east-1:1:files"), ok_response());
        let (file, owner) = ids();

        publisher
            .file_trashed(&file, &owner)
            .await
            .expect("publish");

        let body = sent_body(&http);
        assert!(body.contains("file_trashed"), "{body}");
        assert!(body.contains(&file.to_string()), "{body}");
    }

    #[tokio::test]
    async fn file_restored_and_updated_include_the_file_attributes() {
        let (publisher, http) =
            fake_publisher(Some("arn:aws:sns:us-east-1:1:files"), ok_response());
        let (file, owner) = ids();

        publisher
            .file_restored(&file, &owner, None, "restored.txt", "text/plain", 12)
            .await
            .expect("publish");
        let body = sent_body(&http);
        assert!(body.contains("file_restored"), "{body}");
        assert!(body.contains("restored.txt"), "{body}");

        let (publisher, http) =
            fake_publisher(Some("arn:aws:sns:us-east-1:1:files"), ok_response());
        publisher
            .file_updated(&file, &owner, None, "renamed.txt", "text/plain", 12)
            .await
            .expect("publish");
        let body = sent_body(&http);
        assert!(body.contains("file_updated"), "{body}");
        assert!(body.contains("renamed.txt"), "{body}");
    }

    #[tokio::test]
    async fn file_moved_reports_the_destination_folder() {
        let (publisher, http) =
            fake_publisher(Some("arn:aws:sns:us-east-1:1:files"), ok_response());
        let (file, owner) = ids();
        let folder = Uuid::new_v4();

        publisher
            .file_moved(&file, &owner, Some(&folder))
            .await
            .expect("publish");

        let body = sent_body(&http);
        assert!(body.contains("file_moved"), "{body}");
        assert!(body.contains(&folder.to_string()), "{body}");
    }

    #[test]
    fn optional_attributes_are_omitted_from_the_wire_format() {
        let event = FileEvent {
            event_type: "file_deleted".into(),
            file_id: Uuid::nil().to_string(),
            owner_id: Uuid::nil().to_string(),
            folder_id: None,
            shared_with: None,
            timestamp: "1970-01-01T00:00:00+00:00".into(),
            name: None,
            mime_type: None,
            size_bytes: None,
        };
        let json = serde_json::to_string(&event).unwrap();
        assert!(!json.contains("name"), "{json}");
        assert!(!json.contains("mimeType"), "{json}");
        assert!(!json.contains("sizeBytes"), "{json}");
        assert!(json.contains("\"folderId\":null"), "{json}");
    }
}

#[cfg(test)]
impl EventPublisher {
    pub(crate) fn for_tests(client: aws_sdk_sns::Client, topic_arn: Option<String>) -> Self {
        Self { client, topic_arn }
    }
}
