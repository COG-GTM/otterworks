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
        }
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
    use super::*;
    use std::sync::Mutex;

    // `std::env` is process-global: serialize every test that touches it.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    const ALL_VARS: &[&str] = &[
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

    /// Run `f` with every config env var set exactly as given (all others cleared),
    /// restoring the previous process environment afterwards.
    fn with_env<T>(vars: &[(&str, &str)], f: impl FnOnce() -> T) -> T {
        let _guard = ENV_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let saved: Vec<(&str, Option<String>)> =
            ALL_VARS.iter().map(|k| (*k, env::var(k).ok())).collect();
        for k in ALL_VARS {
            env::remove_var(k);
        }
        for (k, v) in vars {
            env::set_var(k, v);
        }
        let out = f();
        for (k, v) in saved {
            match v {
                Some(v) => env::set_var(k, v),
                None => env::remove_var(k),
            }
        }
        out
    }

    #[test]
    fn server_config_falls_back_to_defaults() {
        let cfg = with_env(&[], ServerConfig::from_env);
        assert_eq!(cfg.port, 8082);
        assert_eq!(cfg.max_upload_bytes, 104_857_600);
    }

    #[test]
    fn server_config_reads_overrides() {
        let cfg = with_env(
            &[("PORT", "9999"), ("MAX_UPLOAD_BYTES", "2048")],
            ServerConfig::from_env,
        );
        assert_eq!(cfg.port, 9999);
        assert_eq!(cfg.max_upload_bytes, 2048);
    }

    #[test]
    fn server_config_ignores_unparseable_values() {
        let cfg = with_env(
            &[("PORT", "http"), ("MAX_UPLOAD_BYTES", "not-a-number")],
            ServerConfig::from_env,
        );
        assert_eq!(cfg.port, 8082, "unparseable port falls back");
        assert_eq!(
            cfg.max_upload_bytes, 104_857_600,
            "unparseable size falls back"
        );
    }

    #[test]
    fn aws_config_falls_back_to_defaults() {
        let cfg = with_env(&[], AwsConfig::from_env);
        assert_eq!(cfg.region, "us-east-1");
        assert_eq!(cfg.endpoint_url, None);
        assert_eq!(cfg.s3_bucket, "otterworks-files");
        assert_eq!(cfg.dynamodb_table, "otterworks-file-metadata");
        assert_eq!(cfg.dynamodb_folders_table, "otterworks-folders");
        assert_eq!(cfg.dynamodb_versions_table, "otterworks-file-versions");
        assert_eq!(cfg.dynamodb_shares_table, "otterworks-file-shares");
    }

    #[test]
    fn aws_config_reads_overrides() {
        let cfg = with_env(
            &[
                ("AWS_REGION", "eu-west-2"),
                ("AWS_ENDPOINT_URL", "http://localstack:4566"),
                ("S3_BUCKET", "my-bucket"),
                ("DYNAMODB_TABLE", "files"),
                ("DYNAMODB_FOLDERS_TABLE", "folders"),
                ("DYNAMODB_VERSIONS_TABLE", "versions"),
                ("DYNAMODB_SHARES_TABLE", "shares"),
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
    fn sns_topic_arn_is_optional() {
        assert_eq!(with_env(&[], SnsConfig::from_env).topic_arn, None);
        let cfg = with_env(
            &[("SNS_TOPIC_ARN", "arn:aws:sns:us-east-1:1:files")],
            SnsConfig::from_env,
        );
        assert_eq!(
            cfg.topic_arn.as_deref(),
            Some("arn:aws:sns:us-east-1:1:files")
        );
    }

    #[test]
    fn app_config_composes_all_sections() {
        let cfg = with_env(
            &[
                ("PORT", "1234"),
                ("AWS_REGION", "ap-south-1"),
                ("SNS_TOPIC_ARN", "arn:aws:sns:ap-south-1:1:files.fifo"),
            ],
            AppConfig::from_env,
        );
        assert_eq!(cfg.server.port, 1234);
        assert_eq!(cfg.aws.region, "ap-south-1");
        assert_eq!(
            cfg.sns.topic_arn.as_deref(),
            Some("arn:aws:sns:ap-south-1:1:files.fifo")
        );
        // Clone + Debug are part of the public surface used by the actix app data.
        let cloned = cfg.clone();
        assert!(format!("{cloned:?}").contains("ap-south-1"));
    }
}
