# s3_ownership.py - ExpectedBucketOwner resolution shared by the ETL scripts.
#
# Every S3 call names the AWS account that must own the bucket, so a bucket
# that was deleted and re-created by another account (or a mistyped name that
# resolves to someone else's bucket) is rejected with 403 instead of silently
# receiving reports or serving forged input.

import os
import re

ENV_VAR = "ETL_S3_EXPECTED_BUCKET_OWNER"
_ACCOUNT_ID = re.compile(r"^\d{12}$")


def expected_bucket_owner(config):
    owner = os.environ.get(ENV_VAR) or config.get("s3", "expected_bucket_owner", fallback="")
    owner = owner.strip()
    if not _ACCOUNT_ID.match(owner):
        raise ValueError(
            f"S3 expected bucket owner must be a 12-digit AWS account ID; set {ENV_VAR} "
            "or [s3] expected_bucket_owner in config.ini"
        )
    return owner
