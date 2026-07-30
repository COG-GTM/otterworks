//! `config::*::from_env` — defaults, overrides, and unparseable values.

mod support;

use file_service::config::{AppConfig, AwsConfig, ServerConfig, SnsConfig};
use support::with_env;

const ALL_VARS: [&str; 10] = [
    "PORT",
    "MAX_UPLOAD_BYTES",
    "AWS_REGION",
    "AWS_ENDPOINT_URL",
    "S3_BUCKET",
    "DYNAMODB_TABLE",
    "DYNAMODB_FOLDERS_TABLE",
    "DYNAMODB_VERSIONS_TABLE",
    "DYNAMODB_SHARES_TABLE",
    "SNS_TOPIC_ARN",
];

fn cleared() -> Vec<(&'static str, Option<&'static str>)> {
    ALL_VARS.iter().map(|k| (*k, None)).collect()
}

#[test]
fn server_config_falls_back_to_defaults() {
    let cfg = with_env(
        &[("PORT", None), ("MAX_UPLOAD_BYTES", None)],
        ServerConfig::from_env,
    );
    assert_eq!(cfg.port, 8082);
    assert_eq!(cfg.max_upload_bytes, 104_857_600);
}

#[test]
fn server_config_reads_overrides() {
    let cfg = with_env(
        &[("PORT", Some("9999")), ("MAX_UPLOAD_BYTES", Some("2048"))],
        ServerConfig::from_env,
    );
    assert_eq!(cfg.port, 9999);
    assert_eq!(cfg.max_upload_bytes, 2048);
}

#[test]
fn server_config_ignores_unparseable_values() {
    let cfg = with_env(
        &[
            ("PORT", Some("not-a-port")),
            ("MAX_UPLOAD_BYTES", Some("huge")),
        ],
        ServerConfig::from_env,
    );
    assert_eq!(cfg.port, 8082, "unparseable PORT falls back");
    assert_eq!(
        cfg.max_upload_bytes, 104_857_600,
        "unparseable MAX_UPLOAD_BYTES falls back"
    );
}

#[test]
fn aws_config_defaults_when_unset() {
    let cfg = with_env(&cleared(), AwsConfig::from_env);
    assert_eq!(cfg.region, "us-east-1");
    assert_eq!(cfg.endpoint_url, None);
    assert_eq!(cfg.s3_bucket, "otterworks-files");
    assert_eq!(cfg.dynamodb_table, "otterworks-file-metadata");
    assert_eq!(cfg.dynamodb_folders_table, "otterworks-folders");
    assert_eq!(cfg.dynamodb_versions_table, "otterworks-file-versions");
    assert_eq!(cfg.dynamodb_shares_table, "otterworks-file-shares");
}

#[test]
fn aws_config_reads_every_override() {
    let cfg = with_env(
        &[
            ("AWS_REGION", Some("eu-west-2")),
            ("AWS_ENDPOINT_URL", Some("http://localstack:4566")),
            ("S3_BUCKET", Some("my-bucket")),
            ("DYNAMODB_TABLE", Some("files-t")),
            ("DYNAMODB_FOLDERS_TABLE", Some("folders-t")),
            ("DYNAMODB_VERSIONS_TABLE", Some("versions-t")),
            ("DYNAMODB_SHARES_TABLE", Some("shares-t")),
        ],
        AwsConfig::from_env,
    );
    assert_eq!(cfg.region, "eu-west-2");
    assert_eq!(cfg.endpoint_url.as_deref(), Some("http://localstack:4566"));
    assert_eq!(cfg.s3_bucket, "my-bucket");
    assert_eq!(cfg.dynamodb_table, "files-t");
    assert_eq!(cfg.dynamodb_folders_table, "folders-t");
    assert_eq!(cfg.dynamodb_versions_table, "versions-t");
    assert_eq!(cfg.dynamodb_shares_table, "shares-t");
}

#[test]
fn sns_config_topic_arn_is_optional() {
    let unset = with_env(&[("SNS_TOPIC_ARN", None)], SnsConfig::from_env);
    assert_eq!(unset.topic_arn, None);

    let set = with_env(
        &[("SNS_TOPIC_ARN", Some("arn:aws:sns:us-east-1:1:files"))],
        SnsConfig::from_env,
    );
    assert_eq!(
        set.topic_arn.as_deref(),
        Some("arn:aws:sns:us-east-1:1:files")
    );
}

#[test]
fn app_config_composes_all_three_sections() {
    let mut vars = cleared();
    vars.retain(|(k, _)| *k != "PORT" && *k != "S3_BUCKET" && *k != "SNS_TOPIC_ARN");
    vars.push(("PORT", Some("1234")));
    vars.push(("S3_BUCKET", Some("composed-bucket")));
    vars.push(("SNS_TOPIC_ARN", Some("arn:aws:sns:us-east-1:1:topic")));

    let cfg = with_env(&vars, AppConfig::from_env);
    assert_eq!(cfg.server.port, 1234);
    assert_eq!(cfg.aws.s3_bucket, "composed-bucket");
    assert_eq!(
        cfg.sns.topic_arn.as_deref(),
        Some("arn:aws:sns:us-east-1:1:topic")
    );
}

#[test]
fn app_config_is_cloneable_and_debug_printable() {
    let cfg = with_env(&cleared(), AppConfig::from_env);
    let clone = cfg.clone();
    assert_eq!(clone.server.port, cfg.server.port);
    assert_eq!(clone.aws.region, cfg.aws.region);
    assert!(format!("{cfg:?}").contains("AppConfig"));
    assert!(format!("{:?}", cfg.server).contains("ServerConfig"));
    assert!(format!("{:?}", cfg.aws).contains("AwsConfig"));
    assert!(format!("{:?}", cfg.sns).contains("SnsConfig"));
}
