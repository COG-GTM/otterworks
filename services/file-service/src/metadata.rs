use aws_sdk_dynamodb::types::AttributeValue;
use chrono::{DateTime, Duration, Utc};
use uuid::Uuid;

use crate::config::AwsConfig;
use crate::errors::ServiceError;
use crate::models::{FileMetadata, FileShare, FileVersion, Folder, SharePermission};

/// How long a trashed item stays recoverable before it is purged.
pub const TRASH_RETENTION_DAYS: i64 = 30;

/// Label shown for items that were deleted from the root of the file browser.
pub const ROOT_LOCATION_LABEL: &str = "My Files";

/// Label shown when the folder an item was deleted from no longer exists.
pub const MISSING_FOLDER_LOCATION_LABEL: &str = "My Files (original folder deleted)";

/// Oldest `trashed_at` that is still inside the retention window.
pub fn trash_retention_cutoff(now: DateTime<Utc>) -> DateTime<Utc> {
    now - Duration::days(TRASH_RETENTION_DAYS)
}

/// Whether a trashed item has outlived the retention window.
///
/// Items without a `trashed_at` (trashed before deletion timestamps were
/// recorded) are kept rather than purged.
pub fn is_trash_expired(trashed_at: Option<DateTime<Utc>>, now: DateTime<Utc>) -> bool {
    match trashed_at {
        Some(at) => at <= trash_retention_cutoff(now),
        None => false,
    }
}

/// Trashed items still inside the retention window, newest deletion first.
pub fn retained_trash(mut files: Vec<FileMetadata>, now: DateTime<Utc>) -> Vec<FileMetadata> {
    files.retain(|f| !is_trash_expired(f.trashed_at, now));
    files.sort_by_key(|f| std::cmp::Reverse(f.trashed_at.unwrap_or(f.updated_at)));
    files
}

/// Trashed items whose retention window has elapsed, ready to be purged.
pub fn expired_trash(mut files: Vec<FileMetadata>, now: DateTime<Utc>) -> Vec<FileMetadata> {
    files.retain(|f| is_trash_expired(f.trashed_at, now));
    files
}

/// Folder an item is restored into: its original folder when that folder still
/// exists, otherwise the root.
pub fn restore_target_folder(
    trashed_from_folder_id: Option<Uuid>,
    original_folder_exists: bool,
) -> Option<Uuid> {
    match trashed_from_folder_id {
        Some(fid) if original_folder_exists => Some(fid),
        _ => None,
    }
}

/// Human-readable original location of a trashed item, and whether the folder
/// it was deleted from has since disappeared.
pub fn original_location_label(
    trashed_from_folder_id: Option<Uuid>,
    folder_name: Option<&str>,
) -> (String, bool) {
    match (trashed_from_folder_id, folder_name) {
        (Some(_), Some(name)) => (name.to_string(), false),
        (Some(_), None) => (MISSING_FOLDER_LOCATION_LABEL.to_string(), true),
        (None, _) => (ROOT_LOCATION_LABEL.to_string(), false),
    }
}

/// Build a DynamoDB update expression from SET and REMOVE clauses.
fn update_expression(set_parts: &[String], remove_parts: &[String]) -> String {
    let mut expr = String::new();
    if !set_parts.is_empty() {
        expr.push_str(&format!("SET {}", set_parts.join(", ")));
    }
    if !remove_parts.is_empty() {
        if !expr.is_empty() {
            expr.push(' ');
        }
        expr.push_str(&format!("REMOVE {}", remove_parts.join(", ")));
    }
    expr
}

/// Check if an AWS SDK error is a ConditionalCheckFailedException.
fn is_conditional_check_failed<E: std::fmt::Debug>(
    err: &aws_sdk_dynamodb::error::SdkError<E>,
) -> bool {
    matches!(err, aws_sdk_dynamodb::error::SdkError::ServiceError(se)
        if format!("{:?}", se.err()).contains("ConditionalCheckFailed"))
}

/// Client for DynamoDB metadata operations.
#[derive(Clone)]
pub struct MetadataClient {
    pub client: aws_sdk_dynamodb::Client,
    pub files_table: String,
    pub folders_table: String,
    pub versions_table: String,
    pub shares_table: String,
}

impl MetadataClient {
    pub async fn new(config: &AwsConfig) -> Self {
        let mut aws_config_builder = aws_config::defaults(aws_config::BehaviorVersion::latest())
            .region(aws_config::Region::new(config.region.clone()));

        if let Some(endpoint) = &config.endpoint_url {
            aws_config_builder = aws_config_builder.endpoint_url(endpoint);
        }

        let aws_config = aws_config_builder.load().await;
        let client = aws_sdk_dynamodb::Client::new(&aws_config);

        Self {
            client,
            files_table: config.dynamodb_table.clone(),
            folders_table: config.dynamodb_folders_table.clone(),
            versions_table: config.dynamodb_versions_table.clone(),
            shares_table: config.dynamodb_shares_table.clone(),
        }
    }

    // -- File Metadata --

    pub async fn put_file(&self, file: &FileMetadata) -> Result<(), ServiceError> {
        let mut item = std::collections::HashMap::new();
        item.insert("id".into(), AttributeValue::S(file.id.to_string()));
        item.insert("name".into(), AttributeValue::S(file.name.clone()));
        item.insert(
            "mime_type".into(),
            AttributeValue::S(file.mime_type.clone()),
        );
        item.insert(
            "size_bytes".into(),
            AttributeValue::N(file.size_bytes.to_string()),
        );
        item.insert("s3_key".into(), AttributeValue::S(file.s3_key.clone()));
        item.insert(
            "owner_id".into(),
            AttributeValue::S(file.owner_id.to_string()),
        );
        item.insert(
            "version".into(),
            AttributeValue::N(file.version.to_string()),
        );
        item.insert("is_trashed".into(), AttributeValue::Bool(file.is_trashed));
        item.insert(
            "created_at".into(),
            AttributeValue::S(file.created_at.to_rfc3339()),
        );
        item.insert(
            "updated_at".into(),
            AttributeValue::S(file.updated_at.to_rfc3339()),
        );

        if let Some(folder_id) = &file.folder_id {
            item.insert("folder_id".into(), AttributeValue::S(folder_id.to_string()));
        }
        if let Some(trashed_at) = &file.trashed_at {
            item.insert(
                "trashed_at".into(),
                AttributeValue::S(trashed_at.to_rfc3339()),
            );
        }
        if let Some(trashed_by) = &file.trashed_by {
            item.insert(
                "trashed_by".into(),
                AttributeValue::S(trashed_by.to_string()),
            );
        }
        if let Some(email) = &file.trashed_by_email {
            item.insert("trashed_by_email".into(), AttributeValue::S(email.clone()));
        }
        if let Some(from) = &file.trashed_from_folder_id {
            item.insert(
                "trashed_from_folder_id".into(),
                AttributeValue::S(from.to_string()),
            );
        }

        self.client
            .put_item()
            .table_name(&self.files_table)
            .set_item(Some(item))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;

        Ok(())
    }

    pub async fn get_file(&self, file_id: &Uuid) -> Result<FileMetadata, ServiceError> {
        let result = self
            .client
            .get_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;

        let item = result
            .item()
            .ok_or_else(|| ServiceError::FileNotFound(file_id.to_string()))?;

        parse_file_metadata(item)
    }

    /// Delete a file's metadata only while it is still trashed and still past
    /// the retention window, so a purge sweep cannot remove a record that was
    /// restored after the sweep selected it. Returns whether the row was
    /// deleted.
    pub async fn delete_expired_trashed_file(
        &self,
        file_id: &Uuid,
        now: DateTime<Utc>,
    ) -> Result<bool, ServiceError> {
        let cutoff = trash_retention_cutoff(now);
        let result = self
            .client
            .delete_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .condition_expression(
                "attribute_exists(id) AND is_trashed = :t AND trashed_at <= :cutoff",
            )
            .expression_attribute_values(":t", AttributeValue::Bool(true))
            .expression_attribute_values(":cutoff", AttributeValue::S(cutoff.to_rfc3339()))
            .send()
            .await;

        match result {
            Ok(_) => Ok(true),
            Err(e) if is_conditional_check_failed(&e) => Ok(false),
            Err(e) => Err(ServiceError::DynamoError(e.to_string())),
        }
    }

    pub async fn delete_file(&self, file_id: &Uuid) -> Result<(), ServiceError> {
        self.client
            .delete_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;
        Ok(())
    }

    /// Trash a file, recording who deleted it, when, and the folder it came
    /// from so it can be restored to its original location.
    pub async fn trash_file(
        &self,
        file_id: &Uuid,
        trashed_by: Option<Uuid>,
        trashed_by_email: Option<&str>,
    ) -> Result<FileMetadata, ServiceError> {
        let now = Utc::now();
        let file = self.get_file(file_id).await?;

        let mut set_parts = vec![
            "is_trashed = :t".to_string(),
            "updated_at = :u".to_string(),
            "trashed_at = :ta".to_string(),
        ];
        let mut remove_parts: Vec<String> = Vec::new();
        let mut builder = self
            .client
            .update_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .condition_expression("attribute_exists(id)")
            .expression_attribute_values(":t", AttributeValue::Bool(true))
            .expression_attribute_values(":u", AttributeValue::S(now.to_rfc3339()))
            .expression_attribute_values(":ta", AttributeValue::S(now.to_rfc3339()));

        if let Some(by) = &trashed_by {
            set_parts.push("trashed_by = :tb".to_string());
            builder = builder.expression_attribute_values(":tb", AttributeValue::S(by.to_string()));
        } else {
            remove_parts.push("trashed_by".to_string());
        }
        if let Some(email) = trashed_by_email {
            set_parts.push("trashed_by_email = :te".to_string());
            builder =
                builder.expression_attribute_values(":te", AttributeValue::S(email.to_string()));
        } else {
            remove_parts.push("trashed_by_email".to_string());
        }
        if let Some(from) = &file.folder_id {
            set_parts.push("trashed_from_folder_id = :tf".to_string());
            builder =
                builder.expression_attribute_values(":tf", AttributeValue::S(from.to_string()));
        } else {
            remove_parts.push("trashed_from_folder_id".to_string());
        }

        builder
            .update_expression(update_expression(&set_parts, &remove_parts))
            .send()
            .await
            .map_err(|e| {
                if is_conditional_check_failed(&e) {
                    return ServiceError::FileNotFound(file_id.to_string());
                }
                ServiceError::DynamoError(e.to_string())
            })?;

        self.get_file(file_id).await
    }

    /// Restore a trashed file to the folder it was deleted from, falling back
    /// to the root when that folder no longer exists.
    pub async fn restore_file(&self, file_id: &Uuid) -> Result<FileMetadata, ServiceError> {
        let now = Utc::now();
        let file = self.get_file(file_id).await?;
        if !file.is_trashed {
            return Ok(file);
        }
        let original_folder_exists = match file.trashed_from_folder_id {
            Some(fid) => match self.get_folder(&fid).await {
                Ok(_) => true,
                Err(ServiceError::FolderNotFound(_)) => false,
                Err(e) => return Err(e),
            },
            None => false,
        };
        let target_folder =
            restore_target_folder(file.trashed_from_folder_id, original_folder_exists);

        let mut set_parts = vec!["is_trashed = :t".to_string(), "updated_at = :u".to_string()];
        let mut remove_parts = vec![
            "trashed_at".to_string(),
            "trashed_by".to_string(),
            "trashed_by_email".to_string(),
            "trashed_from_folder_id".to_string(),
        ];
        let mut builder = self
            .client
            .update_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .condition_expression("attribute_exists(id) AND is_trashed = :was")
            .expression_attribute_values(":t", AttributeValue::Bool(false))
            .expression_attribute_values(":was", AttributeValue::Bool(true))
            .expression_attribute_values(":u", AttributeValue::S(now.to_rfc3339()));

        match target_folder {
            Some(fid) => {
                set_parts.push("folder_id = :f".to_string());
                builder =
                    builder.expression_attribute_values(":f", AttributeValue::S(fid.to_string()));
            }
            None => remove_parts.push("folder_id".to_string()),
        }

        builder
            .update_expression(update_expression(&set_parts, &remove_parts))
            .send()
            .await
            .map_err(|e| {
                if is_conditional_check_failed(&e) {
                    return ServiceError::FileNotFound(file_id.to_string());
                }
                ServiceError::DynamoError(e.to_string())
            })?;

        self.get_file(file_id).await
    }

    pub async fn rename_file(
        &self,
        file_id: &Uuid,
        name: &str,
    ) -> Result<FileMetadata, ServiceError> {
        let now = Utc::now();
        self.client
            .update_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .update_expression("SET #n = :n, updated_at = :u")
            .condition_expression("attribute_exists(id)")
            .expression_attribute_names("#n", "name")
            .expression_attribute_values(":n", AttributeValue::S(name.to_string()))
            .expression_attribute_values(":u", AttributeValue::S(now.to_rfc3339()))
            .send()
            .await
            .map_err(|e| {
                if is_conditional_check_failed(&e) {
                    return ServiceError::FileNotFound(file_id.to_string());
                }
                ServiceError::DynamoError(e.to_string())
            })?;

        self.get_file(file_id).await
    }

    pub async fn move_file(
        &self,
        file_id: &Uuid,
        folder_id: Option<Uuid>,
    ) -> Result<FileMetadata, ServiceError> {
        let now = Utc::now();
        let mut update_builder = self
            .client
            .update_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .condition_expression("attribute_exists(id)")
            .expression_attribute_values(":u", AttributeValue::S(now.to_rfc3339()));

        if let Some(fid) = &folder_id {
            update_builder = update_builder
                .update_expression("SET folder_id = :f, updated_at = :u")
                .expression_attribute_values(":f", AttributeValue::S(fid.to_string()));
        } else {
            update_builder =
                update_builder.update_expression("SET updated_at = :u REMOVE folder_id");
        }

        update_builder.send().await.map_err(|e| {
            if is_conditional_check_failed(&e) {
                return ServiceError::FileNotFound(file_id.to_string());
            }
            ServiceError::DynamoError(e.to_string())
        })?;

        self.get_file(file_id).await
    }

    /// List trashed files still inside the 30 day retention window, newest
    /// deletion first.
    pub async fn list_trashed(
        &self,
        owner_id: Option<Uuid>,
    ) -> Result<Vec<FileMetadata>, ServiceError> {
        let files = self.scan_trashed(owner_id).await?;
        Ok(retained_trash(files, Utc::now()))
    }

    /// List trashed files whose retention window has elapsed.
    pub async fn list_expired_trashed(
        &self,
        now: DateTime<Utc>,
    ) -> Result<Vec<FileMetadata>, ServiceError> {
        let files = self.scan_trashed(None).await?;
        Ok(expired_trash(files, now))
    }

    async fn scan_trashed(
        &self,
        owner_id: Option<Uuid>,
    ) -> Result<Vec<FileMetadata>, ServiceError> {
        let mut filter_parts = vec!["is_trashed = :trashed".to_string()];
        let mut scan_builder = self
            .client
            .scan()
            .table_name(&self.files_table)
            .expression_attribute_values(":trashed", AttributeValue::Bool(true));

        if let Some(oid) = &owner_id {
            filter_parts.push("owner_id = :owner_id".to_string());
            scan_builder = scan_builder
                .expression_attribute_values(":owner_id", AttributeValue::S(oid.to_string()));
        }

        scan_builder = scan_builder.filter_expression(filter_parts.join(" AND "));

        let mut paginator = scan_builder.into_paginator().send();
        let mut files = Vec::new();
        while let Some(page) = paginator.next().await {
            let page = page.map_err(|e| ServiceError::DynamoError(e.to_string()))?;
            if let Some(items) = page.items {
                for item in &items {
                    files.push(parse_file_metadata(item)?);
                }
            }
        }

        Ok(files)
    }

    pub async fn list_files(
        &self,
        folder_id: Option<Uuid>,
        owner_id: Option<Uuid>,
        include_trashed: bool,
    ) -> Result<Vec<FileMetadata>, ServiceError> {
        let mut scan_builder = self.client.scan().table_name(&self.files_table);

        let mut filter_parts: Vec<String> = Vec::new();

        if let Some(fid) = &folder_id {
            filter_parts.push("folder_id = :folder_id".to_string());
            scan_builder = scan_builder
                .expression_attribute_values(":folder_id", AttributeValue::S(fid.to_string()));
        }
        if let Some(oid) = &owner_id {
            filter_parts.push("owner_id = :owner_id".to_string());
            scan_builder = scan_builder
                .expression_attribute_values(":owner_id", AttributeValue::S(oid.to_string()));
        }
        if !include_trashed {
            filter_parts.push("is_trashed = :trashed".to_string());
            scan_builder =
                scan_builder.expression_attribute_values(":trashed", AttributeValue::Bool(false));
        }

        if !filter_parts.is_empty() {
            scan_builder = scan_builder.filter_expression(filter_parts.join(" AND "));
        }

        // Use the SDK paginator to handle DynamoDB's 1MB-per-Scan limit automatically
        let mut paginator = scan_builder.into_paginator().send();
        let mut files = Vec::new();
        while let Some(page) = paginator.next().await {
            let page = page.map_err(|e| ServiceError::DynamoError(e.to_string()))?;
            for item in page.items() {
                files.push(parse_file_metadata(item)?);
            }
        }
        Ok(files)
    }

    // -- Folder --

    pub async fn put_folder(&self, folder: &Folder) -> Result<(), ServiceError> {
        let mut item = std::collections::HashMap::new();
        item.insert("id".into(), AttributeValue::S(folder.id.to_string()));
        item.insert("name".into(), AttributeValue::S(folder.name.clone()));
        item.insert(
            "owner_id".into(),
            AttributeValue::S(folder.owner_id.to_string()),
        );
        item.insert(
            "created_at".into(),
            AttributeValue::S(folder.created_at.to_rfc3339()),
        );
        item.insert(
            "updated_at".into(),
            AttributeValue::S(folder.updated_at.to_rfc3339()),
        );

        if let Some(pid) = &folder.parent_id {
            item.insert("parent_id".into(), AttributeValue::S(pid.to_string()));
        }

        self.client
            .put_item()
            .table_name(&self.folders_table)
            .set_item(Some(item))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;

        Ok(())
    }

    pub async fn get_folder(&self, folder_id: &Uuid) -> Result<Folder, ServiceError> {
        let result = self
            .client
            .get_item()
            .table_name(&self.folders_table)
            .key("id", AttributeValue::S(folder_id.to_string()))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;

        let item = result
            .item()
            .ok_or_else(|| ServiceError::FolderNotFound(folder_id.to_string()))?;

        parse_folder(item)
    }

    pub async fn update_folder(
        &self,
        folder_id: &Uuid,
        name: Option<String>,
        parent_id: Option<Uuid>,
    ) -> Result<Folder, ServiceError> {
        let now = Utc::now();
        let mut update_parts = vec!["updated_at = :u".to_string()];
        let mut builder = self
            .client
            .update_item()
            .table_name(&self.folders_table)
            .key("id", AttributeValue::S(folder_id.to_string()))
            .condition_expression("attribute_exists(id)")
            .expression_attribute_values(":u", AttributeValue::S(now.to_rfc3339()));

        if let Some(n) = &name {
            update_parts.push("#n = :n".to_string());
            builder = builder
                .expression_attribute_names("#n", "name")
                .expression_attribute_values(":n", AttributeValue::S(n.clone()));
        }
        if let Some(pid) = &parent_id {
            update_parts.push("parent_id = :p".to_string());
            builder = builder.expression_attribute_values(":p", AttributeValue::S(pid.to_string()));
        }

        builder = builder.update_expression(format!("SET {}", update_parts.join(", ")));

        builder.send().await.map_err(|e| {
            if is_conditional_check_failed(&e) {
                return ServiceError::FolderNotFound(folder_id.to_string());
            }
            ServiceError::DynamoError(e.to_string())
        })?;

        self.get_folder(folder_id).await
    }

    pub async fn delete_folder(&self, folder_id: &Uuid) -> Result<(), ServiceError> {
        self.client
            .delete_item()
            .table_name(&self.folders_table)
            .key("id", AttributeValue::S(folder_id.to_string()))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;
        Ok(())
    }

    pub async fn list_folders(
        &self,
        parent_id: Option<Uuid>,
        owner_id: Option<Uuid>,
    ) -> Result<Vec<Folder>, ServiceError> {
        let mut scan_builder = self.client.scan().table_name(&self.folders_table);

        let mut filter_parts: Vec<String> = Vec::new();

        match &parent_id {
            Some(pid) => {
                filter_parts.push("parent_id = :parent_id".to_string());
                scan_builder = scan_builder
                    .expression_attribute_values(":parent_id", AttributeValue::S(pid.to_string()));
            }
            None => {
                filter_parts.push("attribute_not_exists(parent_id)".to_string());
            }
        }
        if let Some(oid) = &owner_id {
            filter_parts.push("owner_id = :owner_id".to_string());
            scan_builder = scan_builder
                .expression_attribute_values(":owner_id", AttributeValue::S(oid.to_string()));
        }

        if !filter_parts.is_empty() {
            scan_builder = scan_builder.filter_expression(filter_parts.join(" AND "));
        }

        let mut paginator = scan_builder.into_paginator().send();
        let mut folders = Vec::new();
        while let Some(page) = paginator.next().await {
            let page = page.map_err(|e| ServiceError::DynamoError(e.to_string()))?;
            for item in page.items() {
                folders.push(parse_folder(item)?);
            }
        }
        Ok(folders)
    }

    // -- File Versions --

    pub async fn put_version(&self, version: &FileVersion) -> Result<(), ServiceError> {
        let mut item = std::collections::HashMap::new();
        item.insert(
            "file_id".into(),
            AttributeValue::S(version.file_id.to_string()),
        );
        item.insert(
            "version".into(),
            AttributeValue::N(version.version.to_string()),
        );
        item.insert("s3_key".into(), AttributeValue::S(version.s3_key.clone()));
        item.insert(
            "size_bytes".into(),
            AttributeValue::N(version.size_bytes.to_string()),
        );
        item.insert(
            "created_by".into(),
            AttributeValue::S(version.created_by.to_string()),
        );
        item.insert(
            "created_at".into(),
            AttributeValue::S(version.created_at.to_rfc3339()),
        );

        self.client
            .put_item()
            .table_name(&self.versions_table)
            .set_item(Some(item))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;

        Ok(())
    }

    pub async fn list_versions(&self, file_id: &Uuid) -> Result<Vec<FileVersion>, ServiceError> {
        let result = self
            .client
            .query()
            .table_name(&self.versions_table)
            .key_condition_expression("file_id = :fid")
            .expression_attribute_values(":fid", AttributeValue::S(file_id.to_string()))
            .scan_index_forward(false)
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;

        let items = result.items();
        let mut versions = Vec::with_capacity(items.len());
        for item in items {
            versions.push(parse_file_version(item)?);
        }
        Ok(versions)
    }

    // -- File Shares --

    pub async fn put_share(&self, share: &FileShare) -> Result<(), ServiceError> {
        let mut item = std::collections::HashMap::new();
        item.insert("id".into(), AttributeValue::S(share.id.to_string()));
        item.insert(
            "file_id".into(),
            AttributeValue::S(share.file_id.to_string()),
        );
        item.insert(
            "shared_with".into(),
            AttributeValue::S(share.shared_with.to_string()),
        );
        item.insert(
            "permission".into(),
            AttributeValue::S(share.permission.to_string()),
        );
        item.insert(
            "shared_by".into(),
            AttributeValue::S(share.shared_by.to_string()),
        );
        item.insert(
            "created_at".into(),
            AttributeValue::S(share.created_at.to_rfc3339()),
        );

        self.client
            .put_item()
            .table_name(&self.shares_table)
            .set_item(Some(item))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;

        Ok(())
    }

    pub async fn find_existing_share(
        &self,
        file_id: &Uuid,
        shared_with: &Uuid,
    ) -> Result<Option<FileShare>, ServiceError> {
        let mut paginator = self
            .client
            .scan()
            .table_name(&self.shares_table)
            .filter_expression("file_id = :fid AND shared_with = :uid")
            .expression_attribute_values(":fid", AttributeValue::S(file_id.to_string()))
            .expression_attribute_values(":uid", AttributeValue::S(shared_with.to_string()))
            .into_paginator()
            .items()
            .send();

        if let Some(item) = paginator.next().await {
            let item = item.map_err(|e| ServiceError::DynamoError(e.to_string()))?;
            return Ok(Some(parse_file_share(&item)?));
        }
        Ok(None)
    }

    pub async fn list_shares_for_user(
        &self,
        user_id: &Uuid,
    ) -> Result<Vec<FileShare>, ServiceError> {
        let mut paginator = self
            .client
            .scan()
            .table_name(&self.shares_table)
            .filter_expression("shared_with = :uid")
            .expression_attribute_values(":uid", AttributeValue::S(user_id.to_string()))
            .into_paginator()
            .send();

        let mut shares = Vec::new();
        while let Some(page) = paginator.next().await {
            let page = page.map_err(|e| ServiceError::DynamoError(e.to_string()))?;
            if let Some(items) = page.items {
                for item in &items {
                    shares.push(parse_file_share(item)?);
                }
            }
        }
        Ok(shares)
    }

    pub async fn list_shares_by_owner(
        &self,
        owner_id: &Uuid,
    ) -> Result<Vec<FileShare>, ServiceError> {
        let mut paginator = self
            .client
            .scan()
            .table_name(&self.shares_table)
            .filter_expression("shared_by = :uid")
            .expression_attribute_values(":uid", AttributeValue::S(owner_id.to_string()))
            .into_paginator()
            .items()
            .send();

        let mut shares = Vec::new();
        while let Some(item) = paginator.next().await {
            let item = item.map_err(|e| ServiceError::DynamoError(e.to_string()))?;
            shares.push(parse_file_share(&item)?);
        }
        Ok(shares)
    }

    pub async fn delete_share(&self, share_id: &Uuid) -> Result<(), ServiceError> {
        self.client
            .delete_item()
            .table_name(&self.shares_table)
            .key("id", AttributeValue::S(share_id.to_string()))
            .send()
            .await
            .map_err(|e| ServiceError::DynamoError(e.to_string()))?;
        Ok(())
    }

    pub async fn list_shares(&self, file_id: &Uuid) -> Result<Vec<FileShare>, ServiceError> {
        let mut shares = Vec::new();
        let mut paginator = self
            .client
            .scan()
            .table_name(&self.shares_table)
            .filter_expression("file_id = :fid")
            .expression_attribute_values(":fid", AttributeValue::S(file_id.to_string()))
            .into_paginator()
            .items()
            .send();

        while let Some(item) = paginator.next().await {
            let item = item.map_err(|e| ServiceError::DynamoError(e.to_string()))?;
            shares.push(parse_file_share(&item)?);
        }
        Ok(shares)
    }
}

// -- Parsing helpers --

fn get_s(
    item: &std::collections::HashMap<String, AttributeValue>,
    key: &str,
) -> Result<String, ServiceError> {
    item.get(key)
        .and_then(|v| v.as_s().ok())
        .map(|s| s.to_string())
        .ok_or_else(|| ServiceError::DynamoError(format!("missing field: {key}")))
}

fn get_n_u64(
    item: &std::collections::HashMap<String, AttributeValue>,
    key: &str,
) -> Result<u64, ServiceError> {
    item.get(key)
        .and_then(|v| v.as_n().ok())
        .and_then(|n| n.parse::<u64>().ok())
        .ok_or_else(|| ServiceError::DynamoError(format!("missing numeric field: {key}")))
}

fn get_n_u32(
    item: &std::collections::HashMap<String, AttributeValue>,
    key: &str,
) -> Result<u32, ServiceError> {
    item.get(key)
        .and_then(|v| v.as_n().ok())
        .and_then(|n| n.parse::<u32>().ok())
        .ok_or_else(|| ServiceError::DynamoError(format!("missing numeric field: {key}")))
}

fn get_bool(
    item: &std::collections::HashMap<String, AttributeValue>,
    key: &str,
) -> Result<bool, ServiceError> {
    item.get(key)
        .and_then(|v| v.as_bool().ok())
        .copied()
        .ok_or_else(|| ServiceError::DynamoError(format!("missing bool field: {key}")))
}

fn get_optional_s(
    item: &std::collections::HashMap<String, AttributeValue>,
    key: &str,
) -> Option<String> {
    item.get(key)
        .and_then(|v| v.as_s().ok())
        .map(|s| s.to_string())
}

fn parse_uuid(s: &str) -> Result<uuid::Uuid, ServiceError> {
    s.parse::<uuid::Uuid>()
        .map_err(|e| ServiceError::DynamoError(format!("invalid UUID: {e}")))
}

fn parse_datetime(s: &str) -> Result<chrono::DateTime<chrono::Utc>, ServiceError> {
    chrono::DateTime::parse_from_rfc3339(s)
        .map(|dt| dt.with_timezone(&chrono::Utc))
        .map_err(|e| ServiceError::DynamoError(format!("invalid datetime: {e}")))
}

fn parse_file_metadata(
    item: &std::collections::HashMap<String, AttributeValue>,
) -> Result<FileMetadata, ServiceError> {
    Ok(FileMetadata {
        id: parse_uuid(&get_s(item, "id")?)?,
        name: get_s(item, "name")?,
        mime_type: get_s(item, "mime_type")?,
        size_bytes: get_n_u64(item, "size_bytes")?,
        s3_key: get_s(item, "s3_key")?,
        folder_id: get_optional_s(item, "folder_id")
            .as_deref()
            .map(parse_uuid)
            .transpose()?,
        owner_id: parse_uuid(&get_s(item, "owner_id")?)?,
        version: get_n_u32(item, "version")?,
        is_trashed: get_bool(item, "is_trashed")?,
        trashed_at: get_optional_s(item, "trashed_at")
            .as_deref()
            .map(parse_datetime)
            .transpose()?,
        trashed_by: get_optional_s(item, "trashed_by")
            .as_deref()
            .map(parse_uuid)
            .transpose()?,
        trashed_by_email: get_optional_s(item, "trashed_by_email"),
        trashed_from_folder_id: get_optional_s(item, "trashed_from_folder_id")
            .as_deref()
            .map(parse_uuid)
            .transpose()?,
        created_at: parse_datetime(&get_s(item, "created_at")?)?,
        updated_at: parse_datetime(&get_s(item, "updated_at")?)?,
    })
}

fn parse_folder(
    item: &std::collections::HashMap<String, AttributeValue>,
) -> Result<Folder, ServiceError> {
    Ok(Folder {
        id: parse_uuid(&get_s(item, "id")?)?,
        name: get_s(item, "name")?,
        parent_id: get_optional_s(item, "parent_id")
            .as_deref()
            .map(parse_uuid)
            .transpose()?,
        owner_id: parse_uuid(&get_s(item, "owner_id")?)?,
        created_at: parse_datetime(&get_s(item, "created_at")?)?,
        updated_at: parse_datetime(&get_s(item, "updated_at")?)?,
    })
}

fn parse_file_version(
    item: &std::collections::HashMap<String, AttributeValue>,
) -> Result<FileVersion, ServiceError> {
    Ok(FileVersion {
        file_id: parse_uuid(&get_s(item, "file_id")?)?,
        version: get_n_u32(item, "version")?,
        s3_key: get_s(item, "s3_key")?,
        size_bytes: get_n_u64(item, "size_bytes")?,
        created_by: parse_uuid(&get_s(item, "created_by")?)?,
        created_at: parse_datetime(&get_s(item, "created_at")?)?,
    })
}

fn parse_file_share(
    item: &std::collections::HashMap<String, AttributeValue>,
) -> Result<FileShare, ServiceError> {
    let permission_str = get_s(item, "permission")?;
    let permission = SharePermission::from_str_value(&permission_str).ok_or_else(|| {
        ServiceError::DynamoError(format!("invalid permission: {permission_str}"))
    })?;

    Ok(FileShare {
        id: parse_uuid(&get_s(item, "id")?)?,
        file_id: parse_uuid(&get_s(item, "file_id")?)?,
        shared_with: parse_uuid(&get_s(item, "shared_with")?)?,
        permission,
        shared_by: parse_uuid(&get_s(item, "shared_by")?)?,
        created_at: parse_datetime(&get_s(item, "created_at")?)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn make_file_item() -> HashMap<String, AttributeValue> {
        let now = Utc::now();
        let id = Uuid::new_v4();
        let owner = Uuid::new_v4();
        let mut item = HashMap::new();
        item.insert("id".into(), AttributeValue::S(id.to_string()));
        item.insert("name".into(), AttributeValue::S("test.txt".into()));
        item.insert("mime_type".into(), AttributeValue::S("text/plain".into()));
        item.insert("size_bytes".into(), AttributeValue::N("1024".into()));
        item.insert("s3_key".into(), AttributeValue::S(format!("files/{id}")));
        item.insert("owner_id".into(), AttributeValue::S(owner.to_string()));
        item.insert("version".into(), AttributeValue::N("1".into()));
        item.insert("is_trashed".into(), AttributeValue::Bool(false));
        item.insert("created_at".into(), AttributeValue::S(now.to_rfc3339()));
        item.insert("updated_at".into(), AttributeValue::S(now.to_rfc3339()));
        item
    }

    #[test]
    fn test_parse_file_metadata_success() {
        let item = make_file_item();
        let result = parse_file_metadata(&item);
        assert!(result.is_ok());
        let file = result.unwrap();
        assert_eq!(file.name, "test.txt");
        assert_eq!(file.mime_type, "text/plain");
        assert_eq!(file.size_bytes, 1024);
        assert_eq!(file.version, 1);
        assert!(!file.is_trashed);
        assert!(file.folder_id.is_none());
    }

    #[test]
    fn test_parse_file_metadata_with_folder() {
        let mut item = make_file_item();
        let folder_id = Uuid::new_v4();
        item.insert("folder_id".into(), AttributeValue::S(folder_id.to_string()));
        let file = parse_file_metadata(&item).unwrap();
        assert_eq!(file.folder_id, Some(folder_id));
    }

    #[test]
    fn test_parse_file_metadata_with_deletion_fields() {
        let mut item = make_file_item();
        let trashed_at = Utc::now();
        let trashed_by = Uuid::new_v4();
        let from_folder = Uuid::new_v4();
        item.insert("is_trashed".into(), AttributeValue::Bool(true));
        item.insert(
            "trashed_at".into(),
            AttributeValue::S(trashed_at.to_rfc3339()),
        );
        item.insert(
            "trashed_by".into(),
            AttributeValue::S(trashed_by.to_string()),
        );
        item.insert(
            "trashed_by_email".into(),
            AttributeValue::S("otter@example.com".into()),
        );
        item.insert(
            "trashed_from_folder_id".into(),
            AttributeValue::S(from_folder.to_string()),
        );

        let file = parse_file_metadata(&item).unwrap();
        assert!(file.is_trashed);
        assert_eq!(
            file.trashed_at.unwrap().to_rfc3339(),
            trashed_at.to_rfc3339()
        );
        assert_eq!(file.trashed_by, Some(trashed_by));
        assert_eq!(file.trashed_by_email.as_deref(), Some("otter@example.com"));
        assert_eq!(file.trashed_from_folder_id, Some(from_folder));
    }

    #[test]
    fn test_parse_file_metadata_without_deletion_fields() {
        let file = parse_file_metadata(&make_file_item()).unwrap();
        assert!(file.trashed_at.is_none());
        assert!(file.trashed_by.is_none());
        assert!(file.trashed_by_email.is_none());
        assert!(file.trashed_from_folder_id.is_none());
    }

    #[test]
    fn test_trash_retention_boundary_is_exactly_30_days() {
        let now = Utc::now();
        let kept = now - Duration::days(29) - Duration::hours(23);
        let purged = now - Duration::days(30) - Duration::minutes(1);

        assert!(!is_trash_expired(Some(kept), now));
        assert!(is_trash_expired(Some(purged), now));
    }

    fn trashed_file(name: &str, trashed_at: Option<DateTime<Utc>>) -> FileMetadata {
        let now = Utc::now();
        FileMetadata {
            id: Uuid::new_v4(),
            name: name.to_string(),
            mime_type: "text/plain".into(),
            size_bytes: 1,
            s3_key: format!("files/{name}"),
            folder_id: None,
            owner_id: Uuid::new_v4(),
            version: 1,
            is_trashed: true,
            trashed_at,
            trashed_by: None,
            trashed_by_email: None,
            trashed_from_folder_id: None,
            created_at: now,
            updated_at: now,
        }
    }

    #[test]
    fn test_retained_trash_excludes_expired_and_sorts_newest_first() {
        let now = Utc::now();
        let files = vec![
            trashed_file("old", Some(now - Duration::days(31))),
            trashed_file("older-kept", Some(now - Duration::days(10))),
            trashed_file("newest", Some(now - Duration::hours(1))),
        ];

        let kept = retained_trash(files, now);
        let names: Vec<&str> = kept.iter().map(|f| f.name.as_str()).collect();
        assert_eq!(names, vec!["newest", "older-kept"]);
    }

    #[test]
    fn test_expired_trash_selects_only_expired_items() {
        let now = Utc::now();
        let files = vec![
            trashed_file(
                "expired",
                Some(now - Duration::days(30) - Duration::minutes(1)),
            ),
            trashed_file("kept", Some(now - Duration::days(29) - Duration::hours(23))),
        ];

        let expired = expired_trash(files, now);
        assert_eq!(expired.len(), 1);
        assert_eq!(expired[0].name, "expired");
    }

    #[test]
    fn test_items_without_trashed_at_are_not_expired() {
        assert!(!is_trash_expired(None, Utc::now()));
    }

    #[test]
    fn test_restore_target_folder_prefers_original_folder() {
        let folder_id = Uuid::new_v4();
        assert_eq!(
            restore_target_folder(Some(folder_id), true),
            Some(folder_id)
        );
    }

    #[test]
    fn test_restore_target_folder_falls_back_to_root() {
        assert_eq!(restore_target_folder(Some(Uuid::new_v4()), false), None);
        assert_eq!(restore_target_folder(None, false), None);
    }

    #[test]
    fn test_original_location_label() {
        let folder_id = Uuid::new_v4();
        assert_eq!(
            original_location_label(Some(folder_id), Some("Invoices")),
            ("Invoices".to_string(), false)
        );
        assert_eq!(
            original_location_label(Some(folder_id), None),
            (MISSING_FOLDER_LOCATION_LABEL.to_string(), true)
        );
        assert_eq!(
            original_location_label(None, None),
            (ROOT_LOCATION_LABEL.to_string(), false)
        );
    }

    #[test]
    fn test_update_expression_combines_set_and_remove() {
        assert_eq!(
            update_expression(&["is_trashed = :t".into()], &["trashed_at".into()]),
            "SET is_trashed = :t REMOVE trashed_at"
        );
        assert_eq!(
            update_expression(&["is_trashed = :t".into()], &[]),
            "SET is_trashed = :t"
        );
    }

    #[test]
    fn test_parse_file_metadata_missing_field() {
        let mut item = make_file_item();
        item.remove("name");
        let result = parse_file_metadata(&item);
        assert!(result.is_err());
    }

    #[test]
    fn test_parse_folder() {
        let now = Utc::now();
        let id = Uuid::new_v4();
        let owner = Uuid::new_v4();
        let mut item = HashMap::new();
        item.insert("id".into(), AttributeValue::S(id.to_string()));
        item.insert("name".into(), AttributeValue::S("Documents".into()));
        item.insert("owner_id".into(), AttributeValue::S(owner.to_string()));
        item.insert("created_at".into(), AttributeValue::S(now.to_rfc3339()));
        item.insert("updated_at".into(), AttributeValue::S(now.to_rfc3339()));

        let folder = parse_folder(&item).unwrap();
        assert_eq!(folder.name, "Documents");
        assert_eq!(folder.id, id);
        assert!(folder.parent_id.is_none());
    }

    #[test]
    fn test_parse_file_version() {
        let now = Utc::now();
        let file_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();
        let mut item = HashMap::new();
        item.insert("file_id".into(), AttributeValue::S(file_id.to_string()));
        item.insert("version".into(), AttributeValue::N("3".into()));
        item.insert("s3_key".into(), AttributeValue::S("files/v3/key".into()));
        item.insert("size_bytes".into(), AttributeValue::N("2048".into()));
        item.insert("created_by".into(), AttributeValue::S(user_id.to_string()));
        item.insert("created_at".into(), AttributeValue::S(now.to_rfc3339()));

        let ver = parse_file_version(&item).unwrap();
        assert_eq!(ver.file_id, file_id);
        assert_eq!(ver.version, 3);
        assert_eq!(ver.size_bytes, 2048);
    }

    #[test]
    fn test_parse_file_share() {
        let now = Utc::now();
        let share_id = Uuid::new_v4();
        let file_id = Uuid::new_v4();
        let user_a = Uuid::new_v4();
        let user_b = Uuid::new_v4();
        let mut item = HashMap::new();
        item.insert("id".into(), AttributeValue::S(share_id.to_string()));
        item.insert("file_id".into(), AttributeValue::S(file_id.to_string()));
        item.insert("shared_with".into(), AttributeValue::S(user_a.to_string()));
        item.insert("permission".into(), AttributeValue::S("editor".into()));
        item.insert("shared_by".into(), AttributeValue::S(user_b.to_string()));
        item.insert("created_at".into(), AttributeValue::S(now.to_rfc3339()));

        let share = parse_file_share(&item).unwrap();
        assert_eq!(share.permission, SharePermission::Editor);
        assert_eq!(share.file_id, file_id);
    }

    #[test]
    fn test_share_permission_from_str() {
        assert_eq!(
            SharePermission::from_str_value("viewer"),
            Some(SharePermission::Viewer)
        );
        assert_eq!(
            SharePermission::from_str_value("Editor"),
            Some(SharePermission::Editor)
        );
        assert_eq!(SharePermission::from_str_value("invalid"), None);
    }
}
