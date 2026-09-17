# ------------------------------------------------------------------------------
# OtterWorks Messaging Module
# SQS queues and SNS topics for event-driven architecture
# ------------------------------------------------------------------------------

locals {
  common_tags = {
    Module  = "messaging"
    Project = var.project
  }
}

# --- Event Encryption Key ---

resource "aws_kms_key" "events" {
  description             = "${var.project} SNS event topic encryption (${var.environment})"
  enable_key_rotation     = true
  deletion_window_in_days = var.kms_key_deletion_window
  policy                  = data.aws_iam_policy_document.events_key.json

  tags = merge(local.common_tags, {
    Service = "shared-events"
  })
}

resource "aws_kms_alias" "events" {
  name          = "alias/${var.project}-events-${var.environment}"
  target_key_id = aws_kms_key.events.key_id
}

data "aws_caller_identity" "current" {}

# SNS encrypts the message itself, but the SQS subscribers are delivered to by
# the SNS service principal, which therefore needs the key as well.
data "aws_iam_policy_document" "events_key" {
  statement {
    sid       = "AccountAdmin"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  statement {
    sid       = "AllowSNS"
    effect    = "Allow"
    actions   = ["kms:GenerateDataKey*", "kms:Decrypt"]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["sns.amazonaws.com"]
    }
  }
}

# --- SNS Topic: System Events ---

resource "aws_sns_topic" "events" {
  name              = "${var.project}-events-${var.environment}"
  kms_master_key_id = aws_kms_key.events.id

  tags = merge(local.common_tags, {
    Service = "shared-events"
  })
}

# --- SQS: Notifications Queue ---

resource "aws_sqs_queue" "notifications" {
  name                       = "${var.project}-notifications-${var.environment}"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.notifications_dlq.arn
    maxReceiveCount     = 3
  })

  tags = merge(local.common_tags, {
    Service = "notification-service"
  })
}

resource "aws_sqs_queue" "notifications_dlq" {
  name                      = "${var.project}-notifications-dlq-${var.environment}"
  message_retention_seconds = 1209600

  tags = merge(local.common_tags, {
    Service = "notification-service"
  })
}

# --- SQS: Analytics Events Queue ---

resource "aws_sqs_queue" "analytics_events" {
  name                       = "${var.project}-analytics-events-${var.environment}"
  visibility_timeout_seconds = 120
  message_retention_seconds  = 259200
  receive_wait_time_seconds  = 20

  tags = merge(local.common_tags, {
    Service = "analytics-service"
  })
}

# --- SQS: Search Indexing Queue ---

resource "aws_sqs_queue" "search_indexing" {
  name                       = "${var.project}-search-indexing-${var.environment}"
  visibility_timeout_seconds = 60
  message_retention_seconds  = 86400
  receive_wait_time_seconds  = 20

  tags = merge(local.common_tags, {
    Service = "search-service"
  })
}

# --- SNS -> SQS Subscriptions ---

resource "aws_sns_topic_subscription" "notifications" {
  topic_arn = aws_sns_topic.events.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.notifications.arn

  filter_policy = jsonencode({
    eventType = ["file_shared", "comment_added", "document_edited", "user_mentioned"]
  })
}

resource "aws_sns_topic_subscription" "analytics" {
  topic_arn = aws_sns_topic.events.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.analytics_events.arn
}

resource "aws_sns_topic_subscription" "search_indexing" {
  topic_arn = aws_sns_topic.events.arn
  protocol  = "sqs"
  endpoint  = aws_sqs_queue.search_indexing.arn

  filter_policy = jsonencode({
    eventType = ["document_created", "document_updated", "document_deleted", "file_uploaded", "file_deleted"]
  })
}

# --- SQS Policies ---

resource "aws_sqs_queue_policy" "notifications" {
  queue_url = aws_sqs_queue.notifications.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.notifications.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.events.arn } }
    }]
  })
}

resource "aws_sqs_queue_policy" "analytics_events" {
  queue_url = aws_sqs_queue.analytics_events.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.analytics_events.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.events.arn } }
    }]
  })
}

resource "aws_sqs_queue_policy" "search_indexing" {
  queue_url = aws_sqs_queue.search_indexing.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.search_indexing.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.events.arn } }
    }]
  })
}
