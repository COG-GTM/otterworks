use std::env;

#[derive(Clone, Debug)]
pub struct AppConfig {
    pub server: ServerConfig,
    pub aws: AwsConfig,
    pub sns: SnsConfig,
}

#[derive(Clone, Debug)]
pub struct ServerConfig {
    pub port: u16,
    pub max_upload_bytes: u64,
    /// When true, every upload is routed to a nonexistent S3 bucket so the
    /// request fails with a 500. Off unless explicitly enabled per tenant.
    pub upload_always_fail: bool,
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
}

impl AppConfig {
    pub fn from_env() -> Self {
        Self {
            server: ServerConfig::from_env(),
            aws: AwsConfig::from_env(),
            sns: SnsConfig::from_env(),
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
            topic_arn: env::var("SNS_TOPIC_ARN").ok(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{parse_bool, parse_bool_env};

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
}

#[cfg(test)]
mod env_tests {
    use super::*;
    use std::sync::Mutex;

    // `std::env` is process-global: serialize every test that touches it.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    fn with_env<T>(vars: &[(&str, Option<&str>)], f: impl FnOnce() -> T) -> T {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let saved: Vec<(String, Option<String>)> = vars
            .iter()
            .map(|(k, _)| ((*k).to_string(), env::var(k).ok()))
            .collect();
        for (k, v) in vars {
            match v {
                Some(v) => env::set_var(k, v),
                None => env::remove_var(k),
            }
        }
        let out = f();
        for (k, v) in saved {
            match v {
                Some(v) => env::set_var(&k, v),
                None => env::remove_var(&k),
            }
        }
        out
    }

    const SERVER_VARS: [&str; 2] = ["PORT", "MAX_UPLOAD_BYTES"];
    const AWS_VARS: [&str; 7] = [
        "AWS_REGION",
        "AWS_ENDPOINT_URL",
        "S3_BUCKET",
        "DYNAMODB_TABLE",
        "DYNAMODB_FOLDERS_TABLE",
        "DYNAMODB_VERSIONS_TABLE",
        "DYNAMODB_SHARES_TABLE",
    ];

    fn unset(keys: &[&'static str]) -> Vec<(&'static str, Option<&'static str>)> {
        keys.iter().map(|k| (*k, None)).collect()
    }

    #[test]
    fn server_config_falls_back_to_defaults() {
        let cfg = with_env(&unset(&SERVER_VARS), ServerConfig::from_env);
        assert_eq!(cfg.port, 8082);
        assert_eq!(cfg.max_upload_bytes, 104_857_600);
    }

    #[test]
    fn server_config_reads_overrides_and_ignores_garbage() {
        let cfg = with_env(
            &[
                ("PORT", Some("9999")),
                ("MAX_UPLOAD_BYTES", Some("not-a-number")),
            ],
            ServerConfig::from_env,
        );
        assert_eq!(cfg.port, 9999);
        assert_eq!(
            cfg.max_upload_bytes, 104_857_600,
            "unparseable value falls back to the default"
        );
    }

    #[test]
    fn server_config_accepts_a_custom_upload_ceiling() {
        let cfg = with_env(
            &[("PORT", Some("bogus")), ("MAX_UPLOAD_BYTES", Some("2048"))],
            ServerConfig::from_env,
        );
        assert_eq!(cfg.port, 8082, "unparseable port falls back to the default");
        assert_eq!(cfg.max_upload_bytes, 2048);
    }

    #[test]
    fn aws_config_uses_defaults_when_nothing_is_set() {
        let cfg = with_env(&unset(&AWS_VARS), AwsConfig::from_env);
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
                ("DYNAMODB_TABLE", Some("files")),
                ("DYNAMODB_FOLDERS_TABLE", Some("folders")),
                ("DYNAMODB_VERSIONS_TABLE", Some("versions")),
                ("DYNAMODB_SHARES_TABLE", Some("shares")),
            ],
            AwsConfig::from_env,
        );
        assert_eq!(cfg.region, "eu-west-2");
        assert_eq!(cfg.endpoint_url.as_deref(), Some("http://localstack:4566"));
        assert_eq!(cfg.s3_bucket, "my-bucket");
        assert_eq!(cfg.dynamodb_table, "files");
        assert_eq!(cfg.dynamodb_folders_table, "folders");
        assert_eq!(cfg.dynamodb_versions_table, "versions");
        assert_eq!(cfg.dynamodb_shares_table, "shares");
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
    fn app_config_composes_the_three_sections() {
        let cfg = with_env(
            &[
                ("PORT", Some("1234")),
                ("S3_BUCKET", Some("composed-bucket")),
                ("SNS_TOPIC_ARN", None),
            ],
            AppConfig::from_env,
        );
        assert_eq!(cfg.server.port, 1234);
        assert_eq!(cfg.aws.s3_bucket, "composed-bucket");
        assert_eq!(cfg.sns.topic_arn, None);
    }

    #[test]
    fn parse_bool_env_reads_the_environment() {
        assert!(with_env(&[("OTTERWORKS_TEST_FLAG", Some("1"))], || {
            parse_bool_env("OTTERWORKS_TEST_FLAG", false)
        }));
        assert!(!with_env(&[("OTTERWORKS_TEST_FLAG", Some("0"))], || {
            parse_bool_env("OTTERWORKS_TEST_FLAG", true)
        }));
        assert!(with_env(&[("OTTERWORKS_TEST_FLAG", Some("maybe"))], || {
            parse_bool_env("OTTERWORKS_TEST_FLAG", true)
        }));
    }
}
