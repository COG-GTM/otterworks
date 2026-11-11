from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
os.environ.setdefault(
    "BILLING_SVC_DATABASE_URL",
    "postgresql://billing_svc:billing_svc@localhost:56432/billing_svc_dev",
)
os.environ.setdefault("BILLING_SVC_SERVICE_TOKEN", "test-service-token")
os.environ.setdefault("BILLING_SVC_JWT_SECRET", "test-jwt-secret-0123456789abcdef0123")
