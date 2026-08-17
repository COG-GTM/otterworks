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

#[cfg(test)]
mod dynamo_tests {
    use super::*;
    use crate::models::test_support::dynamo_client;
    use aws_smithy_runtime::client::http::test_util::StaticReplayClient;
    use chrono::DateTime;
    use std::collections::HashMap;

    const OK_EMPTY: &str = "{}";
    const SERVER_ERROR: &str =
        r#"{"__type":"com.amazonaws.dynamodb.v20120810#InternalServerError","message":"boom"}"#;
    const CONDITIONAL_FAILED: &str = r#"{"__type":"com.amazonaws.dynamodb.v20120810#ConditionalCheckFailedException","message":"The conditional request failed"}"#;

    fn client(responses: Vec<(u16, String)>) -> (MetadataClient, StaticReplayClient) {
        let (client, http) = dynamo_client(responses);
        (
            MetadataClient {
                client,
                files_table: "files".into(),
                folders_table: "folders".into(),
                versions_table: "versions".into(),
                shares_table: "shares".into(),
            },
            http,
        )
    }

    fn ok(body: &str) -> (u16, String) {
        (200, body.to_string())
    }

    fn boom() -> (u16, String) {
        (500, SERVER_ERROR.to_string())
    }

    fn conditional_failure() -> (u16, String) {
        (400, CONDITIONAL_FAILED.to_string())
    }

    fn request_bodies(http: &StaticReplayClient) -> Vec<String> {
        http.actual_requests()
            .map(|r| String::from_utf8(r.body().bytes().unwrap().to_vec()).unwrap())
            .collect()
    }

    fn epoch() -> DateTime<Utc> {
        DateTime::from_timestamp(0, 0).unwrap()
    }

    fn file(id: Uuid, owner: Uuid, folder: Option<Uuid>) -> FileMetadata {
        FileMetadata {
            id,
            name: "report.pdf".into(),
            mime_type: "application/pdf".into(),
            size_bytes: 1024,
            s3_key: format!("files/{id}"),
            folder_id: folder,
            owner_id: owner,
            version: 3,
            is_trashed: false,
            created_at: epoch(),
            updated_at: epoch(),
        }
    }

    fn file_item_json(id: Uuid, owner: Uuid, trashed: bool) -> String {
        format!(
            r#"{{"id":{{"S":"{id}"}},"name":{{"S":"report.pdf"}},"mime_type":{{"S":"application/pdf"}},"size_bytes":{{"N":"1024"}},"s3_key":{{"S":"files/{id}"}},"owner_id":{{"S":"{owner}"}},"version":{{"N":"3"}},"is_trashed":{{"BOOL":{trashed}}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}},"updated_at":{{"S":"1970-01-01T00:00:00+00:00"}}}}"#
        )
    }

    fn folder_item_json(id: Uuid, owner: Uuid) -> String {
        format!(
            r#"{{"id":{{"S":"{id}"}},"name":{{"S":"Finance"}},"owner_id":{{"S":"{owner}"}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}},"updated_at":{{"S":"1970-01-01T00:00:00+00:00"}}}}"#
        )
    }

    fn share_item_json(id: Uuid, file_id: Uuid, user: Uuid, permission: &str) -> String {
        format!(
            r#"{{"id":{{"S":"{id}"}},"file_id":{{"S":"{file_id}"}},"shared_with":{{"S":"{user}"}},"permission":{{"S":"{permission}"}},"shared_by":{{"S":"{user}"}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}}}}"#
        )
    }

    fn version_item_json(file_id: Uuid, user: Uuid, version: u32) -> String {
        format!(
            r#"{{"file_id":{{"S":"{file_id}"}},"version":{{"N":"{version}"}},"s3_key":{{"S":"files/{file_id}/v{version}"}},"size_bytes":{{"N":"2048"}},"created_by":{{"S":"{user}"}},"created_at":{{"S":"1970-01-01T00:00:00+00:00"}}}}"#
        )
    }

    fn item_response(item: &str) -> String {
        format!(r#"{{"Item":{item}}}"#)
    }

    fn page(items: &[String], last_key: Option<&str>) -> String {
        let items = items.join(",");
        match last_key {
            Some(k) => format!(
                r#"{{"Items":[{items}],"Count":1,"LastEvaluatedKey":{{"id":{{"S":"{k}"}}}}}}"#
            ),
            None => format!(r#"{{"Items":[{items}],"Count":1}}"#),
        }
    }

    #[tokio::test]
    async fn new_takes_every_table_name_from_config() {
        let metadata = MetadataClient::new(&AwsConfig {
            region: "us-east-1".into(),
            endpoint_url: Some("http://localstack:4566".into()),
            s3_bucket: "bucket".into(),
            dynamodb_table: "cfg-files".into(),
            dynamodb_folders_table: "cfg-folders".into(),
            dynamodb_versions_table: "cfg-versions".into(),
            dynamodb_shares_table: "cfg-shares".into(),
        })
        .await;

        assert_eq!(metadata.files_table, "cfg-files");
        assert_eq!(metadata.folders_table, "cfg-folders");
        assert_eq!(metadata.versions_table, "cfg-versions");
        assert_eq!(metadata.shares_table, "cfg-shares");
    }

    #[tokio::test]
    async fn put_file_writes_every_attribute_including_the_optional_folder() {
        let (meta, http) = client(vec![ok(OK_EMPTY)]);
        let (id, owner, folder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());

        meta.put_file(&file(id, owner, Some(folder)))
            .await
            .expect("put_file");

        let body = &request_bodies(&http)[0];
        assert!(body.contains(r#""TableName":"files""#), "{body}");
        assert!(body.contains(&id.to_string()), "{body}");
        assert!(body.contains(&folder.to_string()), "{body}");
        assert!(body.contains("report.pdf"), "{body}");
        assert!(body.contains(r#""size_bytes":{"N":"1024"}"#), "{body}");
    }

    #[tokio::test]
    async fn put_file_omits_folder_id_when_the_file_is_at_the_root() {
        let (meta, http) = client(vec![ok(OK_EMPTY)]);

        meta.put_file(&file(Uuid::new_v4(), Uuid::new_v4(), None))
            .await
            .expect("put_file");

        assert!(!request_bodies(&http)[0].contains("folder_id"));
    }

    #[tokio::test]
    async fn put_file_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);

        let err = meta
            .put_file(&file(Uuid::new_v4(), Uuid::new_v4(), None))
            .await
            .expect_err("500");

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn get_file_parses_the_stored_item() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, _http) = client(vec![ok(&item_response(&file_item_json(id, owner, false)))]);

        let file = meta.get_file(&id).await.expect("get_file");

        assert_eq!(file.id, id);
        assert_eq!(file.owner_id, owner);
        assert_eq!(file.size_bytes, 1024);
        assert_eq!(file.version, 3);
    }

    #[tokio::test]
    async fn get_file_reports_a_missing_item_as_file_not_found() {
        let id = Uuid::new_v4();
        let (meta, _http) = client(vec![ok(OK_EMPTY)]);

        let err = meta.get_file(&id).await.expect_err("no item");

        assert!(matches!(err, ServiceError::FileNotFound(ref f) if *f == id.to_string()));
    }

    #[tokio::test]
    async fn get_file_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.get_file(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn delete_file_targets_the_files_table_by_id() {
        let id = Uuid::new_v4();
        let (meta, http) = client(vec![ok(OK_EMPTY)]);

        meta.delete_file(&id).await.expect("delete_file");

        let body = &request_bodies(&http)[0];
        assert!(body.contains(r#""TableName":"files""#), "{body}");
        assert!(body.contains(&id.to_string()), "{body}");
    }

    #[tokio::test]
    async fn delete_file_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.delete_file(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn trash_file_flags_the_file_and_returns_the_updated_row() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = client(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item_json(id, owner, true))),
        ]);

        let file = meta.trash_file(&id).await.expect("trash_file");

        assert!(file.is_trashed);
        let update = &request_bodies(&http)[0];
        assert!(
            update.contains("SET is_trashed = :t, updated_at = :u"),
            "{update}"
        );
        assert!(update.contains(r#":t":{"BOOL":true}"#), "{update}");
        assert!(update.contains("attribute_exists(id)"), "{update}");
    }

    #[tokio::test]
    async fn trash_file_translates_a_failed_condition_into_file_not_found() {
        let id = Uuid::new_v4();
        let (meta, _http) = client(vec![conditional_failure()]);

        let err = meta.trash_file(&id).await.expect_err("condition failed");

        assert!(matches!(err, ServiceError::FileNotFound(ref f) if *f == id.to_string()));
    }

    #[tokio::test]
    async fn trash_file_maps_other_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.trash_file(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn restore_file_clears_the_trashed_flag() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = client(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item_json(id, owner, false))),
        ]);

        let file = meta.restore_file(&id).await.expect("restore_file");

        assert!(!file.is_trashed);
        assert!(request_bodies(&http)[0].contains(r#":t":{"BOOL":false}"#));
    }

    #[tokio::test]
    async fn restore_file_translates_a_failed_condition_into_file_not_found() {
        let id = Uuid::new_v4();
        let (meta, _http) = client(vec![conditional_failure()]);
        let err = meta.restore_file(&id).await.expect_err("condition failed");
        assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn restore_file_maps_other_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.restore_file(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn rename_file_sets_the_reserved_name_attribute() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = client(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item_json(id, owner, false))),
        ]);

        meta.rename_file(&id, "renamed.pdf")
            .await
            .expect("rename_file");

        let update = &request_bodies(&http)[0];
        assert!(update.contains("\"#n\":\"name\""), "{update}");
        assert!(update.contains("renamed.pdf"), "{update}");
    }

    #[tokio::test]
    async fn rename_file_translates_a_failed_condition_into_file_not_found() {
        let (meta, _http) = client(vec![conditional_failure()]);
        let err = meta
            .rename_file(&Uuid::new_v4(), "x")
            .await
            .expect_err("condition failed");
        assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn rename_file_maps_other_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .rename_file(&Uuid::new_v4(), "x")
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn move_file_into_a_folder_sets_folder_id() {
        let (id, owner, folder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = client(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item_json(id, owner, false))),
        ]);

        meta.move_file(&id, Some(folder)).await.expect("move_file");

        let update = &request_bodies(&http)[0];
        assert!(
            update.contains("SET folder_id = :f, updated_at = :u"),
            "{update}"
        );
        assert!(update.contains(&folder.to_string()), "{update}");
    }

    #[tokio::test]
    async fn move_file_to_the_root_removes_folder_id() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = client(vec![
            ok(OK_EMPTY),
            ok(&item_response(&file_item_json(id, owner, false))),
        ]);

        meta.move_file(&id, None).await.expect("move_file");

        assert!(request_bodies(&http)[0].contains("SET updated_at = :u REMOVE folder_id"));
    }

    #[tokio::test]
    async fn move_file_translates_a_failed_condition_into_file_not_found() {
        let (meta, _http) = client(vec![conditional_failure()]);
        let err = meta
            .move_file(&Uuid::new_v4(), None)
            .await
            .expect_err("condition failed");
        assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn move_file_maps_other_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .move_file(&Uuid::new_v4(), None)
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_trashed_filters_by_owner_and_returns_newest_first() {
        let owner = Uuid::new_v4();
        let (old_id, new_id) = (Uuid::new_v4(), Uuid::new_v4());
        let older = file_item_json(old_id, owner, true);
        let newer = file_item_json(new_id, owner, true).replace(
            "1970-01-01T00:00:00+00:00\"}}",
            "1971-01-01T00:00:00+00:00\"}}",
        );
        let (meta, http) = client(vec![ok(&page(&[older, newer], None))]);

        let files = meta.list_trashed(Some(owner)).await.expect("list_trashed");

        assert_eq!(files.len(), 2);
        assert_eq!(files[0].id, new_id, "most recently updated first");
        let scan = &request_bodies(&http)[0];
        assert!(
            scan.contains("is_trashed = :trashed AND owner_id = :owner_id"),
            "{scan}"
        );
    }

    #[tokio::test]
    async fn list_trashed_without_an_owner_filters_only_on_the_trash_flag() {
        let (meta, http) = client(vec![ok(&page(&[], None))]);

        let files = meta.list_trashed(None).await.expect("list_trashed");

        assert!(files.is_empty());
        let scan = &request_bodies(&http)[0];
        assert!(
            scan.contains(r#""FilterExpression":"is_trashed = :trashed""#),
            "{scan}"
        );
    }

    #[tokio::test]
    async fn list_trashed_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.list_trashed(None).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_files_filters_by_folder_owner_and_trash_state() {
        let (owner, folder) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = client(vec![ok(&page(
            &[file_item_json(Uuid::new_v4(), owner, false)],
            None,
        ))]);

        let files = meta
            .list_files(Some(folder), Some(owner), false)
            .await
            .expect("list_files");

        assert_eq!(files.len(), 1);
        let scan = &request_bodies(&http)[0];
        assert!(
            scan.contains(
                "folder_id = :folder_id AND owner_id = :owner_id AND is_trashed = :trashed"
            ),
            "{scan}"
        );
    }

    #[tokio::test]
    async fn list_files_including_trash_sends_no_filter_at_all() {
        let (meta, http) = client(vec![ok(&page(&[], None))]);

        meta.list_files(None, None, true).await.expect("list_files");

        assert!(!request_bodies(&http)[0].contains("FilterExpression"));
    }

    #[tokio::test]
    async fn list_files_follows_the_paginator_across_pages() {
        let owner = Uuid::new_v4();
        let first = page(
            &[file_item_json(Uuid::new_v4(), owner, false)],
            Some("cursor"),
        );
        let second = page(&[file_item_json(Uuid::new_v4(), owner, false)], None);
        let (meta, http) = client(vec![ok(&first), ok(&second)]);

        let files = meta.list_files(None, None, true).await.expect("list_files");

        assert_eq!(files.len(), 2, "both pages are collected");
        assert_eq!(http.actual_requests().count(), 2);
        assert!(request_bodies(&http)[1].contains("ExclusiveStartKey"));
    }

    #[tokio::test]
    async fn list_files_surfaces_unparseable_items() {
        let broken = r#"{"id":{"S":"not-a-uuid"}}"#.to_string();
        let (meta, _http) = client(vec![ok(&page(&[broken], None))]);

        let err = meta
            .list_files(None, None, true)
            .await
            .expect_err("bad item");

        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_files_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.list_files(None, None, true).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    fn folder(id: Uuid, owner: Uuid, parent: Option<Uuid>) -> Folder {
        Folder {
            id,
            name: "Finance".into(),
            parent_id: parent,
            owner_id: owner,
            created_at: epoch(),
            updated_at: epoch(),
        }
    }

    #[tokio::test]
    async fn put_folder_writes_the_parent_when_present() {
        let (meta, http) = client(vec![ok(OK_EMPTY), ok(OK_EMPTY)]);
        let parent = Uuid::new_v4();

        meta.put_folder(&folder(Uuid::new_v4(), Uuid::new_v4(), Some(parent)))
            .await
            .expect("put_folder");
        meta.put_folder(&folder(Uuid::new_v4(), Uuid::new_v4(), None))
            .await
            .expect("put_folder");

        let bodies = request_bodies(&http);
        assert!(
            bodies[0].contains(r#""TableName":"folders""#),
            "{}",
            bodies[0]
        );
        assert!(bodies[0].contains(&parent.to_string()), "{}", bodies[0]);
        assert!(!bodies[1].contains("parent_id"), "{}", bodies[1]);
    }

    #[tokio::test]
    async fn put_folder_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .put_folder(&folder(Uuid::new_v4(), Uuid::new_v4(), None))
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn get_folder_parses_the_stored_item() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, _http) = client(vec![ok(&item_response(&folder_item_json(id, owner)))]);

        let folder = meta.get_folder(&id).await.expect("get_folder");

        assert_eq!(folder.id, id);
        assert_eq!(folder.name, "Finance");
        assert!(folder.parent_id.is_none());
    }

    #[tokio::test]
    async fn get_folder_reports_a_missing_item_as_folder_not_found() {
        let (meta, _http) = client(vec![ok(OK_EMPTY)]);
        let err = meta.get_folder(&Uuid::new_v4()).await.expect_err("no item");
        assert!(matches!(err, ServiceError::FolderNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn get_folder_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.get_folder(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn update_folder_sets_only_the_supplied_fields() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let parent = Uuid::new_v4();
        let (meta, http) = client(vec![
            ok(OK_EMPTY),
            ok(&item_response(&folder_item_json(id, owner))),
            ok(OK_EMPTY),
            ok(&item_response(&folder_item_json(id, owner))),
        ]);

        meta.update_folder(&id, Some("Renamed".into()), Some(parent))
            .await
            .expect("update_folder");
        meta.update_folder(&id, None, None)
            .await
            .expect("update_folder");

        let bodies = request_bodies(&http);
        assert!(
            bodies[0].contains("SET updated_at = :u, #n = :n, parent_id = :p"),
            "{}",
            bodies[0]
        );
        assert!(bodies[0].contains("Renamed"), "{}", bodies[0]);
        assert!(
            bodies[2].contains(r#""UpdateExpression":"SET updated_at = :u""#),
            "{}",
            bodies[2]
        );
    }

    #[tokio::test]
    async fn update_folder_translates_a_failed_condition_into_folder_not_found() {
        let (meta, _http) = client(vec![conditional_failure()]);
        let err = meta
            .update_folder(&Uuid::new_v4(), None, None)
            .await
            .expect_err("condition failed");
        assert!(matches!(err, ServiceError::FolderNotFound(_)), "{err:?}");
    }

    #[tokio::test]
    async fn update_folder_maps_other_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .update_folder(&Uuid::new_v4(), None, None)
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn delete_folder_targets_the_folders_table() {
        let id = Uuid::new_v4();
        let (meta, http) = client(vec![ok(OK_EMPTY)]);

        meta.delete_folder(&id).await.expect("delete_folder");

        let body = &request_bodies(&http)[0];
        assert!(body.contains(r#""TableName":"folders""#), "{body}");
        assert!(body.contains(&id.to_string()), "{body}");
    }

    #[tokio::test]
    async fn delete_folder_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.delete_folder(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_folders_scopes_to_a_parent_and_owner() {
        let (owner, parent) = (Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = client(vec![ok(&page(
            &[folder_item_json(Uuid::new_v4(), owner)],
            None,
        ))]);

        let folders = meta
            .list_folders(Some(parent), Some(owner))
            .await
            .expect("list_folders");

        assert_eq!(folders.len(), 1);
        assert!(
            request_bodies(&http)[0].contains("parent_id = :parent_id AND owner_id = :owner_id")
        );
    }

    #[tokio::test]
    async fn list_folders_at_the_root_requires_a_missing_parent() {
        let (meta, http) = client(vec![ok(&page(&[], None))]);

        meta.list_folders(None, None).await.expect("list_folders");

        assert!(request_bodies(&http)[0].contains("attribute_not_exists(parent_id)"));
    }

    #[tokio::test]
    async fn list_folders_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.list_folders(None, None).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn put_version_writes_to_the_versions_table() {
        let (meta, http) = client(vec![ok(OK_EMPTY)]);
        let file_id = Uuid::new_v4();

        meta.put_version(&FileVersion {
            file_id,
            version: 7,
            s3_key: "files/x/v7".into(),
            size_bytes: 2048,
            created_by: Uuid::new_v4(),
            created_at: epoch(),
        })
        .await
        .expect("put_version");

        let body = &request_bodies(&http)[0];
        assert!(body.contains(r#""TableName":"versions""#), "{body}");
        assert!(body.contains(r#""version":{"N":"7"}"#), "{body}");
        assert!(body.contains(&file_id.to_string()), "{body}");
    }

    #[tokio::test]
    async fn put_version_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .put_version(&FileVersion {
                file_id: Uuid::new_v4(),
                version: 1,
                s3_key: "k".into(),
                size_bytes: 1,
                created_by: Uuid::new_v4(),
                created_at: epoch(),
            })
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_versions_queries_newest_first() {
        let (file_id, user) = (Uuid::new_v4(), Uuid::new_v4());
        let items = format!(
            r#"{{"Items":[{},{}],"Count":2}}"#,
            version_item_json(file_id, user, 2),
            version_item_json(file_id, user, 1)
        );
        let (meta, http) = client(vec![ok(&items)]);

        let versions = meta.list_versions(&file_id).await.expect("list_versions");

        assert_eq!(versions.len(), 2);
        assert_eq!(versions[0].version, 2);
        let body = &request_bodies(&http)[0];
        assert!(body.contains(r#""ScanIndexForward":false"#), "{body}");
        assert!(body.contains("file_id = :fid"), "{body}");
    }

    #[tokio::test]
    async fn list_versions_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.list_versions(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    fn share(id: Uuid, file_id: Uuid, user: Uuid) -> FileShare {
        FileShare {
            id,
            file_id,
            shared_with: user,
            permission: SharePermission::Editor,
            shared_by: Uuid::new_v4(),
            created_at: epoch(),
        }
    }

    #[tokio::test]
    async fn put_share_stores_the_permission_as_its_wire_value() {
        let (meta, http) = client(vec![ok(OK_EMPTY)]);

        meta.put_share(&share(Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4()))
            .await
            .expect("put_share");

        let body = &request_bodies(&http)[0];
        assert!(body.contains(r#""TableName":"shares""#), "{body}");
        assert!(body.contains(r#""permission":{"S":"editor"}"#), "{body}");
    }

    #[tokio::test]
    async fn put_share_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .put_share(&share(Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4()))
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn find_existing_share_returns_the_matching_share() {
        let (share_id, file_id, user) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
        let (meta, http) = client(vec![ok(&page(
            &[share_item_json(share_id, file_id, user, "viewer")],
            None,
        ))]);

        let found = meta
            .find_existing_share(&file_id, &user)
            .await
            .expect("find_existing_share")
            .expect("a share exists");

        assert_eq!(found.id, share_id);
        assert_eq!(found.permission, SharePermission::Viewer);
        assert!(request_bodies(&http)[0].contains("file_id = :fid AND shared_with = :uid"));
    }

    #[tokio::test]
    async fn find_existing_share_returns_none_when_nothing_matches() {
        let (meta, _http) = client(vec![ok(&page(&[], None))]);

        let found = meta
            .find_existing_share(&Uuid::new_v4(), &Uuid::new_v4())
            .await
            .expect("find_existing_share");

        assert!(found.is_none());
    }

    #[tokio::test]
    async fn find_existing_share_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .find_existing_share(&Uuid::new_v4(), &Uuid::new_v4())
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_shares_for_user_collects_every_page() {
        let user = Uuid::new_v4();
        let first = page(
            &[share_item_json(
                Uuid::new_v4(),
                Uuid::new_v4(),
                user,
                "viewer",
            )],
            Some("cursor"),
        );
        let second = page(
            &[share_item_json(
                Uuid::new_v4(),
                Uuid::new_v4(),
                user,
                "editor",
            )],
            None,
        );
        let (meta, http) = client(vec![ok(&first), ok(&second)]);

        let shares = meta
            .list_shares_for_user(&user)
            .await
            .expect("list_shares_for_user");

        assert_eq!(shares.len(), 2);
        assert!(request_bodies(&http)[0].contains("shared_with = :uid"));
    }

    #[tokio::test]
    async fn list_shares_for_user_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .list_shares_for_user(&Uuid::new_v4())
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_shares_by_owner_filters_on_shared_by() {
        let owner = Uuid::new_v4();
        let (meta, http) = client(vec![ok(&page(
            &[share_item_json(
                Uuid::new_v4(),
                Uuid::new_v4(),
                owner,
                "viewer",
            )],
            None,
        ))]);

        let shares = meta
            .list_shares_by_owner(&owner)
            .await
            .expect("list_shares_by_owner");

        assert_eq!(shares.len(), 1);
        assert!(request_bodies(&http)[0].contains("shared_by = :uid"));
    }

    #[tokio::test]
    async fn list_shares_by_owner_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta
            .list_shares_by_owner(&Uuid::new_v4())
            .await
            .expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn list_shares_returns_every_share_on_a_file() {
        let file_id = Uuid::new_v4();
        let (meta, http) = client(vec![ok(&page(
            &[share_item_json(
                Uuid::new_v4(),
                file_id,
                Uuid::new_v4(),
                "viewer",
            )],
            None,
        ))]);

        let shares = meta.list_shares(&file_id).await.expect("list_shares");

        assert_eq!(shares.len(), 1);
        assert_eq!(shares[0].file_id, file_id);
        assert!(request_bodies(&http)[0].contains("file_id = :fid"));
    }

    #[tokio::test]
    async fn list_shares_surfaces_an_unknown_permission() {
        let (meta, _http) = client(vec![ok(&page(
            &[share_item_json(
                Uuid::new_v4(),
                Uuid::new_v4(),
                Uuid::new_v4(),
                "owner",
            )],
            None,
        ))]);

        let err = meta
            .list_shares(&Uuid::new_v4())
            .await
            .expect_err("bad row");

        assert!(
            err.to_string().contains("invalid permission: owner"),
            "{err}"
        );
    }

    #[tokio::test]
    async fn list_shares_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.list_shares(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    #[tokio::test]
    async fn delete_share_targets_the_shares_table() {
        let id = Uuid::new_v4();
        let (meta, http) = client(vec![ok(OK_EMPTY)]);

        meta.delete_share(&id).await.expect("delete_share");

        let body = &request_bodies(&http)[0];
        assert!(body.contains(r#""TableName":"shares""#), "{body}");
        assert!(body.contains(&id.to_string()), "{body}");
    }

    #[tokio::test]
    async fn delete_share_maps_dynamo_failures() {
        let (meta, _http) = client(vec![boom()]);
        let err = meta.delete_share(&Uuid::new_v4()).await.expect_err("500");
        assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
    }

    // -- parsing helpers --

    #[test]
    fn getters_report_the_missing_or_mistyped_field() {
        let mut item: HashMap<String, AttributeValue> = HashMap::new();
        item.insert("s".into(), AttributeValue::S("v".into()));
        item.insert("n".into(), AttributeValue::N("12".into()));
        item.insert("big".into(), AttributeValue::N("-1".into()));
        item.insert("b".into(), AttributeValue::Bool(true));

        assert_eq!(get_s(&item, "s").unwrap(), "v");
        assert_eq!(get_n_u64(&item, "n").unwrap(), 12);
        assert_eq!(get_n_u32(&item, "n").unwrap(), 12);
        assert!(get_bool(&item, "b").unwrap());
        assert_eq!(get_optional_s(&item, "s").as_deref(), Some("v"));
        assert_eq!(get_optional_s(&item, "absent"), None);

        assert_eq!(
            get_s(&item, "n").unwrap_err().to_string(),
            "DynamoDB error: missing field: n"
        );
        assert_eq!(
            get_n_u64(&item, "big").unwrap_err().to_string(),
            "DynamoDB error: missing numeric field: big"
        );
        assert_eq!(
            get_n_u32(&item, "big").unwrap_err().to_string(),
            "DynamoDB error: missing numeric field: big"
        );
        assert_eq!(
            get_bool(&item, "s").unwrap_err().to_string(),
            "DynamoDB error: missing bool field: s"
        );
    }

    #[test]
    fn scalar_parsers_reject_malformed_values() {
        assert!(parse_uuid("not-a-uuid")
            .unwrap_err()
            .to_string()
            .starts_with("DynamoDB error: invalid UUID"));
        assert_eq!(parse_uuid(&Uuid::nil().to_string()).unwrap(), Uuid::nil());
        assert!(parse_datetime("yesterday")
            .unwrap_err()
            .to_string()
            .starts_with("DynamoDB error: invalid datetime"));
        assert_eq!(
            parse_datetime("1970-01-01T00:00:00+00:00").unwrap(),
            epoch()
        );
    }

    #[test]
    fn parse_file_metadata_rejects_a_malformed_folder_reference() {
        let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
        let mut item: HashMap<String, AttributeValue> = HashMap::new();
        item.insert("id".into(), AttributeValue::S(id.to_string()));
        item.insert("name".into(), AttributeValue::S("a".into()));
        item.insert("mime_type".into(), AttributeValue::S("text/plain".into()));
        item.insert("size_bytes".into(), AttributeValue::N("1".into()));
        item.insert("s3_key".into(), AttributeValue::S("k".into()));
        item.insert("owner_id".into(), AttributeValue::S(owner.to_string()));
        item.insert("version".into(), AttributeValue::N("1".into()));
        item.insert("is_trashed".into(), AttributeValue::Bool(false));
        item.insert(
            "created_at".into(),
            AttributeValue::S("1970-01-01T00:00:00+00:00".into()),
        );
        item.insert(
            "updated_at".into(),
            AttributeValue::S("1970-01-01T00:00:00+00:00".into()),
        );
        item.insert("folder_id".into(), AttributeValue::S("nope".into()));

        let err = parse_file_metadata(&item).expect_err("bad folder id");

        assert!(err.to_string().contains("invalid UUID"), "{err}");
    }

    #[test]
    fn parse_folder_and_version_report_missing_fields() {
        let empty: HashMap<String, AttributeValue> = HashMap::new();

        assert_eq!(
            parse_folder(&empty).unwrap_err().to_string(),
            "DynamoDB error: missing field: id"
        );
        assert_eq!(
            parse_file_version(&empty).unwrap_err().to_string(),
            "DynamoDB error: missing field: file_id"
        );
        assert_eq!(
            parse_file_share(&empty).unwrap_err().to_string(),
            "DynamoDB error: missing field: permission"
        );
    }
}
