//! `MetadataClient` against a faked DynamoDB HTTP boundary.

mod common;

use aws_smithy_runtime::client::http::test_util::StaticReplayClient;
use common::*;
use file_service::errors::ServiceError;
use file_service::models::{FileMetadata, FileShare, FileVersion, Folder, SharePermission};
use serde_json::{json, Value};
use uuid::Uuid;

fn sent(http: &StaticReplayClient) -> Vec<Value> {
    http.actual_requests()
        .map(|req| serde_json::from_slice(req.body().bytes().unwrap_or_default()).unwrap())
        .collect()
}

fn sample_file(id: Uuid, owner: Uuid, folder: Option<Uuid>) -> FileMetadata {
    FileMetadata {
        id,
        name: "quarterly.pdf".into(),
        mime_type: "application/pdf".into(),
        size_bytes: 2048,
        s3_key: format!("files/{owner}/{id}"),
        folder_id: folder,
        owner_id: owner,
        version: 1,
        is_trashed: false,
        created_at: fixed_time(),
        updated_at: fixed_time(),
    }
}

// -- Files --

#[tokio::test]
async fn put_file_writes_every_attribute() {
    let (id, owner, folder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({}))]);

    meta.put_file(&sample_file(id, owner, Some(folder)))
        .await
        .unwrap();

    let body = &sent(&http)[0];
    assert_eq!(body["TableName"], FILES_TABLE);
    assert_eq!(body["Item"]["id"]["S"], id.to_string());
    assert_eq!(body["Item"]["name"]["S"], "quarterly.pdf");
    assert_eq!(body["Item"]["size_bytes"]["N"], "2048");
    assert_eq!(body["Item"]["folder_id"]["S"], folder.to_string());
    assert_eq!(body["Item"]["is_trashed"]["BOOL"], false);
}

#[tokio::test]
async fn put_file_omits_folder_id_for_root_level_files() {
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({}))]);

    meta.put_file(&sample_file(Uuid::new_v4(), Uuid::new_v4(), None))
        .await
        .unwrap();

    assert!(sent(&http)[0]["Item"].get("folder_id").is_none());
}

#[tokio::test]
async fn put_file_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .put_file(&sample_file(Uuid::new_v4(), Uuid::new_v4(), None))
        .await
        .expect_err("a 400 is an error");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn get_file_parses_the_stored_item() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![dynamo_ok(
        json!({ "Item": file_item(&id, &owner, "a.txt", None, false) }),
    )]);

    let file = meta.get_file(&id).await.unwrap();

    assert_eq!(file.id, id);
    assert_eq!(file.name, "a.txt");
    assert_eq!(sent(&http)[0]["Key"]["id"]["S"], id.to_string());
}

#[tokio::test]
async fn get_file_reports_a_missing_item_as_not_found() {
    let id = Uuid::new_v4();
    let (meta, _http) = metadata_client(vec![dynamo_ok(json!({}))]);

    let err = meta.get_file(&id).await.expect_err("no item");

    match err {
        ServiceError::FileNotFound(reported) => assert_eq!(reported, id.to_string()),
        other => panic!("expected FileNotFound, got {other:?}"),
    }
}

#[tokio::test]
async fn get_file_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ProvisionedThroughputExceededException")]);

    let err = meta.get_file(&Uuid::new_v4()).await.expect_err("throttled");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn delete_file_targets_the_files_table() {
    let id = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({}))]);

    meta.delete_file(&id).await.unwrap();

    let body = &sent(&http)[0];
    assert_eq!(body["TableName"], FILES_TABLE);
    assert_eq!(body["Key"]["id"]["S"], id.to_string());
}

#[tokio::test]
async fn delete_file_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.delete_file(&Uuid::new_v4()).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn trash_file_flags_the_item_and_returns_it() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, true) })),
    ]);

    let file = meta.trash_file(&id).await.unwrap();

    assert!(file.is_trashed);
    let update = &sent(&http)[0];
    assert_eq!(update["ExpressionAttributeValues"][":t"]["BOOL"], true);
    assert_eq!(update["ConditionExpression"], "attribute_exists(id)");
}

#[tokio::test]
async fn trash_file_reports_a_failed_condition_as_not_found() {
    let id = Uuid::new_v4();
    let (meta, _http) = metadata_client(vec![dynamo_err("ConditionalCheckFailedException")]);

    let err = meta.trash_file(&id).await.expect_err("no such file");

    match err {
        ServiceError::FileNotFound(reported) => assert_eq!(reported, id.to_string()),
        other => panic!("expected FileNotFound, got {other:?}"),
    }
}

#[tokio::test]
async fn trash_file_maps_other_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.trash_file(&Uuid::new_v4()).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn restore_file_clears_the_trashed_flag() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
    ]);

    let file = meta.restore_file(&id).await.unwrap();

    assert!(!file.is_trashed);
    assert_eq!(
        sent(&http)[0]["ExpressionAttributeValues"][":t"]["BOOL"],
        false
    );
}

#[tokio::test]
async fn restore_file_reports_a_failed_condition_as_not_found() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ConditionalCheckFailedException")]);

    let err = meta.restore_file(&Uuid::new_v4()).await.expect_err("gone");

    assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
}

#[tokio::test]
async fn restore_file_maps_other_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.restore_file(&Uuid::new_v4()).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn rename_file_sets_the_name_through_an_alias() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "renamed.txt", None, false) })),
    ]);

    let file = meta.rename_file(&id, "renamed.txt").await.unwrap();

    assert_eq!(file.name, "renamed.txt");
    let update = &sent(&http)[0];
    assert_eq!(update["ExpressionAttributeNames"]["#n"], "name");
    assert_eq!(
        update["ExpressionAttributeValues"][":n"]["S"],
        "renamed.txt"
    );
}

#[tokio::test]
async fn rename_file_reports_a_failed_condition_as_not_found() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ConditionalCheckFailedException")]);

    let err = meta
        .rename_file(&Uuid::new_v4(), "x")
        .await
        .expect_err("gone");

    assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
}

#[tokio::test]
async fn rename_file_maps_other_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .rename_file(&Uuid::new_v4(), "x")
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn move_file_into_a_folder_sets_folder_id() {
    let (id, owner, folder) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", Some(&folder), false) })),
    ]);

    let file = meta.move_file(&id, Some(folder)).await.unwrap();

    assert_eq!(file.folder_id, Some(folder));
    let update = &sent(&http)[0];
    assert_eq!(
        update["UpdateExpression"],
        "SET folder_id = :f, updated_at = :u"
    );
    assert_eq!(
        update["ExpressionAttributeValues"][":f"]["S"],
        folder.to_string()
    );
}

#[tokio::test]
async fn move_file_to_the_root_removes_folder_id() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": file_item(&id, &owner, "a.txt", None, false) })),
    ]);

    let file = meta.move_file(&id, None).await.unwrap();

    assert_eq!(file.folder_id, None);
    assert_eq!(
        sent(&http)[0]["UpdateExpression"],
        "SET updated_at = :u REMOVE folder_id"
    );
}

#[tokio::test]
async fn move_file_reports_a_failed_condition_as_not_found() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ConditionalCheckFailedException")]);

    let err = meta
        .move_file(&Uuid::new_v4(), None)
        .await
        .expect_err("gone");

    assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
}

#[tokio::test]
async fn move_file_maps_other_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .move_file(&Uuid::new_v4(), None)
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_files_filters_on_folder_owner_and_trashed() {
    let (owner, folder) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![scan_page(
        vec![file_item(
            &Uuid::new_v4(),
            &owner,
            "a.txt",
            Some(&folder),
            false,
        )],
        None,
    )]);

    let files = meta
        .list_files(Some(folder), Some(owner), false)
        .await
        .unwrap();

    assert_eq!(files.len(), 1);
    let scan = &sent(&http)[0];
    assert_eq!(
        scan["FilterExpression"],
        "folder_id = :folder_id AND owner_id = :owner_id AND is_trashed = :trashed"
    );
    assert_eq!(scan["ExpressionAttributeValues"][":trashed"]["BOOL"], false);
}

#[tokio::test]
async fn list_files_without_filters_scans_the_whole_table() {
    let (meta, http) = metadata_client(vec![scan_page(vec![], None)]);

    let files = meta.list_files(None, None, true).await.unwrap();

    assert!(files.is_empty());
    assert!(sent(&http)[0].get("FilterExpression").is_none());
}

#[tokio::test]
async fn list_files_follows_every_scan_page() {
    let owner = Uuid::new_v4();
    let first = Uuid::new_v4();
    let second = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![
        scan_page(
            vec![file_item(&first, &owner, "a.txt", None, false)],
            Some(key_of(&first)),
        ),
        scan_page(vec![file_item(&second, &owner, "b.txt", None, false)], None),
    ]);

    let files = meta.list_files(None, None, true).await.unwrap();

    assert_eq!(files.len(), 2, "both pages are collected");
    assert_eq!(sent(&http).len(), 2);
}

#[tokio::test]
async fn list_files_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.list_files(None, None, true).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_files_rejects_a_corrupt_item() {
    let mut item = file_item(&Uuid::new_v4(), &Uuid::new_v4(), "a.txt", None, false);
    item["size_bytes"] = json!({ "S": "not-a-number" });
    let (meta, _http) = metadata_client(vec![scan_page(vec![item], None)]);

    let err = meta
        .list_files(None, None, true)
        .await
        .expect_err("corrupt");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_trashed_filters_by_owner() {
    let owner = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![scan_page(
        vec![file_item(&Uuid::new_v4(), &owner, "a.txt", None, true)],
        None,
    )]);

    let files = meta.list_trashed(Some(owner)).await.unwrap();

    assert_eq!(files.len(), 1);
    let scan = &sent(&http)[0];
    assert_eq!(
        scan["FilterExpression"],
        "is_trashed = :trashed AND owner_id = :owner_id"
    );
    assert_eq!(scan["ExpressionAttributeValues"][":trashed"]["BOOL"], true);
}

#[tokio::test]
async fn list_trashed_sorts_newest_first_across_pages() {
    let owner = Uuid::new_v4();
    let older = Uuid::new_v4();
    let newer = Uuid::new_v4();
    let mut older_item = file_item(&older, &owner, "older.txt", None, true);
    older_item["updated_at"] = json!({ "S": "2024-01-01T00:00:00+00:00" });
    let mut newer_item = file_item(&newer, &owner, "newer.txt", None, true);
    newer_item["updated_at"] = json!({ "S": "2024-09-09T00:00:00+00:00" });

    let (meta, _http) = metadata_client(vec![
        scan_page(vec![older_item], Some(key_of(&older))),
        scan_page(vec![newer_item], None),
    ]);

    let files = meta.list_trashed(None).await.unwrap();

    assert_eq!(files.len(), 2);
    assert_eq!(files[0].id, newer, "most recently updated comes first");
}

#[tokio::test]
async fn list_trashed_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.list_trashed(None).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_trashed_rejects_a_corrupt_item() {
    let mut item = file_item(&Uuid::new_v4(), &Uuid::new_v4(), "a.txt", None, true);
    item.as_object_mut().unwrap().remove("is_trashed");
    let (meta, _http) = metadata_client(vec![scan_page(vec![item], None)]);

    let err = meta.list_trashed(None).await.expect_err("corrupt");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

// -- Folders --

#[tokio::test]
async fn put_folder_writes_the_parent_when_nested() {
    let (id, owner, parent) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({})), dynamo_ok(json!({}))]);
    let folder = Folder {
        id,
        name: "Finance".into(),
        parent_id: Some(parent),
        owner_id: owner,
        created_at: fixed_time(),
        updated_at: fixed_time(),
    };

    meta.put_folder(&folder).await.unwrap();
    meta.put_folder(&Folder {
        parent_id: None,
        ..folder.clone()
    })
    .await
    .unwrap();

    let requests = sent(&http);
    assert_eq!(requests[0]["TableName"], FOLDERS_TABLE);
    assert_eq!(requests[0]["Item"]["parent_id"]["S"], parent.to_string());
    assert!(requests[1]["Item"].get("parent_id").is_none());
}

#[tokio::test]
async fn put_folder_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .put_folder(&Folder {
            id: Uuid::new_v4(),
            name: "Finance".into(),
            parent_id: None,
            owner_id: Uuid::new_v4(),
            created_at: fixed_time(),
            updated_at: fixed_time(),
        })
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn get_folder_parses_the_stored_item() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, _http) = metadata_client(vec![dynamo_ok(
        json!({ "Item": folder_item(&id, &owner, "Finance", None) }),
    )]);

    let folder = meta.get_folder(&id).await.unwrap();

    assert_eq!(folder.name, "Finance");
    assert_eq!(folder.parent_id, None);
}

#[tokio::test]
async fn get_folder_reports_a_missing_item_as_not_found() {
    let (meta, _http) = metadata_client(vec![dynamo_ok(json!({}))]);

    let err = meta.get_folder(&Uuid::new_v4()).await.expect_err("no item");

    assert!(matches!(err, ServiceError::FolderNotFound(_)), "{err:?}");
}

#[tokio::test]
async fn get_folder_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.get_folder(&Uuid::new_v4()).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn update_folder_sets_only_the_supplied_fields() {
    let (id, owner, parent) = (Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": folder_item(&id, &owner, "Renamed", Some(&parent)) })),
    ]);

    let folder = meta
        .update_folder(&id, Some("Renamed".into()), Some(parent))
        .await
        .unwrap();

    assert_eq!(folder.name, "Renamed");
    let update = &sent(&http)[0];
    assert_eq!(
        update["UpdateExpression"],
        "SET updated_at = :u, #n = :n, parent_id = :p"
    );
}

#[tokio::test]
async fn update_folder_with_no_fields_only_touches_the_timestamp() {
    let (id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![
        dynamo_ok(json!({})),
        dynamo_ok(json!({ "Item": folder_item(&id, &owner, "Finance", None) })),
    ]);

    meta.update_folder(&id, None, None).await.unwrap();

    assert_eq!(sent(&http)[0]["UpdateExpression"], "SET updated_at = :u");
}

#[tokio::test]
async fn update_folder_reports_a_failed_condition_as_not_found() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ConditionalCheckFailedException")]);

    let err = meta
        .update_folder(&Uuid::new_v4(), None, None)
        .await
        .expect_err("gone");

    assert!(matches!(err, ServiceError::FolderNotFound(_)), "{err:?}");
}

#[tokio::test]
async fn update_folder_maps_other_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .update_folder(&Uuid::new_v4(), None, None)
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn delete_folder_targets_the_folders_table() {
    let id = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({}))]);

    meta.delete_folder(&id).await.unwrap();

    assert_eq!(sent(&http)[0]["TableName"], FOLDERS_TABLE);
}

#[tokio::test]
async fn delete_folder_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.delete_folder(&Uuid::new_v4()).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_folders_at_the_root_requires_no_parent_attribute() {
    let owner = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![scan_page(
        vec![folder_item(&Uuid::new_v4(), &owner, "Finance", None)],
        None,
    )]);

    let folders = meta.list_folders(None, Some(owner)).await.unwrap();

    assert_eq!(folders.len(), 1);
    assert_eq!(
        sent(&http)[0]["FilterExpression"],
        "attribute_not_exists(parent_id) AND owner_id = :owner_id"
    );
}

#[tokio::test]
async fn list_folders_below_a_parent_filters_on_it() {
    let (owner, parent) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![
        scan_page(
            vec![folder_item(&Uuid::new_v4(), &owner, "Q1", Some(&parent))],
            Some(key_of(&parent)),
        ),
        scan_page(
            vec![folder_item(&Uuid::new_v4(), &owner, "Q2", Some(&parent))],
            None,
        ),
    ]);

    let folders = meta.list_folders(Some(parent), None).await.unwrap();

    assert_eq!(folders.len(), 2, "pagination is followed");
    assert_eq!(sent(&http)[0]["FilterExpression"], "parent_id = :parent_id");
}

#[tokio::test]
async fn list_folders_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.list_folders(None, None).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_folders_rejects_a_corrupt_item() {
    let mut item = folder_item(&Uuid::new_v4(), &Uuid::new_v4(), "Finance", None);
    item["created_at"] = json!({ "S": "yesterday" });
    let (meta, _http) = metadata_client(vec![scan_page(vec![item], None)]);

    let err = meta.list_folders(None, None).await.expect_err("corrupt");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

// -- Versions --

#[tokio::test]
async fn put_version_writes_to_the_versions_table() {
    let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({}))]);

    meta.put_version(&FileVersion {
        file_id,
        version: 3,
        s3_key: "files/a/b".into(),
        size_bytes: 99,
        created_by: owner,
        created_at: fixed_time(),
    })
    .await
    .unwrap();

    let body = &sent(&http)[0];
    assert_eq!(body["TableName"], VERSIONS_TABLE);
    assert_eq!(body["Item"]["version"]["N"], "3");
    assert_eq!(body["Item"]["size_bytes"]["N"], "99");
}

#[tokio::test]
async fn put_version_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .put_version(&FileVersion {
            file_id: Uuid::new_v4(),
            version: 1,
            s3_key: "k".into(),
            size_bytes: 1,
            created_by: Uuid::new_v4(),
            created_at: fixed_time(),
        })
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_versions_queries_newest_first() {
    let (file_id, owner) = (Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({
        "Items": [version_item(&file_id, &owner, 2), version_item(&file_id, &owner, 1)],
        "Count": 2,
    }))]);

    let versions = meta.list_versions(&file_id).await.unwrap();

    assert_eq!(versions.len(), 2);
    assert_eq!(versions[0].version, 2);
    let query = &sent(&http)[0];
    assert_eq!(query["KeyConditionExpression"], "file_id = :fid");
    assert_eq!(query["ScanIndexForward"], false);
}

#[tokio::test]
async fn list_versions_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.list_versions(&Uuid::new_v4()).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_versions_rejects_a_corrupt_item() {
    let file_id = Uuid::new_v4();
    let mut item = version_item(&file_id, &Uuid::new_v4(), 1);
    item["created_by"] = json!({ "S": "not-a-uuid" });
    let (meta, _http) = metadata_client(vec![dynamo_ok(json!({ "Items": [item], "Count": 1 }))]);

    let err = meta.list_versions(&file_id).await.expect_err("corrupt");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

// -- Shares --

#[tokio::test]
async fn put_share_stores_the_permission_as_a_string() {
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({}))]);

    meta.put_share(&FileShare {
        id: Uuid::new_v4(),
        file_id: Uuid::new_v4(),
        shared_with: Uuid::new_v4(),
        permission: SharePermission::Editor,
        shared_by: Uuid::new_v4(),
        created_at: fixed_time(),
    })
    .await
    .unwrap();

    let body = &sent(&http)[0];
    assert_eq!(body["TableName"], SHARES_TABLE);
    assert_eq!(body["Item"]["permission"]["S"], "editor");
}

#[tokio::test]
async fn put_share_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .put_share(&FileShare {
            id: Uuid::new_v4(),
            file_id: Uuid::new_v4(),
            shared_with: Uuid::new_v4(),
            permission: SharePermission::Viewer,
            shared_by: Uuid::new_v4(),
            created_at: fixed_time(),
        })
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn find_existing_share_returns_the_first_match() {
    let (share, file, user, owner) = (
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
        Uuid::new_v4(),
    );
    let (meta, http) = metadata_client(vec![scan_page(
        vec![share_item(&share, &file, &user, &owner, "viewer")],
        None,
    )]);

    let found = meta.find_existing_share(&file, &user).await.unwrap();

    let found = found.expect("a share exists");
    assert_eq!(found.id, share);
    assert_eq!(found.permission, SharePermission::Viewer);
    assert_eq!(
        sent(&http)[0]["FilterExpression"],
        "file_id = :fid AND shared_with = :uid"
    );
}

#[tokio::test]
async fn find_existing_share_returns_none_when_unshared() {
    let (meta, _http) = metadata_client(vec![scan_page(vec![], None)]);

    let found = meta
        .find_existing_share(&Uuid::new_v4(), &Uuid::new_v4())
        .await
        .unwrap();

    assert!(found.is_none());
}

#[tokio::test]
async fn find_existing_share_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .find_existing_share(&Uuid::new_v4(), &Uuid::new_v4())
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn find_existing_share_rejects_an_unknown_permission() {
    let (meta, _http) = metadata_client(vec![scan_page(
        vec![share_item(
            &Uuid::new_v4(),
            &Uuid::new_v4(),
            &Uuid::new_v4(),
            &Uuid::new_v4(),
            "owner",
        )],
        None,
    )]);

    let err = meta
        .find_existing_share(&Uuid::new_v4(), &Uuid::new_v4())
        .await
        .expect_err("unknown permission");

    match err {
        ServiceError::DynamoError(message) => assert!(message.contains("invalid permission")),
        other => panic!("expected DynamoError, got {other:?}"),
    }
}

#[tokio::test]
async fn list_shares_for_user_collects_every_page() {
    let user = Uuid::new_v4();
    let first = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![
        scan_page(
            vec![share_item(
                &first,
                &Uuid::new_v4(),
                &user,
                &Uuid::new_v4(),
                "viewer",
            )],
            Some(key_of(&first)),
        ),
        scan_page(
            vec![share_item(
                &Uuid::new_v4(),
                &Uuid::new_v4(),
                &user,
                &Uuid::new_v4(),
                "editor",
            )],
            None,
        ),
    ]);

    let shares = meta.list_shares_for_user(&user).await.unwrap();

    assert_eq!(shares.len(), 2);
    assert_eq!(sent(&http)[0]["FilterExpression"], "shared_with = :uid");
}

#[tokio::test]
async fn list_shares_for_user_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .list_shares_for_user(&Uuid::new_v4())
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_shares_by_owner_filters_on_shared_by() {
    let owner = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![scan_page(
        vec![share_item(
            &Uuid::new_v4(),
            &Uuid::new_v4(),
            &Uuid::new_v4(),
            &owner,
            "editor",
        )],
        None,
    )]);

    let shares = meta.list_shares_by_owner(&owner).await.unwrap();

    assert_eq!(shares.len(), 1);
    assert_eq!(shares[0].shared_by, owner);
    assert_eq!(sent(&http)[0]["FilterExpression"], "shared_by = :uid");
}

#[tokio::test]
async fn list_shares_by_owner_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta
        .list_shares_by_owner(&Uuid::new_v4())
        .await
        .expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_shares_returns_every_share_on_a_file() {
    let file = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![scan_page(
        vec![
            share_item(
                &Uuid::new_v4(),
                &file,
                &Uuid::new_v4(),
                &Uuid::new_v4(),
                "viewer",
            ),
            share_item(
                &Uuid::new_v4(),
                &file,
                &Uuid::new_v4(),
                &Uuid::new_v4(),
                "editor",
            ),
        ],
        None,
    )]);

    let shares = meta.list_shares(&file).await.unwrap();

    assert_eq!(shares.len(), 2);
    assert_eq!(sent(&http)[0]["FilterExpression"], "file_id = :fid");
}

#[tokio::test]
async fn list_shares_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.list_shares(&Uuid::new_v4()).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn delete_share_targets_the_shares_table() {
    let share = Uuid::new_v4();
    let (meta, http) = metadata_client(vec![dynamo_ok(json!({}))]);

    meta.delete_share(&share).await.unwrap();

    let body = &sent(&http)[0];
    assert_eq!(body["TableName"], SHARES_TABLE);
    assert_eq!(body["Key"]["id"]["S"], share.to_string());
}

#[tokio::test]
async fn delete_share_maps_dynamo_failures() {
    let (meta, _http) = metadata_client(vec![dynamo_err("ValidationException")]);

    let err = meta.delete_share(&Uuid::new_v4()).await.expect_err("boom");

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

// -- Construction --

#[tokio::test]
async fn new_reads_table_names_from_config() {
    let aws = file_service::config::AwsConfig {
        region: "us-east-1".into(),
        endpoint_url: None,
        s3_bucket: "bucket".into(),
        dynamodb_table: "files".into(),
        dynamodb_folders_table: "folders".into(),
        dynamodb_versions_table: "versions".into(),
        dynamodb_shares_table: "shares".into(),
    };

    let client = file_service::metadata::MetadataClient::new(&aws).await;
    assert_eq!(client.files_table, "files");
    assert_eq!(client.folders_table, "folders");
    assert_eq!(client.versions_table, "versions");
    assert_eq!(client.shares_table, "shares");

    let with_endpoint =
        file_service::metadata::MetadataClient::new(&file_service::config::AwsConfig {
            endpoint_url: Some("http://localstack:4566".into()),
            ..aws
        })
        .await;
    // Clone is used to hand the client to every actix worker.
    assert_eq!(with_endpoint.clone().files_table, "files");
}
