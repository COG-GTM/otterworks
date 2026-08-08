//! `metadata::MetadataClient` against a replayed DynamoDB HTTP boundary.
//!
//! Every response is canned, so these tests assert both the request the SDK
//! emitted (table, key, expressions) and how the response is parsed.

mod support;

use file_service::config::AwsConfig;
use file_service::errors::ServiceError;
use file_service::metadata::MetadataClient;
use file_service::models::SharePermission;
use serde_json::Value;
use support::{
    dynamo_body, dynamo_conditional_check_failed, dynamo_ok, dynamo_server_error, fake_metadata,
    file_item_json, fixed_time, folder_item_json, get_item_response, items_response, sample_file,
    sample_folder, sample_share, sample_version, share_item_json, version_item_json,
};
use uuid::Uuid;

use aws_smithy_runtime::client::http::test_util::StaticReplayClient;

/// The JSON body of the n-th request the SDK actually sent.
fn request_body(http: &StaticReplayClient, n: usize) -> Value {
    let requests = http.actual_requests().collect::<Vec<_>>();
    let bytes = requests[n].body().bytes().expect("in-memory body");
    serde_json::from_slice(bytes).expect("DynamoDB requests are JSON")
}

fn target(http: &StaticReplayClient, n: usize) -> String {
    let requests = http.actual_requests().collect::<Vec<_>>();
    requests[n]
        .headers()
        .get("x-amz-target")
        .expect("DynamoDB sets X-Amz-Target")
        .to_string()
}

fn empty_page() -> (u16, String) {
    dynamo_body(items_response(&[]))
}

// ── Files ──────────────────────────────────────────────────────────────

#[tokio::test]
async fn put_file_writes_every_attribute_and_omits_an_absent_folder() {
    let (meta, http) = fake_metadata(vec![dynamo_ok(), dynamo_ok()]);
    let id = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4();
    let mut file = sample_file(id, owner);

    meta.put_file(&file).await.expect("put without folder");
    file.folder_id = Some(folder);
    meta.put_file(&file).await.expect("put with folder");

    let without = request_body(&http, 0);
    assert_eq!(without["TableName"], "files-t");
    assert_eq!(without["Item"]["id"]["S"], id.to_string());
    assert_eq!(without["Item"]["name"]["S"], "report.pdf");
    assert_eq!(without["Item"]["size_bytes"]["N"], "1024");
    assert_eq!(without["Item"]["is_trashed"]["BOOL"], false);
    assert_eq!(
        without["Item"]["created_at"]["S"],
        fixed_time().to_rfc3339()
    );
    assert!(
        without["Item"].get("folder_id").is_none(),
        "a file at the drive root has no folder_id attribute"
    );

    let with = request_body(&http, 1);
    assert_eq!(with["Item"]["folder_id"]["S"], folder.to_string());
    assert_eq!(target(&http, 1), "DynamoDB_20120810.PutItem");
}

#[tokio::test]
async fn put_file_surfaces_dynamo_failures() {
    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta
        .put_file(&sample_file(Uuid::new_v4(), Uuid::new_v4()))
        .await
        .expect_err("500 must not be swallowed");
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn get_file_parses_the_returned_item() {
    let id = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let file = sample_file(id, owner);
    let (meta, http) = fake_metadata(vec![dynamo_body(get_item_response(&file_item_json(&file)))]);

    let found = meta.get_file(&id).await.expect("item is present");

    assert_eq!(found.id, id);
    assert_eq!(found.owner_id, owner);
    assert_eq!(found.name, "report.pdf");
    assert_eq!(found.size_bytes, 1024);
    assert_eq!(found.created_at, fixed_time());
    assert_eq!(request_body(&http, 0)["Key"]["id"]["S"], id.to_string());
}

#[tokio::test]
async fn get_file_reports_not_found_for_an_empty_response() {
    let id = Uuid::new_v4();
    let (meta, _http) = fake_metadata(vec![dynamo_ok()]);

    let err = meta.get_file(&id).await.expect_err("no Item in response");

    assert!(matches!(err, ServiceError::FileNotFound(_)), "{err:?}");
    assert!(err.to_string().contains(&id.to_string()));
}

#[tokio::test]
async fn get_file_surfaces_dynamo_failures() {
    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta.get_file(&Uuid::new_v4()).await.unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn get_file_rejects_items_with_unparseable_attributes() {
    let file = sample_file(Uuid::new_v4(), Uuid::new_v4());
    let good = file_item_json(&file);

    let broken = [
        ("missing name", good.replace(r#""name""#, r#""nombre""#)),
        (
            "non-uuid id",
            good.replace(&file.id.to_string(), "not-a-uuid"),
        ),
        (
            "non-numeric size",
            good.replace(
                r#""size_bytes":{"N":"1024"}"#,
                r#""size_bytes":{"S":"big"}"#,
            ),
        ),
        (
            "non-numeric version",
            good.replace(r#""version":{"N":"1"}"#, r#""version":{"S":"one"}"#),
        ),
        (
            "non-bool is_trashed",
            good.replace(
                r#""is_trashed":{"BOOL":false}"#,
                r#""is_trashed":{"S":"false"}"#,
            ),
        ),
        (
            "unparseable timestamp",
            good.replace(&file.created_at.to_rfc3339(), "yesterday"),
        ),
        (
            "non-uuid folder_id",
            good.replace(
                r#""updated_at""#,
                r#""folder_id":{"S":"nope"},"updated_at""#,
            ),
        ),
    ];

    for (label, item) in broken {
        let (meta, _http) = fake_metadata(vec![dynamo_body(get_item_response(&item))]);
        let err = meta.get_file(&file.id).await.expect_err(label);
        assert!(matches!(err, ServiceError::DynamoError(_)), "{label}");
    }
}

#[tokio::test]
async fn delete_file_deletes_by_id() {
    let id = Uuid::new_v4();
    let (meta, http) = fake_metadata(vec![dynamo_ok()]);

    meta.delete_file(&id).await.expect("delete");

    assert_eq!(target(&http, 0), "DynamoDB_20120810.DeleteItem");
    assert_eq!(request_body(&http, 0)["Key"]["id"]["S"], id.to_string());
    assert_eq!(request_body(&http, 0)["TableName"], "files-t");
}

#[tokio::test]
async fn delete_file_surfaces_dynamo_failures() {
    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta.delete_file(&Uuid::new_v4()).await.unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn trash_file_flips_the_flag_then_re_reads_the_item() {
    let id = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let mut file = sample_file(id, owner);
    file.is_trashed = true;
    let (meta, http) = fake_metadata(vec![
        dynamo_ok(),
        dynamo_body(get_item_response(&file_item_json(&file))),
    ]);

    let updated = meta.trash_file(&id).await.expect("trash");

    assert!(updated.is_trashed);
    let update = request_body(&http, 0);
    assert_eq!(
        update["UpdateExpression"],
        "SET is_trashed = :t, updated_at = :u"
    );
    assert_eq!(update["ConditionExpression"], "attribute_exists(id)");
    assert_eq!(update["ExpressionAttributeValues"][":t"]["BOOL"], true);
    assert_eq!(target(&http, 1), "DynamoDB_20120810.GetItem");
}

#[tokio::test]
async fn restore_file_clears_the_flag_then_re_reads_the_item() {
    let id = Uuid::new_v4();
    let file = sample_file(id, Uuid::new_v4());
    let (meta, http) = fake_metadata(vec![
        dynamo_ok(),
        dynamo_body(get_item_response(&file_item_json(&file))),
    ]);

    let updated = meta.restore_file(&id).await.expect("restore");

    assert!(!updated.is_trashed);
    assert_eq!(
        request_body(&http, 0)["ExpressionAttributeValues"][":t"]["BOOL"],
        false
    );
}

#[tokio::test]
async fn rename_file_sets_the_name_through_an_attribute_alias() {
    let id = Uuid::new_v4();
    let mut file = sample_file(id, Uuid::new_v4());
    file.name = "renamed.pdf".into();
    let (meta, http) = fake_metadata(vec![
        dynamo_ok(),
        dynamo_body(get_item_response(&file_item_json(&file))),
    ]);

    let updated = meta.rename_file(&id, "renamed.pdf").await.expect("rename");

    assert_eq!(updated.name, "renamed.pdf");
    let update = request_body(&http, 0);
    assert_eq!(update["UpdateExpression"], "SET #n = :n, updated_at = :u");
    assert_eq!(update["ExpressionAttributeNames"]["#n"], "name");
    assert_eq!(
        update["ExpressionAttributeValues"][":n"]["S"],
        "renamed.pdf"
    );
}

#[tokio::test]
async fn move_file_sets_or_removes_folder_id() {
    let id = Uuid::new_v4();
    let folder = Uuid::new_v4();
    let mut in_folder = sample_file(id, Uuid::new_v4());
    in_folder.folder_id = Some(folder);
    let at_root = sample_file(id, in_folder.owner_id);

    let (meta, http) = fake_metadata(vec![
        dynamo_ok(),
        dynamo_body(get_item_response(&file_item_json(&in_folder))),
        dynamo_ok(),
        dynamo_body(get_item_response(&file_item_json(&at_root))),
    ]);

    let moved = meta
        .move_file(&id, Some(folder))
        .await
        .expect("into folder");
    assert_eq!(moved.folder_id, Some(folder));
    let into = request_body(&http, 0);
    assert_eq!(
        into["UpdateExpression"],
        "SET folder_id = :f, updated_at = :u"
    );
    assert_eq!(
        into["ExpressionAttributeValues"][":f"]["S"],
        folder.to_string()
    );

    let moved = meta.move_file(&id, None).await.expect("to the root");
    assert_eq!(moved.folder_id, None);
    let out = request_body(&http, 2);
    assert_eq!(
        out["UpdateExpression"],
        "SET updated_at = :u REMOVE folder_id"
    );
    assert!(out["ExpressionAttributeValues"].get(":f").is_none());
}

#[tokio::test]
async fn conditional_check_failures_become_file_not_found() {
    let id = Uuid::new_v4();

    for label in ["trash", "restore", "rename", "move"] {
        let (meta, _http) = fake_metadata(vec![dynamo_conditional_check_failed()]);
        let err = match label {
            "trash" => meta.trash_file(&id).await.unwrap_err(),
            "restore" => meta.restore_file(&id).await.unwrap_err(),
            "rename" => meta.rename_file(&id, "x").await.unwrap_err(),
            _ => meta.move_file(&id, None).await.unwrap_err(),
        };
        assert!(
            matches!(err, ServiceError::FileNotFound(_)),
            "{label}: {err:?}"
        );
    }
}

#[tokio::test]
async fn other_update_failures_stay_dynamo_errors() {
    let id = Uuid::new_v4();

    for label in ["trash", "restore", "rename", "move"] {
        let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
        let err = match label {
            "trash" => meta.trash_file(&id).await.unwrap_err(),
            "restore" => meta.restore_file(&id).await.unwrap_err(),
            "rename" => meta.rename_file(&id, "x").await.unwrap_err(),
            _ => meta.move_file(&id, Some(Uuid::new_v4())).await.unwrap_err(),
        };
        assert!(
            matches!(err, ServiceError::DynamoError(_)),
            "{label}: {err:?}"
        );
    }
}

#[tokio::test]
async fn list_files_filters_on_folder_owner_and_trash_flag() {
    let owner = Uuid::new_v4();
    let folder = Uuid::new_v4();
    let file = sample_file(Uuid::new_v4(), owner);
    let (meta, http) = fake_metadata(vec![dynamo_body(items_response(&[file_item_json(&file)]))]);

    let files = meta
        .list_files(Some(folder), Some(owner), false)
        .await
        .expect("scan");

    assert_eq!(files.len(), 1);
    assert_eq!(files[0].owner_id, owner);
    let scan = request_body(&http, 0);
    assert_eq!(scan["TableName"], "files-t");
    assert_eq!(
        scan["FilterExpression"],
        "folder_id = :folder_id AND owner_id = :owner_id AND is_trashed = :trashed"
    );
    assert_eq!(
        scan["ExpressionAttributeValues"][":folder_id"]["S"],
        folder.to_string()
    );
    assert_eq!(scan["ExpressionAttributeValues"][":trashed"]["BOOL"], false);
}

#[tokio::test]
async fn list_files_without_filters_scans_the_whole_table() {
    let (meta, http) = fake_metadata(vec![empty_page()]);

    let files = meta.list_files(None, None, true).await.expect("scan");

    assert!(files.is_empty());
    let scan = request_body(&http, 0);
    assert!(
        scan.get("FilterExpression").is_none(),
        "include_trashed with no owner/folder means an unfiltered scan"
    );
}

#[tokio::test]
async fn list_files_follows_the_scan_paginator() {
    let owner = Uuid::new_v4();
    let first = sample_file(Uuid::new_v4(), owner);
    let second = sample_file(Uuid::new_v4(), owner);
    let page_one = format!(
        r#"{{"Items":[{}],"Count":1,"LastEvaluatedKey":{{"id":{{"S":"{}"}}}}}}"#,
        file_item_json(&first),
        first.id
    );
    let (meta, http) = fake_metadata(vec![
        dynamo_body(page_one),
        dynamo_body(items_response(&[file_item_json(&second)])),
    ]);

    let files = meta.list_files(None, None, true).await.expect("scan");

    assert_eq!(files.len(), 2, "both pages are drained");
    assert_eq!(files[0].id, first.id);
    assert_eq!(files[1].id, second.id);
    assert_eq!(
        request_body(&http, 1)["ExclusiveStartKey"]["id"]["S"],
        first.id.to_string(),
        "the second scan resumes from LastEvaluatedKey"
    );
}

#[tokio::test]
async fn list_files_surfaces_dynamo_failures() {
    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta.list_files(None, None, false).await.unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_trashed_filters_on_the_trash_flag_and_sorts_newest_first() {
    let owner = Uuid::new_v4();
    let mut older = sample_file(Uuid::new_v4(), owner);
    older.updated_at = fixed_time() - chrono::Duration::hours(2);
    let newer = sample_file(Uuid::new_v4(), owner);
    let (meta, http) = fake_metadata(vec![dynamo_body(items_response(&[
        file_item_json(&older),
        file_item_json(&newer),
    ]))]);

    let files = meta.list_trashed(Some(owner)).await.expect("scan");

    assert_eq!(
        files.iter().map(|f| f.id).collect::<Vec<_>>(),
        vec![newer.id, older.id],
        "trash is ordered by updated_at descending"
    );
    let scan = request_body(&http, 0);
    assert_eq!(
        scan["FilterExpression"],
        "is_trashed = :trashed AND owner_id = :owner_id"
    );
    assert_eq!(scan["ExpressionAttributeValues"][":trashed"]["BOOL"], true);
}

#[tokio::test]
async fn list_trashed_without_an_owner_filters_only_on_the_flag() {
    let (meta, http) = fake_metadata(vec![empty_page()]);

    assert!(meta.list_trashed(None).await.expect("scan").is_empty());

    assert_eq!(
        request_body(&http, 0)["FilterExpression"],
        "is_trashed = :trashed"
    );
}

#[tokio::test]
async fn list_trashed_surfaces_dynamo_failures() {
    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta.list_trashed(None).await.unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

// ── Folders ────────────────────────────────────────────────────────────

#[tokio::test]
async fn put_folder_writes_parent_id_only_when_nested() {
    let owner = Uuid::new_v4();
    let parent = Uuid::new_v4();
    let mut folder = sample_folder(Uuid::new_v4(), owner);
    let (meta, http) = fake_metadata(vec![dynamo_ok(), dynamo_ok()]);

    meta.put_folder(&folder).await.expect("root folder");
    folder.parent_id = Some(parent);
    meta.put_folder(&folder).await.expect("nested folder");

    let root = request_body(&http, 0);
    assert_eq!(root["TableName"], "folders-t");
    assert_eq!(root["Item"]["name"]["S"], "Finance");
    assert!(root["Item"].get("parent_id").is_none());
    assert_eq!(
        request_body(&http, 1)["Item"]["parent_id"]["S"],
        parent.to_string()
    );
}

#[tokio::test]
async fn put_folder_surfaces_dynamo_failures() {
    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta
        .put_folder(&sample_folder(Uuid::new_v4(), Uuid::new_v4()))
        .await
        .unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn get_folder_parses_the_item_or_reports_not_found() {
    let id = Uuid::new_v4();
    let folder = sample_folder(id, Uuid::new_v4());
    let (meta, _http) = fake_metadata(vec![dynamo_body(get_item_response(&folder_item_json(
        &folder,
    )))]);
    let found = meta.get_folder(&id).await.expect("present");
    assert_eq!(found.name, "Finance");
    assert_eq!(found.parent_id, None);

    let (meta, _http) = fake_metadata(vec![dynamo_ok()]);
    let err = meta.get_folder(&id).await.unwrap_err();
    assert!(matches!(err, ServiceError::FolderNotFound(_)), "{err:?}");

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta.get_folder(&id).await.unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn get_folder_rejects_an_unparseable_item() {
    let folder = sample_folder(Uuid::new_v4(), Uuid::new_v4());
    let item = folder_item_json(&folder).replace(r#""name""#, r#""nombre""#);
    let (meta, _http) = fake_metadata(vec![dynamo_body(get_item_response(&item))]);

    let err = meta.get_folder(&folder.id).await.unwrap_err();

    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn update_folder_builds_the_expression_from_the_supplied_fields() {
    let id = Uuid::new_v4();
    let parent = Uuid::new_v4();
    let folder = sample_folder(id, Uuid::new_v4());
    let item = folder_item_json(&folder);
    let (meta, http) = fake_metadata(vec![
        dynamo_ok(),
        dynamo_body(get_item_response(&item)),
        dynamo_ok(),
        dynamo_body(get_item_response(&item)),
        dynamo_ok(),
        dynamo_body(get_item_response(&item)),
    ]);

    meta.update_folder(&id, Some("Legal".into()), Some(parent))
        .await
        .expect("rename and reparent");
    let both = request_body(&http, 0);
    assert_eq!(
        both["UpdateExpression"],
        "SET updated_at = :u, #n = :n, parent_id = :p"
    );
    assert_eq!(both["ExpressionAttributeValues"][":n"]["S"], "Legal");
    assert_eq!(
        both["ExpressionAttributeValues"][":p"]["S"],
        parent.to_string()
    );

    meta.update_folder(&id, Some("Legal".into()), None)
        .await
        .expect("rename only");
    assert_eq!(
        request_body(&http, 2)["UpdateExpression"],
        "SET updated_at = :u, #n = :n"
    );

    meta.update_folder(&id, None, None)
        .await
        .expect("touch only");
    assert_eq!(
        request_body(&http, 4)["UpdateExpression"],
        "SET updated_at = :u"
    );
}

#[tokio::test]
async fn update_folder_maps_a_conditional_check_failure_to_folder_not_found() {
    let (meta, _http) = fake_metadata(vec![dynamo_conditional_check_failed()]);
    let err = meta
        .update_folder(&Uuid::new_v4(), None, None)
        .await
        .unwrap_err();
    assert!(matches!(err, ServiceError::FolderNotFound(_)), "{err:?}");

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta
        .update_folder(&Uuid::new_v4(), None, None)
        .await
        .unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn delete_folder_deletes_by_id() {
    let id = Uuid::new_v4();
    let (meta, http) = fake_metadata(vec![dynamo_ok()]);

    meta.delete_folder(&id).await.expect("delete");

    assert_eq!(request_body(&http, 0)["TableName"], "folders-t");
    assert_eq!(request_body(&http, 0)["Key"]["id"]["S"], id.to_string());

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta.delete_folder(&id).await.unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_folders_scopes_to_the_parent_or_the_drive_root() {
    let owner = Uuid::new_v4();
    let parent = Uuid::new_v4();
    let folder = sample_folder(Uuid::new_v4(), owner);
    let (meta, http) = fake_metadata(vec![
        dynamo_body(items_response(&[folder_item_json(&folder)])),
        empty_page(),
    ]);

    let nested = meta
        .list_folders(Some(parent), Some(owner))
        .await
        .expect("scan");
    assert_eq!(nested.len(), 1);
    assert_eq!(
        request_body(&http, 0)["FilterExpression"],
        "parent_id = :parent_id AND owner_id = :owner_id"
    );

    meta.list_folders(None, None).await.expect("scan");
    assert_eq!(
        request_body(&http, 1)["FilterExpression"],
        "attribute_not_exists(parent_id)",
        "no parent means only top-level folders"
    );
}

#[tokio::test]
async fn list_folders_surfaces_dynamo_failures() {
    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta.list_folders(None, None).await.unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

// ── Versions ───────────────────────────────────────────────────────────

#[tokio::test]
async fn put_version_writes_the_version_row() {
    let file_id = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let (meta, http) = fake_metadata(vec![dynamo_ok()]);

    meta.put_version(&sample_version(file_id, owner))
        .await
        .expect("put");

    let body = request_body(&http, 0);
    assert_eq!(body["TableName"], "versions-t");
    assert_eq!(body["Item"]["file_id"]["S"], file_id.to_string());
    assert_eq!(body["Item"]["version"]["N"], "2");
    assert_eq!(body["Item"]["size_bytes"]["N"], "2048");

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta
        .put_version(&sample_version(file_id, owner))
        .await
        .unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");
}

#[tokio::test]
async fn list_versions_queries_newest_first() {
    let file_id = Uuid::new_v4();
    let owner = Uuid::new_v4();
    let version = sample_version(file_id, owner);
    let (meta, http) = fake_metadata(vec![dynamo_body(items_response(&[version_item_json(
        &version,
    )]))]);

    let versions = meta.list_versions(&file_id).await.expect("query");

    assert_eq!(versions.len(), 1);
    assert_eq!(versions[0].version, 2);
    let query = request_body(&http, 0);
    assert_eq!(query["TableName"], "versions-t");
    assert_eq!(query["KeyConditionExpression"], "file_id = :fid");
    assert_eq!(
        query["ScanIndexForward"], false,
        "versions come back newest-first"
    );
}

#[tokio::test]
async fn list_versions_surfaces_dynamo_and_parse_failures() {
    let file_id = Uuid::new_v4();
    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    let err = meta.list_versions(&file_id).await.unwrap_err();
    assert!(matches!(err, ServiceError::DynamoError(_)), "{err:?}");

    let broken = version_item_json(&sample_version(file_id, Uuid::new_v4()))
        .replace(r#""s3_key""#, r#""k""#);
    let (meta, _http) = fake_metadata(vec![dynamo_body(items_response(&[broken]))]);
    let err = meta.list_versions(&file_id).await.unwrap_err();
    assert!(err.to_string().contains("missing field: s3_key"), "{err}");
}

// ── Shares ─────────────────────────────────────────────────────────────

#[tokio::test]
async fn put_share_stores_the_permission_as_a_lowercase_string() {
    let share = sample_share(Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let (meta, http) = fake_metadata(vec![dynamo_ok()]);

    meta.put_share(&share).await.expect("put");

    let body = request_body(&http, 0);
    assert_eq!(body["TableName"], "shares-t");
    assert_eq!(body["Item"]["permission"]["S"], "viewer");
    assert_eq!(
        body["Item"]["shared_with"]["S"],
        share.shared_with.to_string()
    );

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    assert!(matches!(
        meta.put_share(&share).await.unwrap_err(),
        ServiceError::DynamoError(_)
    ));
}

#[tokio::test]
async fn find_existing_share_returns_the_first_match_or_none() {
    let file_id = Uuid::new_v4();
    let user = Uuid::new_v4();
    let share = sample_share(Uuid::new_v4(), file_id, user);
    let (meta, http) = fake_metadata(vec![dynamo_body(items_response(&[share_item_json(
        &share,
    )]))]);

    let found = meta
        .find_existing_share(&file_id, &user)
        .await
        .expect("scan")
        .expect("a share exists");
    assert_eq!(found.id, share.id);
    assert_eq!(found.permission, SharePermission::Viewer);
    assert_eq!(
        request_body(&http, 0)["FilterExpression"],
        "file_id = :fid AND shared_with = :uid"
    );

    let (meta, _http) = fake_metadata(vec![empty_page()]);
    assert!(meta
        .find_existing_share(&file_id, &user)
        .await
        .expect("scan")
        .is_none());

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    assert!(matches!(
        meta.find_existing_share(&file_id, &user).await.unwrap_err(),
        ServiceError::DynamoError(_)
    ));
}

#[tokio::test]
async fn share_items_with_an_unknown_permission_are_rejected() {
    let share = sample_share(Uuid::new_v4(), Uuid::new_v4(), Uuid::new_v4());
    let item = share_item_json(&share).replace(r#""S":"viewer""#, r#""S":"admin""#);
    let (meta, _http) = fake_metadata(vec![dynamo_body(items_response(&[item]))]);

    let err = meta
        .find_existing_share(&share.file_id, &share.shared_with)
        .await
        .unwrap_err();

    assert!(
        err.to_string().contains("invalid permission: admin"),
        "{err}"
    );
}

#[tokio::test]
async fn list_shares_for_user_drains_every_page() {
    let user = Uuid::new_v4();
    let first = sample_share(Uuid::new_v4(), Uuid::new_v4(), user);
    let second = sample_share(Uuid::new_v4(), Uuid::new_v4(), user);
    let page_one = format!(
        r#"{{"Items":[{}],"Count":1,"LastEvaluatedKey":{{"id":{{"S":"{}"}}}}}}"#,
        share_item_json(&first),
        first.id
    );
    let (meta, http) = fake_metadata(vec![
        dynamo_body(page_one),
        dynamo_body(items_response(&[share_item_json(&second)])),
    ]);

    let shares = meta.list_shares_for_user(&user).await.expect("scan");

    assert_eq!(shares.len(), 2);
    assert_eq!(
        request_body(&http, 0)["FilterExpression"],
        "shared_with = :uid"
    );

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    assert!(matches!(
        meta.list_shares_for_user(&user).await.unwrap_err(),
        ServiceError::DynamoError(_)
    ));
}

#[tokio::test]
async fn list_shares_by_owner_filters_on_shared_by() {
    let owner = Uuid::new_v4();
    let share = sample_share(Uuid::new_v4(), Uuid::new_v4(), owner);
    let (meta, http) = fake_metadata(vec![dynamo_body(items_response(&[share_item_json(
        &share,
    )]))]);

    let shares = meta.list_shares_by_owner(&owner).await.expect("scan");

    assert_eq!(shares.len(), 1);
    assert_eq!(
        request_body(&http, 0)["FilterExpression"],
        "shared_by = :uid"
    );

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    assert!(matches!(
        meta.list_shares_by_owner(&owner).await.unwrap_err(),
        ServiceError::DynamoError(_)
    ));
}

#[tokio::test]
async fn list_shares_filters_on_file_id() {
    let file_id = Uuid::new_v4();
    let share = sample_share(Uuid::new_v4(), file_id, Uuid::new_v4());
    let (meta, http) = fake_metadata(vec![dynamo_body(items_response(&[share_item_json(
        &share,
    )]))]);

    let shares = meta.list_shares(&file_id).await.expect("scan");

    assert_eq!(shares.len(), 1);
    assert_eq!(shares[0].file_id, file_id);
    assert_eq!(request_body(&http, 0)["FilterExpression"], "file_id = :fid");

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    assert!(matches!(
        meta.list_shares(&file_id).await.unwrap_err(),
        ServiceError::DynamoError(_)
    ));
}

#[tokio::test]
async fn delete_share_deletes_by_share_id() {
    let id = Uuid::new_v4();
    let (meta, http) = fake_metadata(vec![dynamo_ok()]);

    meta.delete_share(&id).await.expect("delete");

    assert_eq!(request_body(&http, 0)["TableName"], "shares-t");
    assert_eq!(request_body(&http, 0)["Key"]["id"]["S"], id.to_string());

    let (meta, _http) = fake_metadata(vec![dynamo_server_error()]);
    assert!(matches!(
        meta.delete_share(&id).await.unwrap_err(),
        ServiceError::DynamoError(_)
    ));
}

// ── Construction ───────────────────────────────────────────────────────

#[tokio::test]
async fn new_maps_the_four_table_names_and_honours_a_custom_endpoint() {
    let aws = AwsConfig {
        region: "us-west-1".into(),
        endpoint_url: Some("http://localhost:4566".into()),
        s3_bucket: "b".into(),
        dynamodb_table: "files".into(),
        dynamodb_folders_table: "folders".into(),
        dynamodb_versions_table: "versions".into(),
        dynamodb_shares_table: "shares".into(),
    };

    let client = MetadataClient::new(&aws).await;
    assert_eq!(client.files_table, "files");
    assert_eq!(client.folders_table, "folders");
    assert_eq!(client.versions_table, "versions");
    assert_eq!(client.shares_table, "shares");

    let mut no_endpoint = aws.clone();
    no_endpoint.endpoint_url = None;
    let client = MetadataClient::new(&no_endpoint).await;
    assert_eq!(
        client.client.config().region().map(|r| r.as_ref()),
        Some("us-west-1")
    );

    let cloned = client.clone();
    assert_eq!(cloned.files_table, client.files_table);
}
