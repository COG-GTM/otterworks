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
mod config_tests {
    use super::*;
    use crate::test_support::with_env;

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
                ("DYNAMODB_TABLE", Some("my-files")),
                ("DYNAMODB_FOLDERS_TABLE", Some("my-folders")),
                ("DYNAMODB_VERSIONS_TABLE", Some("my-versions")),
                ("DYNAMODB_SHARES_TABLE", Some("my-shares")),
            ],
            AwsConfig::from_env,
        );
        assert_eq!(cfg.region, "eu-west-2");
        assert_eq!(cfg.endpoint_url.as_deref(), Some("http://localstack:4566"));
        assert_eq!(cfg.s3_bucket, "my-bucket");
        assert_eq!(cfg.dynamodb_table, "my-files");
        assert_eq!(cfg.dynamodb_folders_table, "my-folders");
        assert_eq!(cfg.dynamodb_versions_table, "my-versions");
        assert_eq!(cfg.dynamodb_shares_table, "my-shares");
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
        let cfg = with_env(
            &[
                ("PORT", Some("7000")),
                ("MAX_UPLOAD_BYTES", None),
                ("AWS_REGION", Some("ap-south-1")),
                ("AWS_ENDPOINT_URL", None),
                ("S3_BUCKET", Some("bucket-x")),
                ("DYNAMODB_TABLE", None),
                ("DYNAMODB_FOLDERS_TABLE", None),
                ("DYNAMODB_VERSIONS_TABLE", None),
                ("DYNAMODB_SHARES_TABLE", None),
                ("SNS_TOPIC_ARN", Some("arn:aws:sns:ap-south-1:1:t")),
            ],
            AppConfig::from_env,
        );
        assert_eq!(cfg.server.port, 7000);
        assert_eq!(cfg.server.max_upload_bytes, 104_857_600);
        assert_eq!(cfg.aws.region, "ap-south-1");
        assert_eq!(cfg.aws.s3_bucket, "bucket-x");
        assert_eq!(
            cfg.sns.topic_arn.as_deref(),
            Some("arn:aws:sns:ap-south-1:1:t")
        );
    }

    #[test]
    fn app_config_is_debug_and_clone() {
        let cfg = with_env(&cleared(), AppConfig::from_env);
        let copy = cfg.clone();
        assert_eq!(copy.server.port, cfg.server.port);
        assert_eq!(copy.aws.s3_bucket, cfg.aws.s3_bucket);
        assert_eq!(copy.sns.topic_arn, cfg.sns.topic_arn);
        assert!(format!("{cfg:?}").contains("AppConfig"));
        assert!(format!("{:?}", cfg.server).contains("8082"));
        assert!(format!("{:?}", cfg.aws).contains("us-east-1"));
        assert!(format!("{:?}", cfg.sns).contains("None"));
    }
}
