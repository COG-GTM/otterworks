use std::collections::{HashMap, HashSet};
use std::io::{BufRead, BufReader, Write};
use std::sync::{Arc, Mutex};

use actix_web::{web, App, HttpRequest, HttpResponse, HttpServer};
use bytes::Bytes;
use serde_json::{json, Map, Value};

use crate::alerts::AlertConfig;
use crate::config::{AppConfig, AwsConfig, ServerConfig, SnsConfig};
use crate::events::EventPublisher;
use crate::metadata::MetadataClient;
use crate::storage::S3Client;

pub const BUCKET: &str = "test-bucket";
pub const TOPIC: &str = "arn:aws:sns:us-east-1:000000000000:file-events";

type Item = Map<String, Value>;
pub type Part<'a> = (&'a str, Option<&'a str>, Option<&'a str>, &'a [u8]);

#[derive(Default)]
pub struct FakeState {
    pub tables: HashMap<String, Vec<Item>>,
    pub objects: HashMap<(String, String), Vec<u8>>,
    pub buckets: HashSet<String>,
    pub topics: HashSet<String>,
    pub published: Vec<HashMap<String, String>>,
    pub alerts: Vec<(Option<String>, Value)>,
    pub alert_status: u16,
    pub fail: HashSet<String>,
    pub page_size: Option<usize>,
}

pub struct FakeAws {
    pub url: String,
    pub state: Arc<Mutex<FakeState>>,
}

impl FakeAws {
    pub fn start() -> Self {
        let mut st = FakeState {
            alert_status: 200,
            ..Default::default()
        };
        st.buckets.insert(BUCKET.into());
        st.topics.insert(TOPIC.into());
        let state = Arc::new(Mutex::new(st));
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let shared = state.clone();
        std::thread::spawn(move || {
            actix_web::rt::System::new().block_on(async move {
                HttpServer::new(move || {
                    App::new()
                        .app_data(web::Data::new(shared.clone()))
                        .app_data(web::PayloadConfig::new(64 << 20))
                        .default_service(web::to(dispatch))
                })
                .workers(1)
                .listen(listener)
                .unwrap()
                .run()
                .await
                .unwrap();
            });
        });
        Self {
            url: format!("http://127.0.0.1:{port}"),
            state,
        }
    }

    pub fn st(&self) -> std::sync::MutexGuard<'_, FakeState> {
        self.state.lock().unwrap()
    }

    pub fn fail(&self, key: &str) {
        self.st().fail.insert(key.into());
    }

    pub fn table(&self, name: &str) -> Vec<Item> {
        self.st().tables.get(name).cloned().unwrap_or_default()
    }

    pub fn insert_item(&self, table: &str, item: Value) {
        let item = item.as_object().unwrap().clone();
        self.st().tables.entry(table.into()).or_default().push(item);
    }

    pub async fn wait_alerts(&self, n: usize) -> Vec<(Option<String>, Value)> {
        for _ in 0..200 {
            if self.st().alerts.len() >= n {
                break;
            }
            actix_web::rt::time::sleep(std::time::Duration::from_millis(10)).await;
        }
        self.st().alerts.clone()
    }

    pub fn s3(&self) -> S3Client {
        self.s3_bucket(BUCKET)
    }

    pub fn s3_bucket(&self, bucket: &str) -> S3Client {
        let conf = aws_sdk_s3::config::Builder::new()
            .behavior_version(aws_sdk_s3::config::BehaviorVersion::latest())
            .region(aws_sdk_s3::config::Region::new("us-east-1"))
            .endpoint_url(&self.url)
            .credentials_provider(aws_sdk_s3::config::Credentials::new(
                "test", "test", None, None, "test",
            ))
            .force_path_style(true)
            .request_checksum_calculation(
                aws_sdk_s3::config::RequestChecksumCalculation::WhenRequired,
            )
            .response_checksum_validation(
                aws_sdk_s3::config::ResponseChecksumValidation::WhenRequired,
            )
            .retry_config(aws_sdk_s3::config::retry::RetryConfig::disabled())
            .build();
        S3Client {
            client: aws_sdk_s3::Client::from_conf(conf),
            bucket: bucket.into(),
        }
    }

    pub fn meta(&self) -> MetadataClient {
        let conf = aws_sdk_dynamodb::config::Builder::new()
            .behavior_version(aws_sdk_dynamodb::config::BehaviorVersion::latest())
            .region(aws_sdk_dynamodb::config::Region::new("us-east-1"))
            .endpoint_url(&self.url)
            .credentials_provider(aws_sdk_dynamodb::config::Credentials::new(
                "test", "test", None, None, "test",
            ))
            .retry_config(aws_sdk_dynamodb::config::retry::RetryConfig::disabled())
            .build();
        MetadataClient {
            client: aws_sdk_dynamodb::Client::from_conf(conf),
            files_table: "files".into(),
            folders_table: "folders".into(),
            versions_table: "versions".into(),
            shares_table: "shares".into(),
        }
    }

    pub fn events(&self, topic: Option<&str>, fail_topic: Option<&str>) -> EventPublisher {
        EventPublisher::for_test(
            sns_client(&self.url),
            topic.map(String::from),
            fail_topic.map(String::from),
        )
    }

    pub fn config(&self) -> AppConfig {
        AppConfig {
            server: ServerConfig {
                port: 0,
                max_upload_bytes: 1024,
                upload_always_fail: false,
                seed_demo_docs: false,
            },
            aws: AwsConfig {
                region: "us-east-1".into(),
                endpoint_url: Some(self.url.clone()),
                s3_bucket: BUCKET.into(),
                dynamodb_table: "files".into(),
                dynamodb_folders_table: "folders".into(),
                dynamodb_versions_table: "versions".into(),
                dynamodb_shares_table: "shares".into(),
            },
            sns: SnsConfig {
                topic_arn: Some(TOPIC.into()),
                share_event_always_fail: false,
            },
            alerts: AlertConfig {
                admin_service_url: format!("{}/", self.url),
                alert_webhook_secret: Some("s3cr3t".into()),
            },
        }
    }
}

pub fn sns_client(url: &str) -> aws_sdk_sns::Client {
    let conf = aws_sdk_sns::config::Builder::new()
        .behavior_version(aws_sdk_sns::config::BehaviorVersion::latest())
        .region(aws_sdk_sns::config::Region::new("us-east-1"))
        .endpoint_url(url)
        .credentials_provider(aws_sdk_sns::config::Credentials::new(
            "test", "test", None, None, "test",
        ))
        .retry_config(aws_sdk_sns::config::retry::RetryConfig::disabled())
        .build();
    aws_sdk_sns::Client::from_conf(conf)
}

async fn dispatch(
    req: HttpRequest,
    body: Bytes,
    state: web::Data<Arc<Mutex<FakeState>>>,
) -> HttpResponse {
    let mut st = state.lock().unwrap();
    if req.path() == "/api/v1/admin/alerts/ingest" {
        let secret = req
            .headers()
            .get("X-Alert-Secret")
            .map(|v| v.to_str().unwrap().to_string());
        st.alerts
            .push((secret, serde_json::from_slice(&body).unwrap()));
        let status = actix_web::http::StatusCode::from_u16(st.alert_status).unwrap();
        return HttpResponse::build(status).force_close().finish();
    }
    if let Some(target) = req.headers().get("x-amz-target") {
        let op = target
            .to_str()
            .unwrap()
            .rsplit('.')
            .next()
            .unwrap()
            .to_string();
        let input: Value = serde_json::from_slice(&body).unwrap();
        return dynamo(&mut st, &op, &input);
    }
    let is_form = req.headers().get("content-type").is_some_and(|v| {
        v.to_str()
            .unwrap()
            .starts_with("application/x-www-form-urlencoded")
    });
    if is_form {
        return sns(&mut st, &body);
    }
    s3(&mut st, &req, body)
}

fn ddb_err(kind: &str) -> HttpResponse {
    HttpResponse::BadRequest()
        .content_type("application/x-amz-json-1.0")
        .body(
            json!({"__type": format!("com.amazonaws.dynamodb.v20120810#{kind}"), "message": kind})
                .to_string(),
        )
}

fn ddb_ok(v: Value) -> HttpResponse {
    HttpResponse::Ok()
        .content_type("application/x-amz-json-1.0")
        .body(v.to_string())
}

fn item_key(item: &Item) -> String {
    match item.get("id") {
        Some(id) => id.to_string(),
        None => format!("{}#{}", item["file_id"], item["version"]),
    }
}

fn matches_filter(item: &Item, expr: Option<&str>, values: &Value) -> bool {
    let Some(expr) = expr else { return true };
    expr.split(" AND ").all(|term| {
        let term = term.trim();
        if let Some(attr) = term
            .strip_prefix("attribute_not_exists(")
            .and_then(|t| t.strip_suffix(')'))
        {
            return !item.contains_key(attr);
        }
        let (lhs, rhs) = term.split_once(" = ").unwrap();
        item.get(lhs.trim()) == values.get(rhs.trim())
    })
}

fn dynamo(st: &mut FakeState, op: &str, input: &Value) -> HttpResponse {
    let table = input["TableName"].as_str().unwrap_or_default().to_string();
    if st.fail.contains(op) || st.fail.contains(&format!("{op}:{table}")) {
        return ddb_err("ResourceNotFoundException");
    }
    let page_size = st.page_size;
    let rows = st.tables.entry(table).or_default();
    let values = input
        .get("ExpressionAttributeValues")
        .cloned()
        .unwrap_or(json!({}));
    match op {
        "PutItem" => {
            let item = input["Item"].as_object().unwrap().clone();
            let key = item_key(&item);
            rows.retain(|r| item_key(r) != key);
            rows.push(item);
            ddb_ok(json!({}))
        }
        "GetItem" => {
            let id = &input["Key"]["id"];
            match rows.iter().find(|r| r.get("id") == Some(id)) {
                Some(item) => ddb_ok(json!({ "Item": item })),
                None => ddb_ok(json!({})),
            }
        }
        "DeleteItem" => {
            let id = &input["Key"]["id"];
            rows.retain(|r| r.get("id") != Some(id));
            ddb_ok(json!({}))
        }
        "UpdateItem" => {
            let id = &input["Key"]["id"];
            let Some(row) = rows.iter_mut().find(|r| r.get("id") == Some(id)) else {
                return ddb_err("ConditionalCheckFailedException");
            };
            let names = input
                .get("ExpressionAttributeNames")
                .cloned()
                .unwrap_or(json!({}));
            let expr = input["UpdateExpression"].as_str().unwrap();
            let (set_part, remove_part) = match expr.split_once(" REMOVE ") {
                Some((s, r)) => (s, Some(r)),
                None => (expr, None),
            };
            for assign in set_part.trim_start_matches("SET ").split(", ") {
                let (lhs, rhs) = assign.split_once(" = ").unwrap();
                let lhs = lhs.trim();
                let attr = if lhs.starts_with('#') {
                    names[lhs].as_str().unwrap().to_string()
                } else {
                    lhs.to_string()
                };
                row.insert(attr, values[rhs.trim()].clone());
            }
            if let Some(remove) = remove_part {
                for attr in remove.split(", ") {
                    row.remove(attr.trim());
                }
            }
            ddb_ok(json!({}))
        }
        "Scan" | "Query" => {
            let expr = input
                .get("FilterExpression")
                .or_else(|| input.get("KeyConditionExpression"))
                .and_then(Value::as_str);
            let mut matched: Vec<Item> = rows
                .iter()
                .filter(|r| matches_filter(r, expr, &values))
                .cloned()
                .collect();
            if input.get("ScanIndexForward") == Some(&json!(false)) {
                matched.sort_by_key(|r| {
                    std::cmp::Reverse(r["version"]["N"].as_str().unwrap().parse::<u64>().unwrap())
                });
            }
            let offset = input["ExclusiveStartKey"]["__offset"]["N"]
                .as_str()
                .map(|n| n.parse::<usize>().unwrap())
                .unwrap_or(0);
            let size = page_size.unwrap_or(usize::MAX);
            let page: Vec<Item> = matched.iter().skip(offset).take(size).cloned().collect();
            let mut out = json!({"Items": page, "Count": page.len(), "ScannedCount": page.len()});
            if offset.saturating_add(size) < matched.len() {
                out["LastEvaluatedKey"] = json!({"__offset": {"N": (offset + size).to_string()}});
            }
            ddb_ok(out)
        }
        _ => ddb_err("UnknownOperationException"),
    }
}

fn xml_err(status: u16, code: &str) -> HttpResponse {
    HttpResponse::build(actix_web::http::StatusCode::from_u16(status).unwrap())
        .content_type("application/xml")
        .body(format!(
            "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Error><Code>{code}</Code><Message>{code}</Message><RequestId>1</RequestId></Error>"
        ))
}

fn s3(st: &mut FakeState, req: &HttpRequest, body: Bytes) -> HttpResponse {
    let path = req.path().trim_start_matches('/');
    let (bucket, key) = path.split_once('/').unwrap_or((path, ""));
    let (bucket, key) = (bucket.to_string(), key.to_string());
    if !st.buckets.contains(&bucket) {
        return xml_err(404, "NoSuchBucket");
    }
    let method = req.method().as_str().to_string();
    if let Some(src) = req.headers().get("x-amz-copy-source") {
        let src = src.to_str().unwrap().trim_start_matches('/');
        let (sb, sk) = src.split_once('/').unwrap();
        let data = st.objects.get(&(sb.to_string(), sk.to_string())).cloned();
        return match data {
            Some(d) if !st.fail.contains("s3:COPY") => {
                st.objects.insert((bucket, key), d);
                HttpResponse::Ok().content_type("application/xml").body(
                    "<?xml version=\"1.0\" encoding=\"UTF-8\"?><CopyObjectResult><ETag>\"e\"</ETag></CopyObjectResult>",
                )
            }
            _ => xml_err(404, "NoSuchKey"),
        };
    }
    if st.fail.contains(&format!("s3:{method}")) {
        return xml_err(403, "AccessDenied");
    }
    match method.as_str() {
        "PUT" => {
            st.objects.insert((bucket, key), body.to_vec());
            HttpResponse::Ok().insert_header(("ETag", "\"e\"")).finish()
        }
        "GET" => match st.objects.get(&(bucket, key)) {
            Some(d) => HttpResponse::Ok()
                .content_type("application/octet-stream")
                .body(d.clone()),
            None => xml_err(404, "NoSuchKey"),
        },
        "DELETE" => {
            st.objects.remove(&(bucket, key));
            HttpResponse::NoContent().finish()
        }
        _ => xml_err(405, "MethodNotAllowed"),
    }
}

fn sns(st: &mut FakeState, body: &[u8]) -> HttpResponse {
    let form: HashMap<String, String> = serde_urlencoded::from_bytes(body).unwrap();
    let topic = form.get("TopicArn").cloned().unwrap_or_default();
    if st.fail.contains("sns") || !st.topics.contains(&topic) {
        return HttpResponse::NotFound().content_type("text/xml").body(
            "<ErrorResponse xmlns=\"http://sns.amazonaws.com/doc/2010-03-31/\"><Error><Type>Sender</Type><Code>NotFound</Code><Message>Topic does not exist</Message></Error><RequestId>1</RequestId></ErrorResponse>",
        );
    }
    st.published.push(form);
    HttpResponse::Ok().content_type("text/xml").body(
        "<PublishResponse xmlns=\"http://sns.amazonaws.com/doc/2010-03-31/\"><PublishResult><MessageId>m-1</MessageId></PublishResult><ResponseMetadata><RequestId>1</RequestId></ResponseMetadata></PublishResponse>",
    )
}

/// Minimal RESP server: `EXISTS` answers from `flags` (or errors when
/// `broken`), every other command gets `+OK`.
pub fn start_redis(flags: Arc<Mutex<HashSet<String>>>, broken: bool) -> String {
    let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();
    std::thread::spawn(move || {
        for stream in listener.incoming() {
            let Ok(stream) = stream else { continue };
            let flags = flags.clone();
            std::thread::spawn(move || {
                let mut writer = stream.try_clone().unwrap();
                let mut reader = BufReader::new(stream);
                loop {
                    let mut line = String::new();
                    if reader.read_line(&mut line).unwrap_or(0) == 0 {
                        return;
                    }
                    let n: usize = line.trim().trim_start_matches('*').parse().unwrap_or(0);
                    let mut args = Vec::new();
                    for _ in 0..n {
                        let mut len = String::new();
                        reader.read_line(&mut len).unwrap();
                        let mut arg = String::new();
                        reader.read_line(&mut arg).unwrap();
                        args.push(arg.trim_end().to_string());
                    }
                    let reply = match args.first().map(|a| a.to_ascii_uppercase()) {
                        Some(cmd) if cmd == "EXISTS" && broken => "-ERR boom\r\n".to_string(),
                        Some(cmd) if cmd == "EXISTS" => {
                            let f = flags.lock().unwrap();
                            let hits = args[1..].iter().filter(|a| f.contains(*a)).count();
                            format!(":{hits}\r\n")
                        }
                        Some(cmd) if cmd == "PING" => "+PONG\r\n".to_string(),
                        _ => "+OK\r\n".to_string(),
                    };
                    if writer.write_all(reply.as_bytes()).is_err() {
                        return;
                    }
                }
            });
        }
    });
    format!("redis://127.0.0.1:{port}")
}

pub fn multipart(parts: &[Part]) -> (String, Vec<u8>) {
    let boundary = "XTESTBOUNDARYX";
    let mut body = Vec::new();
    for (name, filename, ctype, data) in parts {
        body.extend_from_slice(format!("--{boundary}\r\n").as_bytes());
        let mut disp = format!("Content-Disposition: form-data; name=\"{name}\"");
        if let Some(f) = filename {
            disp.push_str(&format!("; filename=\"{f}\""));
        }
        body.extend_from_slice(disp.as_bytes());
        body.extend_from_slice(b"\r\n");
        if let Some(ct) = ctype {
            body.extend_from_slice(format!("Content-Type: {ct}\r\n").as_bytes());
        }
        body.extend_from_slice(b"\r\n");
        body.extend_from_slice(data);
        body.extend_from_slice(b"\r\n");
    }
    body.extend_from_slice(format!("--{boundary}--\r\n").as_bytes());
    (format!("multipart/form-data; boundary={boundary}"), body)
}
