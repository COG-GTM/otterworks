output "file_bucket_name" {
  description = "Name of the S3 bucket for file storage"
  value       = aws_s3_bucket.files.id
}

output "file_bucket_arn" {
  description = "ARN of the S3 bucket for file storage"
  value       = aws_s3_bucket.files.arn
}

output "data_lake_bucket_name" {
  description = "Name of the S3 bucket for analytics data lake"
  value       = aws_s3_bucket.data_lake.id
}

output "data_lake_bucket_arn" {
  description = "ARN of the S3 bucket for analytics data lake"
  value       = aws_s3_bucket.data_lake.arn
}

output "audit_archive_bucket_name" {
  description = "Name of the S3 bucket for audit archive"
  value       = aws_s3_bucket.audit_archive.id
}

output "audit_archive_bucket_arn" {
  description = "ARN of the S3 bucket for audit archive"
  value       = aws_s3_bucket.audit_archive.arn
}

output "access_logs_bucket_name" {
  description = "Name of the S3 bucket holding server access logs"
  value       = aws_s3_bucket.access_logs.id
}
