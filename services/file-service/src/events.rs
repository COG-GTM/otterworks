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
impl EventPublisher {
    /// Test-only assembly from an already-built SNS client, so tests can inject
    /// a faked HTTP boundary without `EventPublisher::new` reaching AWS.
    pub(crate) fn from_parts(client: aws_sdk_sns::Client, topic_arn: Option<String>) -> Self {
        Self { client, topic_arn }
    }
}

#[cfg(test)]
mod publish_tests {
    use super::*;
    use crate::test_support::{
        aws_config_fixture, offline_aws_env, replay, sns_client, sns_publish_ok, uuid_from,
        with_env_blocking,
    };
    use aws_smithy_runtime::client::http::test_util::StaticReplayClient;

    const SNS_ERROR_BODY: &str = r#"<ErrorResponse><Error><Code>InternalFailure</Code>
        <Message>boom</Message></Error></ErrorResponse>"#;

    fn make_publisher(
        topic_arn: Option<&str>,
        responses: Vec<(u16, String)>,
    ) -> (EventPublisher, StaticReplayClient) {
        let http = replay(responses);
        (
            EventPublisher::from_parts(sns_client(http.clone()), topic_arn.map(str::to_string)),
            http,
        )
    }

    fn published_message(http: &StaticReplayClient) -> serde_json::Value {
        let request = http.actual_requests().next().expect("one publish request");
        let body = std::str::from_utf8(request.body().bytes().unwrap()).unwrap();
        let form: std::collections::HashMap<String, String> =
            url_decode_form(body).into_iter().collect();
        serde_json::from_str(form.get("Message").expect("Message parameter")).unwrap()
    }

    fn published_form(http: &StaticReplayClient) -> std::collections::HashMap<String, String> {
        let request = http.actual_requests().next().expect("one publish request");
        let body = std::str::from_utf8(request.body().bytes().unwrap()).unwrap();
        url_decode_form(body).into_iter().collect()
    }

    /// SNS uses `application/x-www-form-urlencoded` for its query protocol.
    fn url_decode_form(body: &str) -> Vec<(String, String)> {
        body.split('&')
            .filter_map(|pair| pair.split_once('='))
            .map(|(k, v)| (percent_decode(k), percent_decode(v)))
            .collect()
    }

    fn percent_decode(raw: &str) -> String {
        let bytes = raw.replace('+', " ").into_bytes();
        let mut out = Vec::with_capacity(bytes.len());
        let mut i = 0;
        while i < bytes.len() {
            if bytes[i] == b'%' && i + 2 < bytes.len() {
                let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap();
                out.push(u8::from_str_radix(hex, 16).unwrap());
                i += 3;
            } else {
                out.push(bytes[i]);
                i += 1;
            }
        }
        String::from_utf8(out).unwrap()
    }

    #[test]
    fn new_builds_a_publisher_that_carries_the_configured_topic() {
        let sns_config = SnsConfig {
            topic_arn: Some("arn:aws:sns:us-east-1:1:files".into()),
        };
        let aws = aws_config_fixture();

        let publisher = with_env_blocking(&offline_aws_env(), async {
            EventPublisher::new(&sns_config, &aws).await
        });

        assert_eq!(
            publisher.topic_arn.as_deref(),
            Some("arn:aws:sns:us-east-1:1:files")
        );
    }

    #[test]
    fn new_honours_a_custom_endpoint_url() {
        let sns_config = SnsConfig { topic_arn: None };
        let mut aws = aws_config_fixture();
        aws.endpoint_url = Some("http://localstack:4566".into());

        let publisher = with_env_blocking(&offline_aws_env(), async {
            EventPublisher::new(&sns_config, &aws).await
        });

        assert_eq!(publisher.topic_arn, None);
        assert!(publisher.clone().topic_arn.is_none());
    }

    #[tokio::test]
    async fn publishing_without_a_topic_is_a_no_op() {
        let (publisher, http) = make_publisher(None, vec![]);

        publisher
            .file_deleted(&uuid_from(1), &uuid_from(2))
            .await
            .expect("skipped publish still succeeds");

        assert_eq!(
            http.actual_requests().count(),
            0,
            "no SNS call without a topic ARN"
        );
    }

    #[tokio::test]
    async fn file_uploaded_publishes_the_full_payload() {
        let (publisher, http) = make_publisher(
            Some("arn:aws:sns:us-east-1:1:files"),
            vec![sns_publish_ok()],
        );

        publisher
            .file_uploaded(
                &uuid_from(1),
                &uuid_from(2),
                Some(&uuid_from(3)),
                "report.pdf",
                "application/pdf",
                2048,
            )
            .await
            .expect("publish");

        let message = published_message(&http);
        assert_eq!(message["eventType"], "file_uploaded");
        assert_eq!(message["fileId"], uuid_from(1).to_string());
        assert_eq!(message["ownerId"], uuid_from(2).to_string());
        assert_eq!(message["folderId"], uuid_from(3).to_string());
        assert_eq!(message["name"], "report.pdf");
        assert_eq!(message["mimeType"], "application/pdf");
        assert_eq!(message["sizeBytes"], 2048);
        assert!(message["timestamp"].as_str().unwrap().contains('T'));

        let form = published_form(&http);
        assert_eq!(form.get("Action").map(String::as_str), Some("Publish"));
        assert_eq!(
            form.get("TopicArn").map(String::as_str),
            Some("arn:aws:sns:us-east-1:1:files")
        );
        assert!(
            !form.contains_key("MessageGroupId"),
            "standard topics must not get FIFO parameters"
        );
    }

    #[tokio::test]
    async fn fifo_topics_get_a_group_and_deduplication_id() {
        let (publisher, http) = make_publisher(
            Some("arn:aws:sns:us-east-1:1:files.fifo"),
            vec![sns_publish_ok()],
        );

        publisher
            .file_shared(&uuid_from(1), &uuid_from(2), &uuid_from(4))
            .await
            .expect("publish");

        let form = published_form(&http);
        assert_eq!(
            form.get("MessageGroupId").map(String::as_str),
            Some("file_shared")
        );
        let dedup = form.get("MessageDeduplicationId").expect("dedup id");
        assert!(
            dedup.starts_with(&uuid_from(1).to_string()),
            "dedup id is derived from file id + timestamp: {dedup}"
        );

        let message = published_message(&http);
        assert_eq!(message["sharedWithUserId"], uuid_from(4).to_string());
    }

    #[tokio::test]
    async fn sns_failures_surface_as_service_errors() {
        let (publisher, _http) = make_publisher(
            Some("arn:aws:sns:us-east-1:1:files"),
            vec![(500, SNS_ERROR_BODY.to_string())],
        );

        let err = publisher
            .file_trashed(&uuid_from(1), &uuid_from(2))
            .await
            .expect_err("a 500 from SNS is an error");

        assert!(matches!(err, ServiceError::SnsError(_)), "got {err:?}");
    }

    #[tokio::test]
    async fn each_event_helper_sets_its_own_event_type_and_fields() {
        let topic = Some("arn:aws:sns:us-east-1:1:files");
        let file = uuid_from(1);
        let owner = uuid_from(2);
        let folder = uuid_from(3);

        let (publisher, http) = make_publisher(topic, vec![sns_publish_ok()]);
        publisher.file_deleted(&file, &owner).await.unwrap();
        let message = published_message(&http);
        assert_eq!(message["eventType"], "file_deleted");
        assert!(message["folderId"].is_null());
        assert!(message.get("name").is_none(), "empty fields are skipped");

        let (publisher, http) = make_publisher(topic, vec![sns_publish_ok()]);
        publisher.file_trashed(&file, &owner).await.unwrap();
        assert_eq!(published_message(&http)["eventType"], "file_trashed");

        let (publisher, http) = make_publisher(topic, vec![sns_publish_ok()]);
        publisher
            .file_restored(&file, &owner, Some(&folder), "a.txt", "text/plain", 10)
            .await
            .unwrap();
        let message = published_message(&http);
        assert_eq!(message["eventType"], "file_restored");
        assert_eq!(message["name"], "a.txt");
        assert_eq!(message["sizeBytes"], 10);

        let (publisher, http) = make_publisher(topic, vec![sns_publish_ok()]);
        publisher
            .file_updated(&file, &owner, None, "b.txt", "text/plain", 20)
            .await
            .unwrap();
        let message = published_message(&http);
        assert_eq!(message["eventType"], "file_updated");
        assert!(message["folderId"].is_null());
        assert_eq!(message["mimeType"], "text/plain");

        let (publisher, http) = make_publisher(topic, vec![sns_publish_ok()]);
        publisher
            .file_moved(&file, &owner, Some(&folder))
            .await
            .unwrap();
        let message = published_message(&http);
        assert_eq!(message["eventType"], "file_moved");
        assert_eq!(message["folderId"], folder.to_string());
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
