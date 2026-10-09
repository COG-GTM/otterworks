"""Static checks on the IRSA policies in infrastructure/terraform/main.tf.

Stdlib only so it runs without terraform or provider credentials:
    python3 -m unittest discover -s tests/infra -t .
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAIN_TF = REPO_ROOT / "infrastructure" / "terraform" / "main.tf"
VARIABLES_TF = REPO_ROOT / "infrastructure" / "terraform" / "variables.tf"
APP_CONFIG_KT = (
    REPO_ROOT
    / "services/notification-service/src/main/kotlin"
    / "com/otterworks/notification/config/AppConfig.kt"
)

# Actions AWS does not support resource-level permissions for.
WILDCARD_RESOURCE_ALLOWED = {"cloudwatch:GetMetricData", "cloudwatch:ListMetrics"}


def _balanced_block(text, open_index):
    depth = 0
    for i in range(open_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_index : i + 1]
    raise ValueError("unbalanced braces in main.tf")


def _service_policy(text, service):
    match = re.search(r'"%s"\s*=\s*jsonencode\(\{' % re.escape(service), text)
    if match is None:
        raise AssertionError("no IRSA policy for %s" % service)
    return _balanced_block(text, match.end() - 1)


def _statements(policy):
    body_start = policy.index("Statement")
    statements = []
    i = policy.index("[", body_start) + 1
    while True:
        i = policy.find("{", i)
        if i == -1:
            return statements
        block = _balanced_block(policy, i)
        statements.append(block)
        i += len(block)


def _service_names(text):
    return re.findall(r'"([a-z-]+)"\s*=\s*jsonencode\(\{', text)


def _actions(statement):
    match = re.search(r"Action\s*=\s*\[(.*?)\]", statement, re.S)
    return set(re.findall(r'"([^"]+)"', match.group(1))) if match else set()


class IrsaPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main_tf = MAIN_TF.read_text()

    def test_wildcard_resource_only_for_actions_without_resource_support(self):
        for service in _service_names(self.main_tf):
            for statement in _statements(_service_policy(self.main_tf, service)):
                if re.search(r'Resource\s*=\s*\[\s*"\*"\s*\]', statement):
                    self.assertLessEqual(
                        _actions(statement),
                        WILDCARD_RESOURCE_ALLOWED,
                        "%s grants %s on Resource *"
                        % (service, sorted(_actions(statement))),
                    )

    def test_notification_service_ses_send_is_pinned_to_identity_and_from_address(self):
        policy = _service_policy(self.main_tf, "notification-service")
        ses = [s for s in _statements(policy) if "ses:SendEmail" in s]
        self.assertEqual(len(ses), 1)
        statement = ses[0]
        self.assertEqual(_actions(statement), {"ses:SendEmail", "ses:SendRawEmail"})
        self.assertRegex(statement, r"Resource\s*=\s*local\.ses_identity_arns\b")
        self.assertRegex(
            statement,
            r'StringEquals\s*=\s*\{\s*"ses:FromAddress"\s*=\s*var\.ses_from_address\s*\}',
        )

    def test_ses_identity_arns_cover_only_the_from_address_and_its_domain(self):
        match = re.search(
            r"ses_identity_arns\s*=\s*distinct\(\[(.*?)\n\s*\]\)", self.main_tf, re.S
        )
        self.assertIsNotNone(match)
        arns = re.findall(r'^\s*"(.+)",\s*$', match.group(1), re.M)
        self.assertEqual(
            arns,
            [
                "${local.ses_identity_arn_prefix}/${var.ses_from_address}",
                "${local.ses_identity_arn_prefix}/"
                "${coalesce(var.ses_identity_domain, "
                'split("@", var.ses_from_address)[1])}',
            ],
        )
        self.assertRegex(
            self.main_tf,
            r'ses_identity_arn_prefix\s*=\s*"arn:\$\{data\.aws_partition\.current\.partition\}'
            r":ses:\$\{var\.aws_region\}:\$\{data\.aws_caller_identity\.current\.account_id\}"
            r':identity"',
        )

    def test_ses_from_address_matches_service_default_and_rejects_wildcards(self):
        variables = VARIABLES_TF.read_text()
        match = re.search(r'variable "ses_from_address" \{', variables)
        self.assertIsNotNone(match)
        block = _balanced_block(variables, match.end() - 1)

        tf_default = re.search(r'default\s*=\s*"([^"]+)"', block).group(1)
        app_default = re.search(
            r'getenv\("SES_FROM_EMAIL"\)\s*\?:\s*"([^"]+)"', APP_CONFIG_KT.read_text()
        ).group(1)
        self.assertEqual(tf_default, app_default)

        hcl_regex = re.search(r'regex\("(.+?)", var\.ses_from_address\)', block).group(
            1
        )
        pattern = re.compile(hcl_regex.replace("\\\\", "\\"))
        self.assertTrue(pattern.fullmatch(tf_default))
        for bad in (
            "*@otterworks.io",
            "*",
            "a@b@c.io",
            "notifications@*.io",
            "x@localhost",
        ):
            self.assertIsNone(pattern.fullmatch(bad), bad)


if __name__ == "__main__":
    unittest.main()
