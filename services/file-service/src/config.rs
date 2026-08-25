use std::env;

use crate::alerts::AlertConfig;

#[derive(Clone, Debug)]
pub struct AppConfig {
    pub server: ServerConfig,
    pub aws: AwsConfig,
    pub sns: SnsConfig,
    pub alerts: AlertConfig,
}

#[derive(Clone, Debug)]
pub struct ServerConfig {
    pub port: u16,
    pub max_upload_bytes: u64,
    /// When true, every upload is routed to a nonexistent S3 bucket so the
    /// request fails with a 500. Off unless explicitly enabled per tenant.
    pub upload_always_fail: bool,
    /// When true, owners with no files get a few demo documents seeded on
    /// first listing, so share flows are demoable even when uploads fail.
    pub seed_demo_docs: bool,
}

#[derive(Clone, Debug)]
pub struct AwsConfig {
    pub region: String,
    pub endpoint_url: Option<String>,
    pub s3_bucket: String,
    pub dynamodb_table: String,
    pub dynamodb_folders_table: String,
    pub dynamodb_versions_table: String,
    pub dynamodb_shares_table: String,
}

#[derive(Clone, Debug)]
pub struct SnsConfig {
    pub topic_arn: Option<String>,
    /// When true, the `file_shared` event is published to a nonexistent SNS
    /// topic, so every share click fails with a real AWS SNS error. Off
    /// unless explicitly enabled per tenant.
    pub share_event_always_fail: bool,
}

impl AppConfig {
    pub fn from_env() -> Self {
        Self {
            server: ServerConfig::from_env(),
            aws: AwsConfig::from_env(),
            sns: SnsConfig::from_env(),
            alerts: AlertConfig::from_env(),
        }
    }
}

impl ServerConfig {
    pub fn from_env() -> Self {
        Self {
            port: env::var("PORT")
                .unwrap_or_else(|_| "8082".into())
                .parse()
                .unwrap_or(8082),
            max_upload_bytes: env::var("MAX_UPLOAD_BYTES")
                .unwrap_or_else(|_| "104857600".into()) // 100 MB
                .parse()
                .unwrap_or(104_857_600),
            upload_always_fail: parse_bool_env("FILE_UPLOAD_ALWAYS_FAIL", false),
            seed_demo_docs: parse_bool_env("FILE_SEED_DEMO_DOCS", false),
        }
    }
}

fn parse_bool_env(key: &str, default: bool) -> bool {
    env::var(key)
        .ok()
        .map_or(default, |raw| parse_bool(&raw, default))
}

fn parse_bool(raw: &str, default: bool) -> bool {
    match raw.trim().to_ascii_lowercase().as_str() {
        "true" | "1" => true,
        "false" | "0" => false,
        _ => default,
    }
}

impl AwsConfig {
    pub fn from_env() -> Self {
        Self {
            region: env::var("AWS_REGION").unwrap_or_else(|_| "us-east-1".into()),
            endpoint_url: env::var("AWS_ENDPOINT_URL").ok(),
            s3_bucket: env::var("S3_BUCKET").unwrap_or_else(|_| "otterworks-files".into()),
            dynamodb_table: env::var("DYNAMODB_TABLE")
                .unwrap_or_else(|_| "otterworks-file-metadata".into()),
            dynamodb_folders_table: env::var("DYNAMODB_FOLDERS_TABLE")
                .unwrap_or_else(|_| "otterworks-folders".into()),
            dynamodb_versions_table: env::var("DYNAMODB_VERSIONS_TABLE")
                .unwrap_or_else(|_| "otterworks-file-versions".into()),
            dynamodb_shares_table: env::var("DYNAMODB_SHARES_TABLE")
                .unwrap_or_else(|_| "otterworks-file-shares".into()),
        }
    }
}

impl SnsConfig {
    pub fn from_env() -> Self {
        Self {
            topic_arn: env::var("SNS_TOPIC_ARN")
                .ok()
                .filter(|s| !s.trim().is_empty()),
            share_event_always_fail: parse_bool_env("FILE_SHARE_EVENT_ALWAYS_FAIL", false),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{parse_bool, parse_bool_env};

    fn unquote(value: &str) -> &str {
        value
            .strip_prefix('"')
            .and_then(|value| value.strip_suffix('"'))
            .or_else(|| {
                value
                    .strip_prefix('\'')
                    .and_then(|value| value.strip_suffix('\''))
            })
            .unwrap_or(value)
    }

    fn upload_failure_image_default(dockerfile: &str) -> Option<&str> {
        dockerfile.lines().map(str::trim).find_map(|line| {
            let instruction = line.strip_prefix("ENV ")?.trim_start();
            let key = "FILE_UPLOAD_ALWAYS_FAIL";
            let value = if let Some(remainder) = instruction.strip_prefix(key) {
                let first = remainder.chars().next()?;
                if first == '=' {
                    Some(&remainder[1..])
                } else if first.is_whitespace() {
                    Some(remainder.trim_start())
                } else {
                    None
                }
            } else {
                instruction.split_ascii_whitespace().find_map(|assignment| {
                    let (name, value) = assignment.split_once('=')?;
                    (name == key).then_some(value)
                })
            }?;

            Some(unquote(value.trim()))
        })
    }

    #[test]
    fn parse_bool_accepts_true_and_one() {
        for raw in ["true", "TRUE", " True ", "1"] {
            assert!(parse_bool(raw, false), "raw={raw}");
        }
    }

    #[test]
    fn parse_bool_accepts_false_and_zero() {
        for raw in ["false", "FALSE", " False ", "0"] {
            assert!(!parse_bool(raw, true), "raw={raw}");
        }
    }

    #[test]
    fn parse_bool_falls_back_to_default_on_empty_or_garbage() {
        for raw in ["", "  ", "yes"] {
            assert!(!parse_bool(raw, false), "raw={raw}");
            assert!(parse_bool(raw, true), "raw={raw}");
        }
    }

    #[test]
    fn parse_bool_env_defaults_when_unset() {
        assert!(!parse_bool_env(
            "OTTERWORKS_DEFINITELY_UNSET_ENV_VAR",
            false
        ));
        assert!(parse_bool_env("OTTERWORKS_DEFINITELY_UNSET_ENV_VAR", true));
    }

    #[test]
    fn upload_always_fail_is_off_by_default() {
        if std::env::var("FILE_UPLOAD_ALWAYS_FAIL").is_ok() {
            return;
        }
        assert!(!super::ServerConfig::from_env().upload_always_fail);
    }

    #[test]
    fn image_does_not_enable_upload_failure_by_default() {
        let dockerfile = include_str!("../Dockerfile");

        assert!(
            !upload_failure_image_default(dockerfile).is_some_and(|value| parse_bool(value, false)),
            "file-service image must not force uploads to fail"
        );
    }

    #[test]
    fn upload_failure_image_default_accepts_docker_env_syntaxes() {
        for dockerfile in [
            "ENV FILE_UPLOAD_ALWAYS_FAIL=true",
            "ENV FILE_UPLOAD_ALWAYS_FAIL true",
            "ENV FILE_UPLOAD_ALWAYS_FAIL=\"true\"",
            "ENV FILE_UPLOAD_ALWAYS_FAIL='true'",
            "ENV FOO=bar FILE_UPLOAD_ALWAYS_FAIL=true",
        ] {
            assert_eq!(upload_failure_image_default(dockerfile), Some("true"));
        }
    }
}
