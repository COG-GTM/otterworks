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
mod publisher_tests {
    use super::*;
    use aws_sdk_sns::config::{retry::RetryConfig, BehaviorVersion, Credentials, Region};
    use aws_smithy_runtime::client::http::test_util::{ReplayEvent, StaticReplayClient};
    use aws_smithy_types::body::SdkBody;

    const PUBLISH_OK: &str = concat!(
        "<PublishResponse xmlns=\"http://sns.amazonaws.com/doc/2010-03-31/\">",
        "<PublishResult><MessageId>11111111-2222-3333-4444-555555555555</MessageId></PublishResult>",
        "<ResponseMetadata><RequestId>req-1</RequestId></ResponseMetadata></PublishResponse>"
    );

    const PUBLISH_ERR: &str = concat!(
        "<ErrorResponse><Error><Type>Sender</Type><Code>InvalidParameter</Code>",
        "<Message>Invalid parameter: TopicArn</Message></Error></ErrorResponse>"
    );

    /// An SNS client whose HTTP boundary is faked: `n` canned responses, no network.
    fn replay(n: usize, status: u16, body: &'static str) -> StaticReplayClient {
        StaticReplayClient::new(
            (0..n)
                .map(|_| {
                    ReplayEvent::new(
                        http::Request::builder()
                            .method("POST")
                            .uri("https://sns.us-east-1.amazonaws.com/")
                            .body(SdkBody::empty())
                            .unwrap(),
                        http::Response::builder()
                            .status(status)
                            .body(SdkBody::from(body))
                            .unwrap(),
                    )
                })
                .collect(),
        )
    }

    fn publisher(topic_arn: Option<&str>, http: StaticReplayClient) -> EventPublisher {
        let conf = aws_sdk_sns::Config::builder()
            .behavior_version(BehaviorVersion::latest())
            .region(Region::new("us-east-1"))
            .credentials_provider(Credentials::for_tests())
            .retry_config(RetryConfig::disabled())
            .http_client(http)
            .build();
        EventPublisher {
            client: aws_sdk_sns::Client::from_conf(conf),
            topic_arn: topic_arn.map(str::to_string),
        }
    }

    fn sent_bodies(http: &StaticReplayClient) -> Vec<String> {
        http.actual_requests()
            .map(|r| String::from_utf8_lossy(r.body().bytes().unwrap_or_default()).to_string())
            .collect()
    }

    #[tokio::test]
    async fn every_event_type_is_published_with_its_payload() {
        let http = replay(7, 200, PUBLISH_OK);
        let pubr = publisher(Some("arn:aws:sns:us-east-1:1:files"), http.clone());
        let file = Uuid::new_v4();
        let owner = Uuid::new_v4();
        let folder = Uuid::new_v4();
        let other = Uuid::new_v4();

        pubr.file_uploaded(&file, &owner, Some(&folder), "a.txt", "text/plain", 12)
            .await
            .unwrap();
        pubr.file_deleted(&file, &owner).await.unwrap();
        pubr.file_shared(&file, &owner, &other).await.unwrap();
        pubr.file_trashed(&file, &owner).await.unwrap();
        pubr.file_restored(&file, &owner, None, "a.txt", "text/plain", 12)
            .await
            .unwrap();
        pubr.file_updated(&file, &owner, Some(&folder), "b.txt", "text/plain", 12)
            .await
            .unwrap();
        pubr.file_moved(&file, &owner, None).await.unwrap();

        let bodies = sent_bodies(&http);
        assert_eq!(bodies.len(), 7);
        for expected in [
            "file_uploaded",
            "file_deleted",
            "file_shared",
            "file_trashed",
            "file_restored",
            "file_updated",
            "file_moved",
        ] {
            assert!(
                bodies.iter().any(|b| b.contains(expected)),
                "no request carried {expected}"
            );
        }
        assert!(bodies[0].contains("a.txt"));
        assert!(bodies[2].contains(&other.to_string()));
    }

    #[tokio::test]
    async fn publishing_is_skipped_when_no_topic_is_configured() {
        let http = replay(0, 200, PUBLISH_OK);
        let pubr = publisher(None, http.clone());

        pubr.file_uploaded(
            &Uuid::new_v4(),
            &Uuid::new_v4(),
            None,
            "a.txt",
            "text/plain",
            1,
        )
        .await
        .expect("a missing topic is not an error");

        assert_eq!(http.actual_requests().count(), 0, "nothing is sent to SNS");
    }

    #[tokio::test]
    async fn fifo_topics_get_group_and_deduplication_ids() {
        let http = replay(1, 200, PUBLISH_OK);
        let pubr = publisher(Some("arn:aws:sns:us-east-1:1:files.fifo"), http.clone());

        pubr.file_trashed(&Uuid::new_v4(), &Uuid::new_v4())
            .await
            .unwrap();

        let body = &sent_bodies(&http)[0];
        assert!(body.contains("MessageGroupId"), "{body}");
        assert!(body.contains("MessageDeduplicationId"), "{body}");
    }

    #[tokio::test]
    async fn standard_topics_omit_fifo_only_parameters() {
        let http = replay(1, 200, PUBLISH_OK);
        let pubr = publisher(Some("arn:aws:sns:us-east-1:1:files"), http.clone());

        pubr.file_moved(&Uuid::new_v4(), &Uuid::new_v4(), None)
            .await
            .unwrap();

        let body = &sent_bodies(&http)[0];
        assert!(!body.contains("MessageGroupId"), "{body}");
        assert!(!body.contains("MessageDeduplicationId"), "{body}");
    }

    #[tokio::test]
    async fn sns_failures_surface_as_service_errors() {
        let http = replay(1, 400, PUBLISH_ERR);
        let pubr = publisher(Some("arn:aws:sns:us-east-1:1:files"), http);

        let err = pubr
            .file_deleted(&Uuid::new_v4(), &Uuid::new_v4())
            .await
            .expect_err("a 400 from SNS is an error");

        assert!(matches!(err, ServiceError::SnsError(_)), "got {err:?}");
    }

    #[tokio::test]
    async fn new_builds_a_publisher_from_config() {
        let aws = crate::config::AwsConfig {
            region: "us-east-1".into(),
            endpoint_url: None,
            s3_bucket: "b".into(),
            dynamodb_table: "t".into(),
            dynamodb_folders_table: "f".into(),
            dynamodb_versions_table: "v".into(),
            dynamodb_shares_table: "s".into(),
        };

        let default_endpoint = EventPublisher::new(&SnsConfig { topic_arn: None }, &aws).await;
        assert!(default_endpoint.topic_arn.is_none());

        let custom_endpoint = EventPublisher::new(
            &SnsConfig {
                topic_arn: Some("arn:aws:sns:us-east-1:1:files".into()),
            },
            &crate::config::AwsConfig {
                endpoint_url: Some("http://localstack:4566".into()),
                ..aws
            },
        )
        .await;
        assert_eq!(
            custom_endpoint.topic_arn.as_deref(),
            Some("arn:aws:sns:us-east-1:1:files")
        );
        // Clone is used when the publisher is shared across actix workers.
        assert!(custom_endpoint.clone().topic_arn.is_some());
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
