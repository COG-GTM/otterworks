"""Guards on how search-service is deployed.

search-service trusts the gateway-injected ``X-User-ID``, so deployments must
keep its auth middleware on and restrict who can reach it on the network.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TENANT_COMMON = REPO_ROOT / "scripts" / "lib" / "tenant-common.sh"
DEPLOY_DEV = REPO_ROOT / "scripts" / "deploy-dev.sh"
DEPLOY_TENANT = REPO_ROOT / "scripts" / "deploy-tenant.sh"
CHART = REPO_ROOT / "infrastructure" / "helm" / "search-service"

pytestmark = pytest.mark.skipif(
    not TENANT_COMMON.exists(),
    reason="deploy scripts are not available outside the repo",
)


def _search_service_case(script: Path) -> str:
    match = re.search(r"\n\s*search-service\)\n(.*?);;", script.read_text(), re.DOTALL)
    assert match, f"no search-service case in {script}"
    return match.group(1)


@pytest.mark.parametrize("script", [TENANT_COMMON, DEPLOY_DEV], ids=lambda p: p.name)
def test_deploy_scripts_do_not_disable_auth(script):
    assert "REQUIRE_AUTH=false" not in script.read_text()


def test_tenant_keeps_search_service_network_policy():
    assert "networkPolicy.enabled=true" in _search_service_case(TENANT_COMMON)
    own = re.search(
        r'^TENANT_OWN_NETPOL_SERVICES="([^"]*)"',
        TENANT_COMMON.read_text(),
        re.MULTILINE,
    )
    assert own and "search-service" in own.group(1).split()


def test_tenant_isolation_policy_excludes_services_with_their_own_policy():
    text = DEPLOY_TENANT.read_text()
    policy = text[text.index("name: tenant-isolation") :]
    policy = policy[: policy.index("YAML")]
    assert "podSelector: {}" not in policy
    assert "operator: NotIn" in policy
    assert "${TENANT_OWN_NETPOL_SERVICES" in policy


def test_chart_network_policy_admits_only_listed_apps():
    template = (CHART / "templates" / "networkpolicy.yaml").read_text()
    assert ".Values.networkPolicy.allowFromApps" in template
    values = (CHART / "values.yaml").read_text()
    block = values[values.index("networkPolicy:") :].split("\n\n", 1)[0]
    apps = re.findall(r"^\s+- (\S+)$", block, re.MULTILINE)
    assert "api-gateway" in apps
    assert set(apps) <= {"api-gateway", "admin-service"}
