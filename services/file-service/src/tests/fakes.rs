//! In-memory fakes for the AWS services (DynamoDB, S3, SNS) and Redis that
//! file-service talks to, so handlers can be exercised end to end in
//! `cargo test` without LocalStack.

use std::collections::{HashMap, HashSet};
use std::sync::{Arc, Mutex};

use aws_smithy_types::body::SdkBody;
use serde_json::{json, Map, Value};
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};

type Item = Map<String, Value>;

#[derive(Default)]
pub struct FakeAws {
    pub tables: Mutex<HashMap<String, Vec<Item>>>,
    pub objects: Mutex<HashMap<(String, String), Vec<u8>>>,
    pub sns_published: Mutex<Vec<(String, String)>>,
}

fn key_attrs(table: &str) -> &'static [&'static str] {
    if table.contains("versions") {
        &["file_id", "version"]
    } else {
        &["id"]
    }
}

fn same_key(table: &str, a: &Item, b: &Item) -> bool {
    key_attrs(table).iter().all(|k| a.get(*k) == b.get(*k))
}

fn resolve_name(name: &str, names: &Value) -> String {
    if name.starts_with('#') {
        names[name].as_str().unwrap_or(name).to_string()
    } else {
        name.to_string()
    }
}

/// Evaluates the small subset of DynamoDB condition syntax file-service uses:
/// `a = :v`, `attribute_exists(a)`, `attribute_not_exists(a)` joined by AND.
fn matches(expr: Option<&str>, item: &Item, values: &Value, names: &Value) -> bool {
    let Some(expr) = expr else { return true };
    expr.split(" AND ").all(|clause| {
        let clause = clause.trim();
        if let Some(attr) = clause
            .strip_prefix("attribute_not_exists(")
            .and_then(|r| r.strip_suffix(')'))
        {
            !item.contains_key(&resolve_name(attr, names))
        } else if let Some(attr) = clause
            .strip_prefix("attribute_exists(")
            .and_then(|r| r.strip_suffix(')'))
        {
            item.contains_key(&resolve_name(attr, names))
        } else {
            let (lhs, rhs) = clause.split_once('=').expect("unsupported clause");
            item.get(&resolve_name(lhs.trim(), names)) == Some(&values[rhs.trim()])
        }
    })
}

fn json_response(status: u16, body: Value) -> http::Response<SdkBody> {
    http::Response::builder()
        .status(status)
        .header("content-type", "application/x-amz-json-1.0")
        .body(SdkBody::from(body.to_string()))
        .unwrap()
}

fn xml_response(status: u16, body: String) -> http::Response<SdkBody> {
    http::Response::builder()
        .status(status)
        .header("content-type", "application/xml")
        .body(SdkBody::from(body))
        .unwrap()
}

impl FakeAws {
    pub fn handle(&self, req: http::Request<SdkBody>) -> http::Response<SdkBody> {
        let host = req.uri().host().unwrap_or_default().to_string();
        if host.starts_with("dynamodb") {
            self.dynamodb(req)
        } else if host.starts_with("s3") {
            self.s3(req)
        } else if host.starts_with("sns") {
            self.sns(req)
        } else {
            panic!("unexpected AWS host {host}")
        }
    }

    pub fn table(&self, name: &str) -> Vec<Item> {
        self.tables
            .lock()
            .unwrap()
            .get(name)
            .cloned()
            .unwrap_or_default()
    }

    pub fn has_object(&self, bucket: &str, key: &str) -> bool {
        self.objects
            .lock()
            .unwrap()
            .contains_key(&(bucket.to_string(), key.to_string()))
    }

    fn dynamodb(&self, req: http::Request<SdkBody>) -> http::Response<SdkBody> {
        let target = req
            .headers()
            .get("x-amz-target")
            .and_then(|v| v.to_str().ok())
            .unwrap_or_default()
            .rsplit('.')
            .next()
            .unwrap_or_default()
            .to_string();
        let body: Value = serde_json::from_slice(req.body().bytes().unwrap_or(b"{}")).unwrap();
        let table = body["TableName"].as_str().unwrap_or_default().to_string();
        let values = body
            .get("ExpressionAttributeValues")
            .cloned()
            .unwrap_or(Value::Null);
        let names = body
            .get("ExpressionAttributeNames")
            .cloned()
            .unwrap_or(Value::Null);
        let mut tables = self.tables.lock().unwrap();
        let rows = tables.entry(table.clone()).or_default();
        match target.as_str() {
            "PutItem" => {
                let item = body["Item"].as_object().unwrap().clone();
                rows.retain(|r| !same_key(&table, r, &item));
                rows.push(item);
                json_response(200, json!({}))
            }
            "GetItem" => {
                let key = body["Key"].as_object().unwrap().clone();
                match rows.iter().find(|r| same_key(&table, r, &key)) {
                    Some(item) => json_response(200, json!({ "Item": item })),
                    None => json_response(200, json!({})),
                }
            }
            "DeleteItem" => {
                let key = body["Key"].as_object().unwrap().clone();
                rows.retain(|r| !same_key(&table, r, &key));
                json_response(200, json!({}))
            }
            "UpdateItem" => {
                let key = body["Key"].as_object().unwrap().clone();
                let pos = rows.iter().position(|r| same_key(&table, r, &key));
                let empty = Item::new();
                let current = pos.map(|p| &rows[p]).unwrap_or(&empty);
                if !matches(
                    body["ConditionExpression"].as_str(),
                    current,
                    &values,
                    &names,
                ) {
                    return json_response(
                        400,
                        json!({
                            "__type": "com.amazonaws.dynamodb.v20120810#ConditionalCheckFailedException",
                            "message": "The conditional request failed"
                        }),
                    );
                }
                let mut item = current.clone();
                for (k, v) in &key {
                    item.insert(k.clone(), v.clone());
                }
                let expr = body["UpdateExpression"].as_str().unwrap_or_default();
                let (set_part, remove_part) = match expr.split_once("REMOVE ") {
                    Some((s, r)) => (s, Some(r)),
                    None => (expr, None),
                };
                let set_part = set_part.trim().trim_start_matches("SET ").trim();
                if !set_part.is_empty() {
                    for assignment in set_part.split(',') {
                        let (lhs, rhs) = assignment.split_once('=').unwrap();
                        item.insert(resolve_name(lhs.trim(), &names), values[rhs.trim()].clone());
                    }
                }
                if let Some(remove) = remove_part {
                    for attr in remove.split(',') {
                        item.remove(&resolve_name(attr.trim(), &names));
                    }
                }
                match pos {
                    Some(p) => rows[p] = item,
                    None => rows.push(item),
                }
                json_response(200, json!({}))
            }
            "Scan" | "Query" => {
                let expr = body["FilterExpression"]
                    .as_str()
                    .or(body["KeyConditionExpression"].as_str());
                let mut items: Vec<Item> = rows
                    .iter()
                    .filter(|r| matches(expr, r, &values, &names))
                    .cloned()
                    .collect();
                if body["ScanIndexForward"] == json!(false) {
                    items.sort_by_key(|i| {
                        std::cmp::Reverse(
                            i.get("version")
                                .and_then(|v| v["N"].as_str())
                                .and_then(|n| n.parse::<u64>().ok())
                                .unwrap_or(0),
                        )
                    });
                }
                let count = items.len();
                json_response(
                    200,
                    json!({ "Items": items, "Count": count, "ScannedCount": count }),
                )
            }
            other => panic!("FakeAws: unsupported DynamoDB op {other}"),
        }
    }

    fn s3(&self, req: http::Request<SdkBody>) -> http::Response<SdkBody> {
        let path = req.uri().path().trim_start_matches('/').to_string();
        let (bucket, key) = path.split_once('/').unwrap_or((&path, ""));
        let (bucket, key) = (bucket.to_string(), key.to_string());
        if bucket.contains("nonexistent") {
            return xml_response(
                404,
                format!(
                    "<?xml version=\"1.0\" encoding=\"UTF-8\"?><Error><Code>NoSuchBucket</Code>\
                     <Message>The specified bucket does not exist</Message>\
                     <BucketName>{bucket}</BucketName></Error>"
                ),
            );
        }
        let mut objects = self.objects.lock().unwrap();
        match req.method().as_str() {
            "PUT" => {
                let data = req.body().bytes().unwrap_or_default().to_vec();
                objects.insert((bucket, key), data);
                http::Response::builder()
                    .status(200)
                    .header("ETag", "\"fake-etag\"")
                    .body(SdkBody::empty())
                    .unwrap()
            }
            "DELETE" => {
                objects.remove(&(bucket, key));
                http::Response::builder()
                    .status(204)
                    .body(SdkBody::empty())
                    .unwrap()
            }
            other => panic!("FakeAws: unsupported S3 method {other}"),
        }
    }

    fn sns(&self, req: http::Request<SdkBody>) -> http::Response<SdkBody> {
        let form = String::from_utf8_lossy(req.body().bytes().unwrap_or_default()).to_string();
        let params: HashMap<String, String> = form
            .split('&')
            .filter_map(|kv| kv.split_once('='))
            .map(|(k, v)| (k.to_string(), url_decode(v)))
            .collect();
        let topic = params.get("TopicArn").cloned().unwrap_or_default();
        if topic.ends_with("-v2") {
            return xml_response(
                404,
                "<ErrorResponse xmlns=\"http://sns.amazonaws.com/doc/2010-03-31/\"><Error>\
                 <Type>Sender</Type><Code>NotFound</Code><Message>Topic does not exist</Message>\
                 </Error><RequestId>fake</RequestId></ErrorResponse>"
                    .to_string(),
            );
        }
        self.sns_published
            .lock()
            .unwrap()
            .push((topic, params.get("Message").cloned().unwrap_or_default()));
        xml_response(
            200,
            "<PublishResponse xmlns=\"http://sns.amazonaws.com/doc/2010-03-31/\"><PublishResult>\
             <MessageId>fake-id</MessageId></PublishResult><ResponseMetadata>\
             <RequestId>fake</RequestId></ResponseMetadata></PublishResponse>"
                .to_string(),
        )
    }
}

fn url_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'+' => out.push(b' '),
            b'%' if i + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap();
                out.push(u8::from_str_radix(hex, 16).unwrap());
                i += 2;
            }
            b => out.push(b),
        }
        i += 1;
    }
    String::from_utf8_lossy(&out).to_string()
}

/// Minimal RESP server: replies `:1`/`:0` to EXISTS based on the configured
/// flags and `+OK` to anything else (handshake commands included).
pub struct FakeRedis {
    pub url: String,
    pub flags: Arc<Mutex<HashSet<String>>>,
}

impl FakeRedis {
    pub async fn start() -> Self {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("redis://{}", listener.local_addr().unwrap());
        let flags: Arc<Mutex<HashSet<String>>> = Arc::default();
        let shared = flags.clone();
        tokio::spawn(async move {
            while let Ok((socket, _)) = listener.accept().await {
                let flags = shared.clone();
                tokio::spawn(async move {
                    let (read, mut write) = socket.into_split();
                    let mut reader = BufReader::new(read);
                    while let Some(cmd) = read_command(&mut reader).await {
                        let reply = if cmd.first().map(|c| c.eq_ignore_ascii_case("EXISTS"))
                            == Some(true)
                        {
                            let set = flags.lock().unwrap();
                            let n = cmd[1..].iter().filter(|k| set.contains(*k)).count();
                            format!(":{n}\r\n")
                        } else {
                            "+OK\r\n".to_string()
                        };
                        if write.write_all(reply.as_bytes()).await.is_err() {
                            break;
                        }
                    }
                });
            }
        });
        Self { url, flags }
    }

    pub fn set_flag(&self, key: &str) {
        self.flags.lock().unwrap().insert(key.to_string());
    }
}

async fn read_command<R: tokio::io::AsyncBufRead + Unpin>(r: &mut R) -> Option<Vec<String>> {
    let mut line = String::new();
    if r.read_line(&mut line).await.ok()? == 0 {
        return None;
    }
    let n: usize = line.trim().strip_prefix('*')?.parse().ok()?;
    let mut parts = Vec::with_capacity(n);
    for _ in 0..n {
        line.clear();
        r.read_line(&mut line).await.ok()?;
        let len: usize = line.trim().strip_prefix('$')?.parse().ok()?;
        let mut buf = vec![0u8; len + 2];
        r.read_exact(&mut buf).await.ok()?;
        buf.truncate(len);
        parts.push(String::from_utf8_lossy(&buf).to_string());
    }
    Some(parts)
}
