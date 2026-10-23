#!/bin/bash
set -euo pipefail

echo "Initializing LocalStack resources..."

# Idempotent so re-runs on already-provisioned state (e.g. when DynamoDB tables
# are restored from a persisted snapshot with PERSISTENCE=1) do not abort under
# `set -e`. This ready.d hook runs on every container start.
bucket_exists() { awslocal s3api head-bucket --bucket "$1" >/dev/null 2>&1; }
table_exists()  { awslocal dynamodb describe-table --table-name "$1" >/dev/null 2>&1; }
make_bucket()   { bucket_exists "$1" || awslocal s3 mb "s3://$1"; }

# S3 Buckets
make_bucket otterworks-files
make_bucket otterworks-data-lake
make_bucket otterworks-audit-archive

# SQS Queue (create-queue is idempotent for an existing queue with the same name)
awslocal sqs create-queue --queue-name otterworks-notifications
awslocal sqs create-queue --queue-name otterworks-audit-events-queue
awslocal sqs create-queue --queue-name otterworks-search-events

# SNS Topic (create-topic returns the existing ARN if it already exists)
awslocal sns create-topic --name otterworks-events
NOTIFICATION_QUEUE_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/otterworks-notifications \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)
awslocal sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:000000000000:otterworks-events \
  --protocol sqs \
  --notification-endpoint "$NOTIFICATION_QUEUE_ARN"
AUDIT_QUEUE_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/otterworks-audit-events-queue \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)
awslocal sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:000000000000:otterworks-events \
  --protocol sqs \
  --notification-endpoint "$AUDIT_QUEUE_ARN"
SEARCH_QUEUE_ARN=$(awslocal sqs get-queue-attributes \
  --queue-url http://localhost:4566/000000000000/otterworks-search-events \
  --attribute-names QueueArn \
  --query 'Attributes.QueueArn' \
  --output text)
awslocal sns subscribe \
  --topic-arn arn:aws:sns:us-east-1:000000000000:otterworks-events \
  --protocol sqs \
  --notification-endpoint "$SEARCH_QUEUE_ARN"

# DynamoDB Tables
table_exists otterworks-file-metadata || awslocal dynamodb create-table \
  --table-name otterworks-file-metadata \
  --attribute-definitions AttributeName=id,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

# GSIs mirror infrastructure/terraform/modules/database/main.tf; the audit
# service reads exclusively through them (no table scans).
table_exists otterworks-audit-events || awslocal dynamodb create-table \
  --table-name otterworks-audit-events \
  --attribute-definitions \
    AttributeName=id,AttributeType=S \
    AttributeName=user_id,AttributeType=S \
    AttributeName=date_partition,AttributeType=S \
    AttributeName=timestamp,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --global-secondary-indexes \
    '[{"IndexName":"user-index","KeySchema":[{"AttributeName":"user_id","KeyType":"HASH"},{"AttributeName":"timestamp","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}},{"IndexName":"timestamp-index","KeySchema":[{"AttributeName":"date_partition","KeyType":"HASH"},{"AttributeName":"timestamp","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}}]' \
  --billing-mode PAY_PER_REQUEST

# Tables restored from a pre-GSI snapshot keep their old schema; add any missing
# audit index in place. Events written before the upgrade lack the index keys
# and stay invisible to index queries until rewritten.
ensure_gsi() {
  local table="$1" index="$2" hash="$3" range="$4"
  if awslocal dynamodb describe-table --table-name "$table" \
      --query "Table.GlobalSecondaryIndexes[?IndexName=='${index}'].IndexName" --output text | grep -qx "$index"; then
    return 0
  fi
  echo "Adding missing GSI ${index} to ${table}"
  awslocal dynamodb update-table --table-name "$table" \
    --attribute-definitions AttributeName="$hash",AttributeType=S AttributeName="$range",AttributeType=S \
    --global-secondary-index-updates \
      "[{\"Create\":{\"IndexName\":\"${index}\",\"KeySchema\":[{\"AttributeName\":\"${hash}\",\"KeyType\":\"HASH\"},{\"AttributeName\":\"${range}\",\"KeyType\":\"RANGE\"}],\"Projection\":{\"ProjectionType\":\"ALL\"}}}]" >/dev/null
  for _ in $(seq 1 30); do
    status=$(awslocal dynamodb describe-table --table-name "$table" \
      --query "Table.GlobalSecondaryIndexes[?IndexName=='${index}'].IndexStatus" --output text)
    [ "$status" = "ACTIVE" ] && return 0
    sleep 1
  done
  echo "GSI ${index} on ${table} not ACTIVE after 30s (status: ${status:-unknown})" >&2
}
ensure_gsi otterworks-audit-events user-index user_id timestamp
ensure_gsi otterworks-audit-events timestamp-index date_partition timestamp

table_exists otterworks-notifications || awslocal dynamodb create-table \
  --table-name otterworks-notifications \
  --attribute-definitions \
    AttributeName=id,AttributeType=S \
    AttributeName=userId,AttributeType=S \
    AttributeName=createdAt,AttributeType=S \
  --key-schema \
    AttributeName=id,KeyType=HASH \
  --global-secondary-indexes \
    '[{"IndexName":"userId-createdAt-index","KeySchema":[{"AttributeName":"userId","KeyType":"HASH"},{"AttributeName":"createdAt","KeyType":"RANGE"}],"Projection":{"ProjectionType":"ALL"}}]' \
  --billing-mode PAY_PER_REQUEST

table_exists otterworks-notification-preferences || awslocal dynamodb create-table \
  --table-name otterworks-notification-preferences \
  --attribute-definitions AttributeName=userId,AttributeType=S \
  --key-schema AttributeName=userId,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

table_exists otterworks-folders || awslocal dynamodb create-table \
  --table-name otterworks-folders \
  --attribute-definitions AttributeName=id,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

table_exists otterworks-file-versions || awslocal dynamodb create-table \
  --table-name otterworks-file-versions \
  --attribute-definitions \
    AttributeName=file_id,AttributeType=S \
    AttributeName=version,AttributeType=N \
  --key-schema \
    AttributeName=file_id,KeyType=HASH \
    AttributeName=version,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST

table_exists otterworks-file-shares || awslocal dynamodb create-table \
  --table-name otterworks-file-shares \
  --attribute-definitions AttributeName=id,AttributeType=S \
  --key-schema AttributeName=id,KeyType=HASH \
  --billing-mode PAY_PER_REQUEST

echo "LocalStack initialization complete!"
