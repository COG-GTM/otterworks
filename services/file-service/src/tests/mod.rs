//! Handler-level unit tests: the real actix routes, handlers and AWS SDK
//! clients run against in-memory fakes (`fakes.rs`), so every route can be
//! exercised in `cargo test` without LocalStack, Redis or the gateway.

mod authz;
mod fakes;
mod files;
mod folders;
mod pure;
mod shares;

use std::sync::Arc;

use actix_web::body::MessageBody;
use actix_web::dev::{Service, ServiceResponse};
use actix_web::{test, web, App};
use aws_smithy_http_client::test_util::infallible_client_fn;
use serde_json::Value;
use uuid::Uuid;

use crate::alerts::AlertConfig;
use crate::config::{AppConfig, AwsConfig, ServerConfig, SnsConfig};
use crate::events::EventPublisher;
use crate::metadata::MetadataClient;
use crate::storage::S3Client;
use fakes::{FakeAws, FakeRedis};

pub const BUCKET: &str = "otterworks-files-test";
pub const FILES: &str = "files-test";
pub const FOLDERS: &str = "folders-test";
pub const VERSIONS: &str = "versions-test";
pub const SHARES: &str = "shares-test";
pub const TOPIC: &str = "arn:aws:sns:us-east-1:000000000000:otterworks-events";

pub struct Opts {
    pub max_upload_bytes: u64,
    pub upload_always_fail: bool,
    pub share_event_always_fail: bool,
    pub topic: Option<String>,
}

impl Default for Opts {
    fn default() -> Self {
        Self {
            max_upload_bytes: 1024,
            upload_always_fail: false,
            share_event_always_fail: false,
            topic: Some(TOPIC.to_string()),
        }
    }
}

pub struct Ctx {
    pub aws: Arc<FakeAws>,
    pub redis: FakeRedis,
    config: web::Data<AppConfig>,
    s3: web::Data<S3Client>,
    meta: web::Data<MetadataClient>,
    events: web::Data<EventPublisher>,
    redis_cm: web::Data<redis::aio::ConnectionManager>,
}

fn http_client(aws: &Arc<FakeAws>) -> aws_smithy_runtime_api::client::http::SharedHttpClient {
    let aws = aws.clone();
    infallible_client_fn(move |req| aws.handle(req))
}

impl Ctx {
    pub async fn new() -> Self {
        Self::with(Opts::default()).await
    }

    pub async fn with(opts: Opts) -> Self {
        let aws = Arc::new(FakeAws::default());
        let http = http_client(&aws);

        let dynamo = aws_sdk_dynamodb::Config::builder()
            .behavior_version(aws_sdk_dynamodb::config::BehaviorVersion::latest())
            .region(aws_sdk_dynamodb::config::Region::new("us-east-1"))
            .credentials_provider(aws_sdk_dynamodb::config::Credentials::new(
                "test", "test", None, None, "test",
            ))
            .endpoint_url("http://dynamodb.fake")
            .retry_config(aws_sdk_dynamodb::config::retry::RetryConfig::disabled())
            .http_client(http.clone())
            .build();
        let s3 = aws_sdk_s3::Config::builder()
            .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
            .region(aws_sdk_s3::config::Region::new("us-east-1"))
            .credentials_provider(aws_sdk_s3::config::Credentials::new(
                "test", "test", None, None, "test",
            ))
            .endpoint_url("http://s3.fake")
            .force_path_style(true)
            .request_checksum_calculation(
                aws_sdk_s3::config::RequestChecksumCalculation::WhenRequired,
            )
            .retry_config(aws_sdk_s3::config::retry::RetryConfig::disabled())
            .http_client(http.clone())
            .build();
        let sns = aws_sdk_sns::Config::builder()
            .behavior_version(aws_sdk_sns::config::BehaviorVersion::latest())
            .region(aws_sdk_sns::config::Region::new("us-east-1"))
            .credentials_provider(aws_sdk_sns::config::Credentials::new(
                "test", "test", None, None, "test",
            ))
            .endpoint_url("http://sns.fake")
            .retry_config(aws_sdk_sns::config::retry::RetryConfig::disabled())
            .http_client(http)
            .build();

        let share_fail_topic = (opts.share_event_always_fail).then(|| {
            "arn:aws:sns:us-east-1:000000000000:otterworks-file-share-notifications-v2".to_string()
        });

        let config = AppConfig {
            server: ServerConfig {
                port: 0,
                max_upload_bytes: opts.max_upload_bytes,
                upload_always_fail: opts.upload_always_fail,
                seed_demo_docs: false,
            },
            aws: AwsConfig {
                region: "us-east-1".into(),
                endpoint_url: None,
                s3_bucket: BUCKET.into(),
                dynamodb_table: FILES.into(),
                dynamodb_folders_table: FOLDERS.into(),
                dynamodb_versions_table: VERSIONS.into(),
                dynamodb_shares_table: SHARES.into(),
            },
            sns: SnsConfig {
                topic_arn: opts.topic.clone(),
                share_event_always_fail: opts.share_event_always_fail,
            },
            // Empty URL disables alert delivery: no admin-service/Slack calls.
            alerts: AlertConfig {
                admin_service_url: String::new(),
                alert_webhook_secret: None,
            },
        };

        let redis = FakeRedis::start().await;
        let redis_cm =
            redis::aio::ConnectionManager::new(redis::Client::open(redis.url.as_str()).unwrap())
                .await
                .expect("fake redis connection");

        Self {
            config: web::Data::new(config),
            s3: web::Data::new(S3Client {
                client: aws_sdk_s3::Client::from_conf(s3),
                bucket: BUCKET.into(),
            }),
            meta: web::Data::new(MetadataClient {
                client: aws_sdk_dynamodb::Client::from_conf(dynamo),
                files_table: FILES.into(),
                folders_table: FOLDERS.into(),
                versions_table: VERSIONS.into(),
                shares_table: SHARES.into(),
            }),
            events: web::Data::new(EventPublisher::from_parts(
                aws_sdk_sns::Client::from_conf(sns),
                opts.topic,
                share_fail_topic,
            )),
            redis_cm: web::Data::new(redis_cm),
            aws,
            redis,
        }
    }

    pub async fn app(
        &self,
    ) -> impl Service<
        actix_http::Request,
        Response = ServiceResponse<impl MessageBody>,
        Error = actix_web::Error,
    > {
        test::init_service(
            App::new()
                .wrap(crate::middleware::RequestId)
                .app_data(self.config.clone())
                .app_data(self.s3.clone())
                .app_data(self.meta.clone())
                .app_data(self.events.clone())
                .app_data(self.redis_cm.clone())
                .configure(crate::configure_routes),
        )
        .await
    }
}

pub const BOUNDARY: &str = "----otterworks-test-boundary";

/// A multipart part: (field name, optional filename, optional content type, bytes).
pub type Part<'a> = (&'a str, Option<&'a str>, Option<&'a str>, &'a [u8]);

pub fn multipart(parts: &[Part]) -> Vec<u8> {
    let mut body = Vec::new();
    for (name, filename, ct, data) in parts {
        body.extend_from_slice(format!("--{BOUNDARY}\r\n").as_bytes());
        let mut disp = format!("Content-Disposition: form-data; name=\"{name}\"");
        if let Some(f) = filename {
            disp.push_str(&format!("; filename=\"{f}\""));
        }
        body.extend_from_slice(disp.as_bytes());
        body.extend_from_slice(b"\r\n");
        if let Some(ct) = ct {
            body.extend_from_slice(format!("Content-Type: {ct}\r\n").as_bytes());
        }
        body.extend_from_slice(b"\r\n");
        body.extend_from_slice(data);
        body.extend_from_slice(b"\r\n");
    }
    body.extend_from_slice(format!("--{BOUNDARY}--\r\n").as_bytes());
    body
}

pub fn upload_req(user: Option<Uuid>, parts: &[Part]) -> test::TestRequest {
    let mut req = test::TestRequest::post()
        .uri("/api/v1/files/upload")
        .insert_header((
            "content-type",
            format!("multipart/form-data; boundary={BOUNDARY}"),
        ))
        .set_payload(multipart(parts));
    if let Some(u) = user {
        req = req.insert_header(("X-User-ID", u.to_string()));
    }
    req
}

/// Sends `req` and returns (status, parsed JSON body or Null).
pub async fn call<S, B>(app: &S, req: test::TestRequest) -> (u16, Value)
where
    S: Service<actix_http::Request, Response = ServiceResponse<B>, Error = actix_web::Error>,
    B: MessageBody,
{
    let resp = test::call_service(app, req.to_request()).await;
    let status = resp.status().as_u16();
    let bytes = test::read_body(resp).await;
    let json = serde_json::from_slice(&bytes).unwrap_or(Value::Null);
    (status, json)
}

/// Uploads `name` as `user` through the real route and returns the file id.
pub async fn upload<S, B>(app: &S, user: Uuid, name: &str, data: &[u8]) -> Uuid
where
    S: Service<actix_http::Request, Response = ServiceResponse<B>, Error = actix_web::Error>,
    B: MessageBody,
{
    let (status, body) = call(
        app,
        upload_req(
            Some(user),
            &[("file", Some(name), Some("text/plain"), data)],
        ),
    )
    .await;
    assert_eq!(status, 201, "upload failed: {body}");
    body["file"]["id"].as_str().unwrap().parse().unwrap()
}

pub fn as_user(req: test::TestRequest, user: Uuid) -> test::TestRequest {
    req.insert_header(("X-User-ID", user.to_string()))
}
