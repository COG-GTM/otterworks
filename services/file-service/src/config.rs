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
            alerts: AlertConfig::from_env(),
        }
    }
}

impl ServerConfig {
    pub fn from_env() -> Self {
        Self::from_vars(env::var("PORT").ok(), env::var("MAX_UPLOAD_BYTES").ok())
    }

    fn from_vars(port: Option<String>, max_upload_bytes: Option<String>) -> Self {
        Self {
            port: port.and_then(|v| v.parse().ok()).unwrap_or(8082),
            max_upload_bytes: max_upload_bytes
                .and_then(|v| v.parse().ok())
                .unwrap_or(104_857_600), // 100 MB
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
    use super::ServerConfig;

    #[test]
    fn server_config_falls_back_to_defaults_when_unset_or_unparsable() {
        for raw in [None, Some("".to_string()), Some("nope".to_string())] {
            let cfg = ServerConfig::from_vars(raw.clone(), raw);
            assert_eq!(cfg.port, 8082);
            assert_eq!(cfg.max_upload_bytes, 104_857_600);
        }
    }

    #[test]
    fn server_config_reads_provided_values() {
        let cfg = ServerConfig::from_vars(Some("9000".into()), Some("2048".into()));
        assert_eq!(cfg.port, 9000);
        assert_eq!(cfg.max_upload_bytes, 2048);
    }
}
