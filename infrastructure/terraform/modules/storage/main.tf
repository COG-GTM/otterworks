# ------------------------------------------------------------------------------
# OtterWorks Storage Module
# S3 buckets for file storage, data lake, and audit archive
# ------------------------------------------------------------------------------

locals {
  common_tags = {
    Module  = "storage"
    Project = var.project
  }
}

# --- File Storage Bucket ---

resource "aws_s3_bucket" "files" {
  #checkov:skip=CKV_AWS_144:Cross-region replication is out of scope for single-region demo environments.
  #checkov:skip=CKV2_AWS_62:No consumer for S3 event notifications; services publish their own events via SNS.
  #checkov:skip=CKV_AWS_18:Server access logging needs a dedicated log bucket; CloudTrail data events are the audit source.
  bucket = "${var.project}-files-${var.environment}"

  tags = merge(local.common_tags, {
    Service = "file-service"
  })
}

resource "aws_s3_bucket_public_access_block" "files" {
  bucket                  = aws_s3_bucket.files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "files" {
  bucket = aws_s3_bucket.files.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "files" {
  bucket = aws_s3_bucket.files.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "files" {
  bucket = aws_s3_bucket.files.id

  rule {
    id     = "archive-old-versions"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }

    noncurrent_version_transition {
      noncurrent_days = 30
      storage_class   = "GLACIER"
    }
    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

# --- Data Lake Bucket ---

resource "aws_s3_bucket" "data_lake" {
  #checkov:skip=CKV_AWS_144:Cross-region replication is out of scope for single-region demo environments.
  #checkov:skip=CKV2_AWS_62:No consumer for S3 event notifications; services publish their own events via SNS.
  #checkov:skip=CKV_AWS_18:Server access logging needs a dedicated log bucket; CloudTrail data events are the audit source.
  #checkov:skip=CKV_AWS_21:Analytics output is regenerated from source events; versioning would only accumulate cost.
  #checkov:skip=CKV2_AWS_61:Retention for analytics output has not been decided; add expiry rules once it is.
  bucket = "${var.project}-data-lake-${var.environment}"

  tags = merge(local.common_tags, {
    Service = "analytics-service"
  })
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket                  = aws_s3_bucket.data_lake.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

# --- Audit Archive Bucket ---

resource "aws_s3_bucket" "audit_archive" {
  #checkov:skip=CKV_AWS_144:Cross-region replication is out of scope for single-region demo environments.
  #checkov:skip=CKV2_AWS_62:No consumer for S3 event notifications; services publish their own events via SNS.
  #checkov:skip=CKV_AWS_18:Server access logging needs a dedicated log bucket; CloudTrail data events are the audit source.
  #checkov:skip=CKV2_AWS_61:Audit archive retention is a compliance decision; objects must not expire until it is made.
  bucket = "${var.project}-audit-archive-${var.environment}"

  tags = merge(local.common_tags, {
    Service = "audit-service"
  })
}

resource "aws_s3_bucket_public_access_block" "audit_archive" {
  bucket                  = aws_s3_bucket.audit_archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "audit_archive" {
  bucket = aws_s3_bucket.audit_archive.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit_archive" {
  bucket = aws_s3_bucket.audit_archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}
