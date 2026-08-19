use chrono::Utc;
use uuid::Uuid;

use crate::metadata::MetadataClient;
use crate::models::FileMetadata;
use crate::storage::S3Client;

/// Namespace for deriving stable per-owner demo document ids, so seeding is
/// idempotent even if it runs concurrently for the same owner.
const SEED_NAMESPACE: Uuid = Uuid::from_bytes([
    0x6f, 0x74, 0x74, 0x65, 0x72, 0x77, 0x6f, 0x72, 0x6b, 0x73, 0x2d, 0x73, 0x65, 0x65, 0x64, 0x73,
]);

const DEMO_DOCS: &[(&str, &str, &str)] = &[
    (
        "Q3 Financial Report.txt",
        "text/plain",
        "OtterWorks Inc.\nQ3 Financial Report\n\nRevenue: $4.2M (+18% QoQ)\nGross margin: 62%\nNet burn: $310K/month\n\nHighlights:\n- Enterprise tier launched in July\n- 14 new logos closed\n- Churn down to 1.1%\n",
    ),
    (
        "Annual Planning 2027.txt",
        "text/plain",
        "Annual Planning 2027 — Draft\n\nThemes:\n1. Platform reliability (99.95% SLO)\n2. International expansion (EU + APAC)\n3. Self-serve onboarding\n\nHeadcount plan: +22 engineering, +8 GTM\n",
    ),
    (
        "Team Offsite Agenda.txt",
        "text/plain",
        "Team Offsite — Agenda\n\nDay 1: Roadmap review, customer panel\nDay 2: Architecture deep-dives, hack afternoon\nDay 3: OKR workshop, retro, dinner\n\nVenue: Lakeside Lodge, cabin 12\n",
    ),
];

/// Seed a few demo documents for an owner who has no files yet. Used on demo
/// deployments where uploads are made to fail: sharing (and its notification
/// path) can still be exercised on these pre-seeded documents. Idempotent per
/// owner via deterministic ids. Never fails the caller.
pub async fn maybe_seed_demo_docs(meta: &MetadataClient, s3: &S3Client, owner_id: Uuid) {
    let existing = match meta.list_files(None, Some(owner_id), true).await {
        Ok(files) => files,
        Err(e) => {
            tracing::warn!(error = %e, "Demo-doc seeding: listing files failed; skipping");
            return;
        }
    };
    if !existing.is_empty() {
        return;
    }

    for (name, mime_type, content) in DEMO_DOCS {
        let file_id = Uuid::new_v5(&SEED_NAMESPACE, format!("{owner_id}/{name}").as_bytes());
        let s3_key = format!("files/{owner_id}/{file_id}");
        let bytes = bytes::Bytes::from_static(content.as_bytes());

        if let Err(e) = s3.upload_object(&s3_key, bytes, mime_type).await {
            tracing::warn!(error = %e, name = %name, "Demo-doc seeding: S3 upload failed; skipping doc");
            continue;
        }

        let now = Utc::now();
        let file = FileMetadata {
            id: file_id,
            name: (*name).to_string(),
            mime_type: (*mime_type).to_string(),
            size_bytes: content.len() as u64,
            s3_key,
            folder_id: None,
            owner_id,
            version: 1,
            is_trashed: false,
            created_at: now,
            updated_at: now,
        };
        if let Err(e) = meta.put_file(&file).await {
            tracing::warn!(error = %e, name = %name, "Demo-doc seeding: metadata write failed");
        } else {
            tracing::info!(owner_id = %owner_id, name = %name, "Seeded demo document");
        }
    }
}
