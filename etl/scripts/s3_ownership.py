"""Resolve the AWS account that must own every bucket the ETL jobs touch.

Passed to S3 as ExpectedBucketOwner / ExpectedSourceBucketOwner so a renamed,
deleted or re-registered bucket owned by another account is rejected by S3
instead of silently receiving (or serving) our data.
"""

import os
import re

import boto3

ENV_VAR = "ETL_EXPECTED_BUCKET_OWNER"
_ACCOUNT_ID = re.compile(r"^\d{12}$")


def resolve_expected_bucket_owner(config, aws_access_key, aws_secret_key, aws_region):
    """Return the 12-digit account id from env, config [s3] expected_bucket_owner,
    or, when neither is set, the account of the ETL credentials (via STS)."""
    owner = os.environ.get(ENV_VAR, "").strip()
    if not owner:
        owner = config.get("s3", "expected_bucket_owner", fallback="").strip()
    if not owner:
        sts_client = boto3.client(
            "sts",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=aws_region,
        )
        owner = sts_client.get_caller_identity()["Account"]
    if not _ACCOUNT_ID.match(owner):
        raise ValueError("expected bucket owner must be a 12-digit AWS account id, got %r" % owner)
    return owner
