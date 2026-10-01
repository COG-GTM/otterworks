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

    fn image_enables_upload_always_fail(dockerfile: &str) -> bool {
        let mut logical_dockerfile = String::with_capacity(dockerfile.len());
        let mut continued = false;
        for line in dockerfile.lines() {
            let line = line.trim_end();
            if continued {
                logical_dockerfile.push_str(line.trim_start());
            } else {
                logical_dockerfile.push_str(line);
            }

            continued = line.ends_with('\\');
            if continued {
                logical_dockerfile.pop();
            } else {
                logical_dockerfile.push('\n');
            }
        }

        logical_dockerfile.lines().any(|line| {
            let mut tokens = line.split_ascii_whitespace();
            if !tokens
                .next()
                .is_some_and(|instruction| instruction.eq_ignore_ascii_case("ENV"))
            {
                return false;
            }

            while let Some(token) = tokens.next() {
                let value = if let Some((name, value)) = token.split_once('=') {
                    (name.eq_ignore_ascii_case("FILE_UPLOAD_ALWAYS_FAIL")).then_some(value)
                } else if token.eq_ignore_ascii_case("FILE_UPLOAD_ALWAYS_FAIL") {
                    tokens.next()
                } else {
                    None
                };

                if value.is_some_and(|value| parse_bool(value.trim_matches(['"', '\'']), false)) {
                    return true;
                }
            }

            false
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
    fn image_does_not_enable_upload_always_fail() {
        let dockerfile = include_str!("../Dockerfile");
        assert!(!image_enables_upload_always_fail(dockerfile));
    }

    #[test]
    fn image_guard_matches_runtime_boolean_parsing() {
        for dockerfile in [
            "ENV FILE_UPLOAD_ALWAYS_FAIL=true",
            "ENV FILE_UPLOAD_ALWAYS_FAIL 1",
            "ENV OTHER=false FILE_UPLOAD_ALWAYS_FAIL=\"TRUE\"",
            "ENV FILE_UPLOAD_ALWAYS_FAIL=\\\n    1",
            "ENV FILE_UPLOAD_ALWAYS_FAIL \\\n    true",
        ] {
            assert!(image_enables_upload_always_fail(dockerfile));
        }
        for dockerfile in [
            "ENV FILE_UPLOAD_ALWAYS_FAIL=false",
            "ENV FILE_UPLOAD_ALWAYS_FAIL 0",
        ] {
            assert!(!image_enables_upload_always_fail(dockerfile));
        }
    }
}
