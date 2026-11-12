# s3_ownership.py - Bucket-ownership guard shared by the ETL scripts
#
# Every S3 request passes ExpectedBucketOwner so a bucket that has been
# deleted and re-created (or squatted) under another AWS account is rejected
# with 403 instead of silently receiving or serving pipeline data.

import os
import re

ENV_VAR = "ETL_S3_EXPECTED_BUCKET_OWNER"
_ACCOUNT_ID = re.compile(r"^[0-9]{12}$")


def expected_bucket_owner(config):
    """Return the 12-digit AWS account ID that must own every ETL bucket."""
    owner = os.environ.get(ENV_VAR) or config.get("s3", "expected_bucket_owner", fallback="")
    owner = owner.strip()
    if not _ACCOUNT_ID.match(owner):
        raise SystemExit(
            f"ERROR: [s3] expected_bucket_owner (or {ENV_VAR}) must be the 12-digit AWS "
            "account ID that owns the ETL buckets"
        )
    return owner
