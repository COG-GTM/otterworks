# s3_ownership.py - Resolve the AWS account that must own the ETL's S3 buckets.
#
# Every S3 call made by the ETL scripts passes ExpectedBucketOwner (and
# ExpectedSourceBucketOwner for copies) so a bucket name that has been deleted
# and re-registered by another AWS account is rejected with 403 AccessDenied
# instead of silently receiving (or serving) our data.

import os
import re

import boto3

_ACCOUNT_ID = re.compile(r"^[0-9]{12}$")


def resolve_expected_bucket_owner(config, aws_access_key, aws_secret_key, aws_region):
    """Return the 12-digit account id that owns the ETL buckets.

    Precedence: ETL_EXPECTED_BUCKET_OWNER env var, then [s3] expected_bucket_owner
    in config.ini, then the account of the ETL's own credentials (STS).
    """
    owner = os.environ.get("ETL_EXPECTED_BUCKET_OWNER", "").strip()
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
        raise ValueError("expected S3 bucket owner must be a 12-digit AWS account id, got %r" % owner)
    return owner
