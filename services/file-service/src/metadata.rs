use aws_sdk_dynamodb::types::AttributeValue;
use chrono::Utc;
use uuid::Uuid;

use crate::config::AwsConfig;
use crate::errors::ServiceError;
use crate::models::{FileMetadata, FileShare, FileVersion, Folder, SharePermission};

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

    pub async fn trash_file(&self, file_id: &Uuid) -> Result<FileMetadata, ServiceError> {
        let now = Utc::now();
        self.client
            .update_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .update_expression("SET is_trashed = :t, updated_at = :u")
            .condition_expression("attribute_exists(id)")
            .expression_attribute_values(":t", AttributeValue::Bool(true))
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

    pub async fn restore_file(&self, file_id: &Uuid) -> Result<FileMetadata, ServiceError> {
        let now = Utc::now();
        self.client
            .update_item()
            .table_name(&self.files_table)
            .key("id", AttributeValue::S(file_id.to_string()))
            .update_expression("SET is_trashed = :t, updated_at = :u")
            .condition_expression("attribute_exists(id)")
            .expression_attribute_values(":t", AttributeValue::Bool(false))
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

    pub async fn list_trashed(
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

        files.sort_by_key(|f| std::cmp::Reverse(f.updated_at));
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
mod client_tests {
    use super::*;
    use crate::test_support::{
        aws_config_fixture, dynamo_error, empty_get_item_response, file_item_json,
        folder_item_json, get_item_response, offline_aws_env, ok_json, query_response, replay,
        scan_response, share_item_json, uuid_from, version_item_json, with_env_blocking, write_ok,
    };
    use crate::test_support::{fixed_time, metadata_client};
    use aws_smithy_runtime::client::http::test_util::StaticReplayClient;
    use serde_json::Value;

    const FILE: u8 = 1;
    const OWNER: u8 = 2;
    const FOLDER: u8 = 3;
    const SHARE: u8 = 4;
    const OTHER_USER: u8 = 5;

    fn sent_bodies(http: &StaticReplayClient) -> Vec<Value> {
        http.actual_requests()
            .map(|r| serde_json::from_slice(r.body().bytes().unwrap()).unwrap())
            .collect()
    }

    fn target_of(http: &StaticReplayClient, index: usize) -> String {
        http.actual_requests()
            .nth(index)
            .expect("request")
            .headers()
            .get("x-amz-target")
            .expect("DynamoDB sets an operation target header")
            .to_string()
    }

    fn file_fixture() -> FileMetadata {
        FileMetadata {
            id: uuid_from(FILE),
            name: "report.pdf".into(),
            mime_type: "application/pdf".into(),
            size_bytes: 2048,
            s3_key: "files/a/b".into(),
            folder_id: Some(uuid_from(FOLDER)),
            owner_id: uuid_from(OWNER),
            version: 1,
            is_trashed: false,
            created_at: fixed_time(),
            updated_at: fixed_time(),
        }
    }

    #[test]
    fn new_reads_every_table_name_from_config() {
        let mut config = aws_config_fixture();
        config.dynamodb_table = "f".into();
        config.dynamodb_folders_table = "fo".into();
        config.dynamodb_versions_table = "v".into();
        config.dynamodb_shares_table = "s".into();
        config.endpoint_url = Some("http://localstack:4566".into());

        let client = with_env_blocking(&offline_aws_env(), async {
            MetadataClient::new(&config).await
        });

        assert_eq!(client.files_table, "f");
        assert_eq!(client.folders_table, "fo");
        assert_eq!(client.versions_table, "v");
        assert_eq!(client.shares_table, "s");
        assert_eq!(
            client.clone().client.config().region().map(|r| r.as_ref()),
            Some("us-east-1")
        );
    }

    #[tokio::test]
    async fn put_file_writes_every_attribute_including_the_folder() {
        let http = replay(vec![write_ok()]);
        let client = metadata_client(http.clone());

        client.put_file(&file_fixture()).await.expect("put_file");

        let body = &sent_bodies(&http)[0];
        assert_eq!(body["TableName"], "files");
        let item = &body["Item"];
        assert_eq!(item["id"]["S"], uuid_from(FILE).to_string());
        assert_eq!(item["name"]["S"], "report.pdf");
        assert_eq!(item["mime_type"]["S"], "application/pdf");
        assert_eq!(item["size_bytes"]["N"], "2048");
        assert_eq!(item["s3_key"]["S"], "files/a/b");
        assert_eq!(item["owner_id"]["S"], uuid_from(OWNER).to_string());
        assert_eq!(item["version"]["N"], "1");
        assert_eq!(item["is_trashed"]["BOOL"], false);
        assert_eq!(item["folder_id"]["S"], uuid_from(FOLDER).to_string());
        assert_eq!(item["created_at"]["S"], fixed_time().to_rfc3339());
    }

    #[tokio::test]
    async fn put_file_omits_folder_id_for_root_level_files() {
        let http = replay(vec![write_ok()]);
        let client = metadata_client(http.clone());
        let mut file = file_fixture();
        file.folder_id = None;

        client.put_file(&file).await.expect("put_file");

        assert!(sent_bodies(&http)[0]["Item"]["folder_id"].is_null());
    }

    #[tokio::test]
    async fn put_file_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.put_file(&file_fixture()).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn get_file_parses_the_returned_item() {
        let http = replay(vec![get_item_response(&file_item_json(
            uuid_from(FILE),
            uuid_from(OWNER),
            Some(uuid_from(FOLDER)),
        ))]);
        let client = metadata_client(http.clone());

        let file = client.get_file(&uuid_from(FILE)).await.expect("get_file");

        assert_eq!(file.id, uuid_from(FILE));
        assert_eq!(file.folder_id, Some(uuid_from(FOLDER)));
        assert_eq!(file.size_bytes, 2048);
        let body = &sent_bodies(&http)[0];
        assert_eq!(body["TableName"], "files");
        assert_eq!(body["Key"]["id"]["S"], uuid_from(FILE).to_string());
    }

    #[tokio::test]
    async fn get_file_reports_a_missing_item_as_file_not_found() {
        let client = metadata_client(replay(vec![empty_get_item_response()]));

        let err = client.get_file(&uuid_from(FILE)).await.unwrap_err();

        assert!(matches!(err, ServiceError::FileNotFound(id) if id == uuid_from(FILE).to_string()));
    }

    #[tokio::test]
    async fn get_file_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.get_file(&uuid_from(FILE)).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn delete_file_deletes_by_primary_key() {
        let http = replay(vec![write_ok()]);
        let client = metadata_client(http.clone());

        client
            .delete_file(&uuid_from(FILE))
            .await
            .expect("delete_file");

        let body = &sent_bodies(&http)[0];
        assert_eq!(body["TableName"], "files");
        assert_eq!(body["Key"]["id"]["S"], uuid_from(FILE).to_string());
        assert!(target_of(&http, 0).ends_with("DeleteItem"));
    }

    #[tokio::test]
    async fn delete_file_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(400, "ValidationException")]));

        let err = client.delete_file(&uuid_from(FILE)).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn trash_file_sets_the_flag_then_returns_the_updated_file() {
        let mut trashed = file_item_json(uuid_from(FILE), uuid_from(OWNER), None);
        trashed = trashed.replace(
            r#""is_trashed":{"BOOL":false}"#,
            r#""is_trashed":{"BOOL":true}"#,
        );
        let http = replay(vec![write_ok(), get_item_response(&trashed)]);
        let client = metadata_client(http.clone());

        let file = client
            .trash_file(&uuid_from(FILE))
            .await
            .expect("trash_file");

        assert!(file.is_trashed);
        let update = &sent_bodies(&http)[0];
        assert_eq!(
            update["UpdateExpression"],
            "SET is_trashed = :t, updated_at = :u"
        );
        assert_eq!(update["ConditionExpression"], "attribute_exists(id)");
        assert_eq!(update["ExpressionAttributeValues"][":t"]["BOOL"], true);
    }

    #[tokio::test]
    async fn trash_file_maps_a_failed_condition_to_file_not_found() {
        let client = metadata_client(replay(vec![dynamo_error(
            400,
            "ConditionalCheckFailedException",
        )]));

        let err = client.trash_file(&uuid_from(FILE)).await.unwrap_err();

        assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn trash_file_surfaces_other_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.trash_file(&uuid_from(FILE)).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn restore_file_clears_the_trashed_flag() {
        let http = replay(vec![
            write_ok(),
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
        ]);
        let client = metadata_client(http.clone());

        let file = client
            .restore_file(&uuid_from(FILE))
            .await
            .expect("restore_file");

        assert!(!file.is_trashed);
        assert_eq!(
            sent_bodies(&http)[0]["ExpressionAttributeValues"][":t"]["BOOL"],
            false
        );
    }

    #[tokio::test]
    async fn restore_file_maps_a_failed_condition_to_file_not_found() {
        let client = metadata_client(replay(vec![dynamo_error(
            400,
            "ConditionalCheckFailedException",
        )]));

        let err = client.restore_file(&uuid_from(FILE)).await.unwrap_err();

        assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn restore_file_surfaces_other_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.restore_file(&uuid_from(FILE)).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn rename_file_updates_the_reserved_name_attribute() {
        let http = replay(vec![
            write_ok(),
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
        ]);
        let client = metadata_client(http.clone());

        client
            .rename_file(&uuid_from(FILE), "renamed.pdf")
            .await
            .expect("rename_file");

        let update = &sent_bodies(&http)[0];
        assert_eq!(update["UpdateExpression"], "SET #n = :n, updated_at = :u");
        assert_eq!(update["ExpressionAttributeNames"]["#n"], "name");
        assert_eq!(
            update["ExpressionAttributeValues"][":n"]["S"],
            "renamed.pdf"
        );
    }

    #[tokio::test]
    async fn rename_file_maps_a_failed_condition_to_file_not_found() {
        let client = metadata_client(replay(vec![dynamo_error(
            400,
            "ConditionalCheckFailedException",
        )]));

        let err = client.rename_file(&uuid_from(FILE), "x").await.unwrap_err();

        assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn rename_file_surfaces_other_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.rename_file(&uuid_from(FILE), "x").await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn move_file_into_a_folder_sets_folder_id() {
        let http = replay(vec![
            write_ok(),
            get_item_response(&file_item_json(
                uuid_from(FILE),
                uuid_from(OWNER),
                Some(uuid_from(FOLDER)),
            )),
        ]);
        let client = metadata_client(http.clone());

        let file = client
            .move_file(&uuid_from(FILE), Some(uuid_from(FOLDER)))
            .await
            .expect("move_file");

        assert_eq!(file.folder_id, Some(uuid_from(FOLDER)));
        let update = &sent_bodies(&http)[0];
        assert_eq!(
            update["UpdateExpression"],
            "SET folder_id = :f, updated_at = :u"
        );
        assert_eq!(
            update["ExpressionAttributeValues"][":f"]["S"],
            uuid_from(FOLDER).to_string()
        );
    }

    #[tokio::test]
    async fn move_file_to_the_root_removes_folder_id() {
        let http = replay(vec![
            write_ok(),
            get_item_response(&file_item_json(uuid_from(FILE), uuid_from(OWNER), None)),
        ]);
        let client = metadata_client(http.clone());

        let file = client
            .move_file(&uuid_from(FILE), None)
            .await
            .expect("move_file");

        assert_eq!(file.folder_id, None);
        assert_eq!(
            sent_bodies(&http)[0]["UpdateExpression"],
            "SET updated_at = :u REMOVE folder_id"
        );
    }

    #[tokio::test]
    async fn move_file_maps_a_failed_condition_to_file_not_found() {
        let client = metadata_client(replay(vec![dynamo_error(
            400,
            "ConditionalCheckFailedException",
        )]));

        let err = client.move_file(&uuid_from(FILE), None).await.unwrap_err();

        assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn move_file_surfaces_other_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.move_file(&uuid_from(FILE), None).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_trashed_filters_on_the_trashed_flag_and_owner() {
        let http = replay(vec![scan_response(&[file_item_json(
            uuid_from(FILE),
            uuid_from(OWNER),
            None,
        )])]);
        let client = metadata_client(http.clone());

        let files = client
            .list_trashed(Some(uuid_from(OWNER)))
            .await
            .expect("list_trashed");

        assert_eq!(files.len(), 1);
        let scan = &sent_bodies(&http)[0];
        assert_eq!(
            scan["FilterExpression"],
            "is_trashed = :trashed AND owner_id = :owner_id"
        );
        assert_eq!(scan["ExpressionAttributeValues"][":trashed"]["BOOL"], true);
        assert_eq!(
            scan["ExpressionAttributeValues"][":owner_id"]["S"],
            uuid_from(OWNER).to_string()
        );
    }

    #[tokio::test]
    async fn list_trashed_without_an_owner_filters_only_on_the_flag_and_sorts_newest_first() {
        let older = file_item_json(uuid_from(FILE), uuid_from(OWNER), None)
            .replace(&fixed_time().to_rfc3339(), "2020-01-01T00:00:00+00:00");
        let http = replay(vec![scan_response(&[
            older,
            file_item_json(uuid_from(OTHER_USER), uuid_from(OWNER), None),
        ])]);
        let client = metadata_client(http.clone());

        let files = client.list_trashed(None).await.expect("list_trashed");

        assert_eq!(
            files.iter().map(|f| f.id).collect::<Vec<_>>(),
            vec![uuid_from(OTHER_USER), uuid_from(FILE)],
            "most recently updated first"
        );
        assert_eq!(
            sent_bodies(&http)[0]["FilterExpression"],
            "is_trashed = :trashed"
        );
    }

    #[tokio::test]
    async fn list_trashed_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.list_trashed(None).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_files_combines_every_filter() {
        let http = replay(vec![scan_response(&[file_item_json(
            uuid_from(FILE),
            uuid_from(OWNER),
            Some(uuid_from(FOLDER)),
        )])]);
        let client = metadata_client(http.clone());

        let files = client
            .list_files(Some(uuid_from(FOLDER)), Some(uuid_from(OWNER)), false)
            .await
            .expect("list_files");

        assert_eq!(files.len(), 1);
        assert_eq!(
            sent_bodies(&http)[0]["FilterExpression"],
            "folder_id = :folder_id AND owner_id = :owner_id AND is_trashed = :trashed"
        );
    }

    #[tokio::test]
    async fn list_files_without_filters_scans_the_whole_table() {
        let http = replay(vec![scan_response(&[])]);
        let client = metadata_client(http.clone());

        let files = client.list_files(None, None, true).await.expect("list");

        assert!(files.is_empty());
        assert!(
            sent_bodies(&http)[0]["FilterExpression"].is_null(),
            "include_trashed with no ids means no filter at all"
        );
    }

    #[tokio::test]
    async fn list_files_follows_the_paginator_across_pages() {
        let first_page = ok_json(&format!(
            r#"{{"Items":[{}],"Count":1,"LastEvaluatedKey":{{"id":{{"S":"{}"}}}}}}"#,
            file_item_json(uuid_from(FILE), uuid_from(OWNER), None),
            uuid_from(FILE)
        ));
        let second_page = scan_response(&[file_item_json(
            uuid_from(OTHER_USER),
            uuid_from(OWNER),
            None,
        )]);
        let http = replay(vec![first_page, second_page]);
        let client = metadata_client(http.clone());

        let files = client.list_files(None, None, true).await.expect("list");

        assert_eq!(files.len(), 2, "both pages are collected");
        let second_request = &sent_bodies(&http)[1];
        assert_eq!(
            second_request["ExclusiveStartKey"]["id"]["S"],
            uuid_from(FILE).to_string()
        );
    }

    #[tokio::test]
    async fn list_files_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.list_files(None, None, false).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_files_reports_unparseable_items() {
        let http = replay(vec![scan_response(
            &[r#"{"id":{"S":"not-a-uuid"}}"#.into()],
        )]);
        let client = metadata_client(http);

        let err = client.list_files(None, None, true).await.unwrap_err();

        assert!(err.to_string().contains("invalid UUID"), "{err}");
    }

    #[tokio::test]
    async fn put_folder_writes_the_parent_only_when_present() {
        let http = replay(vec![write_ok(), write_ok()]);
        let client = metadata_client(http.clone());
        let mut folder = Folder {
            id: uuid_from(FOLDER),
            name: "Finance".into(),
            parent_id: Some(uuid_from(OTHER_USER)),
            owner_id: uuid_from(OWNER),
            created_at: fixed_time(),
            updated_at: fixed_time(),
        };

        client.put_folder(&folder).await.expect("with parent");
        folder.parent_id = None;
        client.put_folder(&folder).await.expect("without parent");

        let bodies = sent_bodies(&http);
        assert_eq!(bodies[0]["TableName"], "folders");
        assert_eq!(bodies[0]["Item"]["name"]["S"], "Finance");
        assert_eq!(
            bodies[0]["Item"]["parent_id"]["S"],
            uuid_from(OTHER_USER).to_string()
        );
        assert!(bodies[1]["Item"]["parent_id"].is_null());
    }

    #[tokio::test]
    async fn put_folder_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));
        let folder = Folder {
            id: uuid_from(FOLDER),
            name: "Finance".into(),
            parent_id: None,
            owner_id: uuid_from(OWNER),
            created_at: fixed_time(),
            updated_at: fixed_time(),
        };

        let err = client.put_folder(&folder).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn get_folder_parses_the_item_and_reports_misses() {
        let http = replay(vec![
            get_item_response(&folder_item_json(uuid_from(FOLDER), uuid_from(OWNER), None)),
            empty_get_item_response(),
            dynamo_error(500, "InternalServerError"),
        ]);
        let client = metadata_client(http.clone());

        let folder = client
            .get_folder(&uuid_from(FOLDER))
            .await
            .expect("get_folder");
        assert_eq!(folder.name, "Finance");
        assert_eq!(sent_bodies(&http)[0]["TableName"], "folders");

        let missing = client.get_folder(&uuid_from(FOLDER)).await.unwrap_err();
        assert!(matches!(missing, ServiceError::FolderNotFound(_)));

        let failed = client.get_folder(&uuid_from(FOLDER)).await.unwrap_err();
        assert!(matches!(failed, ServiceError::DynamoError(_)));
    }

    #[tokio::test]
    async fn update_folder_only_sets_the_supplied_fields() {
        let http = replay(vec![
            write_ok(),
            get_item_response(&folder_item_json(uuid_from(FOLDER), uuid_from(OWNER), None)),
            write_ok(),
            get_item_response(&folder_item_json(uuid_from(FOLDER), uuid_from(OWNER), None)),
        ]);
        let client = metadata_client(http.clone());

        client
            .update_folder(
                &uuid_from(FOLDER),
                Some("Renamed".into()),
                Some(uuid_from(OTHER_USER)),
            )
            .await
            .expect("update with both fields");
        client
            .update_folder(&uuid_from(FOLDER), None, None)
            .await
            .expect("timestamp-only update");

        let bodies = sent_bodies(&http);
        assert_eq!(
            bodies[0]["UpdateExpression"],
            "SET updated_at = :u, #n = :n, parent_id = :p"
        );
        assert_eq!(bodies[0]["ExpressionAttributeValues"][":n"]["S"], "Renamed");
        assert_eq!(bodies[2]["UpdateExpression"], "SET updated_at = :u");
        assert!(bodies[2]["ExpressionAttributeNames"].is_null());
    }

    #[tokio::test]
    async fn update_folder_maps_a_failed_condition_to_folder_not_found() {
        let client = metadata_client(replay(vec![dynamo_error(
            400,
            "ConditionalCheckFailedException",
        )]));

        let err = client
            .update_folder(&uuid_from(FOLDER), None, None)
            .await
            .unwrap_err();

        assert!(matches!(err, ServiceError::FolderNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn update_folder_surfaces_other_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client
            .update_folder(&uuid_from(FOLDER), None, None)
            .await
            .unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn delete_folder_deletes_from_the_folders_table() {
        let http = replay(vec![write_ok(), dynamo_error(500, "InternalServerError")]);
        let client = metadata_client(http.clone());

        client
            .delete_folder(&uuid_from(FOLDER))
            .await
            .expect("delete_folder");
        let err = client.delete_folder(&uuid_from(FOLDER)).await.unwrap_err();

        assert_eq!(sent_bodies(&http)[0]["TableName"], "folders");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_folders_filters_by_parent_or_root_and_owner() {
        let http = replay(vec![
            scan_response(&[folder_item_json(
                uuid_from(FOLDER),
                uuid_from(OWNER),
                Some(uuid_from(OTHER_USER)),
            )]),
            scan_response(&[]),
        ]);
        let client = metadata_client(http.clone());

        let children = client
            .list_folders(Some(uuid_from(OTHER_USER)), Some(uuid_from(OWNER)))
            .await
            .expect("list children");
        client
            .list_folders(None, None)
            .await
            .expect("list root folders");

        assert_eq!(children.len(), 1);
        assert_eq!(children[0].parent_id, Some(uuid_from(OTHER_USER)));
        let bodies = sent_bodies(&http);
        assert_eq!(
            bodies[0]["FilterExpression"],
            "parent_id = :parent_id AND owner_id = :owner_id"
        );
        assert_eq!(
            bodies[1]["FilterExpression"],
            "attribute_not_exists(parent_id)"
        );
    }

    #[tokio::test]
    async fn list_folders_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.list_folders(None, None).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn put_version_writes_the_version_row() {
        let http = replay(vec![write_ok(), dynamo_error(500, "InternalServerError")]);
        let client = metadata_client(http.clone());
        let version = FileVersion {
            file_id: uuid_from(FILE),
            version: 3,
            s3_key: "files/a/b/v3".into(),
            size_bytes: 4096,
            created_by: uuid_from(OWNER),
            created_at: fixed_time(),
        };

        client.put_version(&version).await.expect("put_version");
        let err = client.put_version(&version).await.unwrap_err();

        let body = &sent_bodies(&http)[0];
        assert_eq!(body["TableName"], "versions");
        assert_eq!(body["Item"]["version"]["N"], "3");
        assert_eq!(body["Item"]["size_bytes"]["N"], "4096");
        assert_eq!(body["Item"]["s3_key"]["S"], "files/a/b/v3");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_versions_queries_newest_first() {
        let http = replay(vec![query_response(&[
            version_item_json(uuid_from(FILE), uuid_from(OWNER), 2),
            version_item_json(uuid_from(FILE), uuid_from(OWNER), 1),
        ])]);
        let client = metadata_client(http.clone());

        let versions = client
            .list_versions(&uuid_from(FILE))
            .await
            .expect("list_versions");

        assert_eq!(
            versions.iter().map(|v| v.version).collect::<Vec<_>>(),
            vec![2, 1]
        );
        let body = &sent_bodies(&http)[0];
        assert_eq!(body["TableName"], "versions");
        assert_eq!(body["KeyConditionExpression"], "file_id = :fid");
        assert_eq!(body["ScanIndexForward"], false);
    }

    #[tokio::test]
    async fn list_versions_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client.list_versions(&uuid_from(FILE)).await.unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn put_share_stores_the_permission_as_a_lowercase_string() {
        let http = replay(vec![write_ok(), dynamo_error(500, "InternalServerError")]);
        let client = metadata_client(http.clone());
        let share = FileShare {
            id: uuid_from(SHARE),
            file_id: uuid_from(FILE),
            shared_with: uuid_from(OTHER_USER),
            permission: SharePermission::Editor,
            shared_by: uuid_from(OWNER),
            created_at: fixed_time(),
        };

        client.put_share(&share).await.expect("put_share");
        let err = client.put_share(&share).await.unwrap_err();

        let body = &sent_bodies(&http)[0];
        assert_eq!(body["TableName"], "shares");
        assert_eq!(body["Item"]["permission"]["S"], "editor");
        assert_eq!(
            body["Item"]["shared_with"]["S"],
            uuid_from(OTHER_USER).to_string()
        );
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn find_existing_share_returns_the_first_match_or_none() {
        let http = replay(vec![
            scan_response(&[share_item_json(
                uuid_from(SHARE),
                uuid_from(FILE),
                uuid_from(OTHER_USER),
                uuid_from(OWNER),
                "viewer",
            )]),
            scan_response(&[]),
        ]);
        let client = metadata_client(http.clone());

        let found = client
            .find_existing_share(&uuid_from(FILE), &uuid_from(OTHER_USER))
            .await
            .expect("scan");
        let missing = client
            .find_existing_share(&uuid_from(FILE), &uuid_from(OTHER_USER))
            .await
            .expect("scan");

        assert_eq!(found.map(|s| s.id), Some(uuid_from(SHARE)));
        assert!(missing.is_none());
        assert_eq!(
            sent_bodies(&http)[0]["FilterExpression"],
            "file_id = :fid AND shared_with = :uid"
        );
    }

    #[tokio::test]
    async fn find_existing_share_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client
            .find_existing_share(&uuid_from(FILE), &uuid_from(OTHER_USER))
            .await
            .unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_shares_for_user_filters_on_the_recipient() {
        let http = replay(vec![scan_response(&[share_item_json(
            uuid_from(SHARE),
            uuid_from(FILE),
            uuid_from(OTHER_USER),
            uuid_from(OWNER),
            "viewer",
        )])]);
        let client = metadata_client(http.clone());

        let shares = client
            .list_shares_for_user(&uuid_from(OTHER_USER))
            .await
            .expect("list");

        assert_eq!(shares.len(), 1);
        assert_eq!(shares[0].permission, SharePermission::Viewer);
        assert_eq!(
            sent_bodies(&http)[0]["FilterExpression"],
            "shared_with = :uid"
        );
    }

    #[tokio::test]
    async fn list_shares_for_user_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client
            .list_shares_for_user(&uuid_from(OTHER_USER))
            .await
            .unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_shares_by_owner_filters_on_the_sharer() {
        let http = replay(vec![scan_response(&[share_item_json(
            uuid_from(SHARE),
            uuid_from(FILE),
            uuid_from(OTHER_USER),
            uuid_from(OWNER),
            "editor",
        )])]);
        let client = metadata_client(http.clone());

        let shares = client
            .list_shares_by_owner(&uuid_from(OWNER))
            .await
            .expect("list");

        assert_eq!(shares.len(), 1);
        assert_eq!(shares[0].permission, SharePermission::Editor);
        assert_eq!(
            sent_bodies(&http)[0]["FilterExpression"],
            "shared_by = :uid"
        );
    }

    #[tokio::test]
    async fn list_shares_by_owner_surfaces_dynamo_failures() {
        let client = metadata_client(replay(vec![dynamo_error(500, "InternalServerError")]));

        let err = client
            .list_shares_by_owner(&uuid_from(OWNER))
            .await
            .unwrap_err();

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_shares_filters_on_the_file() {
        let http = replay(vec![
            scan_response(&[share_item_json(
                uuid_from(SHARE),
                uuid_from(FILE),
                uuid_from(OTHER_USER),
                uuid_from(OWNER),
                "viewer",
            )]),
            dynamo_error(500, "InternalServerError"),
        ]);
        let client = metadata_client(http.clone());

        let shares = client.list_shares(&uuid_from(FILE)).await.expect("list");
        let err = client.list_shares(&uuid_from(FILE)).await.unwrap_err();

        assert_eq!(shares.len(), 1);
        assert_eq!(shares[0].file_id, uuid_from(FILE));
        assert_eq!(sent_bodies(&http)[0]["FilterExpression"], "file_id = :fid");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn delete_share_deletes_from_the_shares_table() {
        let http = replay(vec![write_ok(), dynamo_error(500, "InternalServerError")]);
        let client = metadata_client(http.clone());

        client
            .delete_share(&uuid_from(SHARE))
            .await
            .expect("delete_share");
        let err = client.delete_share(&uuid_from(SHARE)).await.unwrap_err();

        let body = &sent_bodies(&http)[0];
        assert_eq!(body["TableName"], "shares");
        assert_eq!(body["Key"]["id"]["S"], uuid_from(SHARE).to_string());
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }
}

#[cfg(test)]
mod parsing_tests {
    use super::*;
    use std::collections::HashMap;

    fn item(pairs: &[(&str, AttributeValue)]) -> HashMap<String, AttributeValue> {
        pairs
            .iter()
            .map(|(k, v)| ((*k).to_string(), v.clone()))
            .collect()
    }

    #[test]
    fn get_s_requires_a_string_attribute() {
        let item = item(&[
            ("name", AttributeValue::S("x".into())),
            ("size", AttributeValue::N("1".into())),
        ]);

        assert_eq!(get_s(&item, "name").unwrap(), "x");
        assert_eq!(
            get_s(&item, "size").unwrap_err().to_string(),
            "DynamoDB error: missing field: size"
        );
        assert!(get_s(&item, "absent").is_err());
    }

    #[test]
    fn numeric_getters_reject_non_numeric_and_out_of_range_values() {
        let item = item(&[
            ("n", AttributeValue::N("42".into())),
            ("huge", AttributeValue::N("4294967296".into())),
            ("text", AttributeValue::S("42".into())),
            ("bad", AttributeValue::N("nope".into())),
        ]);

        assert_eq!(get_n_u64(&item, "n").unwrap(), 42);
        assert_eq!(get_n_u32(&item, "n").unwrap(), 42);
        assert_eq!(get_n_u64(&item, "huge").unwrap(), 4_294_967_296);
        assert!(
            get_n_u32(&item, "huge").is_err(),
            "value beyond u32 is rejected"
        );
        assert!(get_n_u64(&item, "text").is_err());
        assert!(get_n_u64(&item, "bad").is_err());
        assert!(get_n_u32(&item, "missing").is_err());
    }

    #[test]
    fn get_bool_requires_a_boolean_attribute() {
        let item = item(&[
            ("flag", AttributeValue::Bool(true)),
            ("not_flag", AttributeValue::S("true".into())),
        ]);

        assert!(get_bool(&item, "flag").unwrap());
        assert_eq!(
            get_bool(&item, "not_flag").unwrap_err().to_string(),
            "DynamoDB error: missing bool field: not_flag"
        );
        assert!(get_bool(&item, "absent").is_err());
    }

    #[test]
    fn get_optional_s_returns_none_for_absent_or_mistyped_fields() {
        let item = item(&[
            ("here", AttributeValue::S("value".into())),
            ("number", AttributeValue::N("1".into())),
        ]);

        assert_eq!(get_optional_s(&item, "here"), Some("value".to_string()));
        assert_eq!(get_optional_s(&item, "number"), None);
        assert_eq!(get_optional_s(&item, "absent"), None);
    }

    #[test]
    fn parse_uuid_and_datetime_report_malformed_input() {
        let id = Uuid::nil();
        assert_eq!(parse_uuid(&id.to_string()).unwrap(), id);
        assert!(parse_uuid("nope")
            .unwrap_err()
            .to_string()
            .contains("invalid UUID"));

        let parsed = parse_datetime("2024-05-17T12:30:45+02:00").unwrap();
        assert_eq!(parsed.to_rfc3339(), "2024-05-17T10:30:45+00:00");
        assert!(parse_datetime("17/05/2024")
            .unwrap_err()
            .to_string()
            .contains("invalid datetime"));
    }

    #[test]
    fn parse_file_metadata_rejects_a_malformed_folder_id() {
        let mut item = item(&[
            ("id", AttributeValue::S(Uuid::nil().to_string())),
            ("name", AttributeValue::S("f".into())),
            ("mime_type", AttributeValue::S("text/plain".into())),
            ("size_bytes", AttributeValue::N("1".into())),
            ("s3_key", AttributeValue::S("k".into())),
            ("owner_id", AttributeValue::S(Uuid::nil().to_string())),
            ("version", AttributeValue::N("1".into())),
            ("is_trashed", AttributeValue::Bool(false)),
            (
                "created_at",
                AttributeValue::S("2024-05-17T12:30:45+00:00".into()),
            ),
            (
                "updated_at",
                AttributeValue::S("2024-05-17T12:30:45+00:00".into()),
            ),
        ]);
        item.insert("folder_id".into(), AttributeValue::S("not-a-uuid".into()));

        let err = parse_file_metadata(&item).unwrap_err();

        assert!(err.to_string().contains("invalid UUID"), "{err}");
    }

    #[test]
    fn parse_folder_rejects_a_malformed_parent_id() {
        let item = item(&[
            ("id", AttributeValue::S(Uuid::nil().to_string())),
            ("name", AttributeValue::S("Finance".into())),
            ("parent_id", AttributeValue::S("nope".into())),
            ("owner_id", AttributeValue::S(Uuid::nil().to_string())),
            (
                "created_at",
                AttributeValue::S("2024-05-17T12:30:45+00:00".into()),
            ),
            (
                "updated_at",
                AttributeValue::S("2024-05-17T12:30:45+00:00".into()),
            ),
        ]);

        assert!(parse_folder(&item)
            .unwrap_err()
            .to_string()
            .contains("invalid UUID"));
    }

    #[test]
    fn parse_file_version_requires_all_of_its_fields() {
        let complete = item(&[
            ("file_id", AttributeValue::S(Uuid::nil().to_string())),
            ("version", AttributeValue::N("2".into())),
            ("s3_key", AttributeValue::S("k".into())),
            ("size_bytes", AttributeValue::N("5".into())),
            ("created_by", AttributeValue::S(Uuid::nil().to_string())),
            (
                "created_at",
                AttributeValue::S("2024-05-17T12:30:45+00:00".into()),
            ),
        ]);
        assert_eq!(parse_file_version(&complete).unwrap().version, 2);

        let mut incomplete = complete.clone();
        incomplete.remove("s3_key");
        assert!(parse_file_version(&incomplete)
            .unwrap_err()
            .to_string()
            .contains("missing field: s3_key"));
    }

    #[test]
    fn parse_file_share_rejects_an_unknown_permission() {
        let item = item(&[
            ("id", AttributeValue::S(Uuid::nil().to_string())),
            ("file_id", AttributeValue::S(Uuid::nil().to_string())),
            ("shared_with", AttributeValue::S(Uuid::nil().to_string())),
            ("permission", AttributeValue::S("owner".into())),
            ("shared_by", AttributeValue::S(Uuid::nil().to_string())),
            (
                "created_at",
                AttributeValue::S("2024-05-17T12:30:45+00:00".into()),
            ),
        ]);

        let err = parse_file_share(&item).unwrap_err();

        assert_eq!(
            err.to_string(),
            "DynamoDB error: invalid permission: owner",
            "unknown permissions are not silently downgraded"
        );
    }

    #[test]
    fn is_conditional_check_failed_only_matches_the_condition_error() {
        use aws_sdk_dynamodb::error::SdkError;
        use aws_sdk_dynamodb::operation::update_item::UpdateItemError;
        use aws_sdk_dynamodb::types::error::ConditionalCheckFailedException;
        use aws_smithy_runtime_api::http::Response as HttpResponse;
        use aws_smithy_types::body::SdkBody;

        let raw = || HttpResponse::new(400.try_into().unwrap(), SdkBody::empty());

        let conditional = SdkError::service_error(
            UpdateItemError::ConditionalCheckFailedException(
                ConditionalCheckFailedException::builder().build(),
            ),
            raw(),
        );
        assert!(is_conditional_check_failed(&conditional));

        let other = SdkError::service_error(
            UpdateItemError::generic(
                aws_smithy_types::error::ErrorMetadata::builder()
                    .code("InternalServerError")
                    .build(),
            ),
            raw(),
        );
        assert!(!is_conditional_check_failed(&other));

        let timeout: SdkError<UpdateItemError> = SdkError::timeout_error("timed out");
        assert!(!is_conditional_check_failed(&timeout));
    }
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
