import tempfile
import unittest
from pathlib import Path

import check_java4shell as c


class VerdictTest(unittest.TestCase):
    def test_affected_builds_fail(self):
        for v in ["17.0.6", "17.0.10", "17.0.21", "21.0.13", "21.0.12.1", "25.0.5", "27.0.1"]:
            self.assertIsNotNone(c.verdict(c.parse_version(v)), v)

    def test_fixed_and_unaffected_builds_pass(self):
        for v in ["17.0.21.1", "17.0.22", "21.0.13.1", "25.0.5.1", "27.0.1.1",
                  "17.0.5", "11.0.25", "1.8.0_412"]:
            self.assertIsNone(c.verdict(c.parse_version(v)), v)

    def test_unlisted_major_fails(self):
        self.assertIsNotNone(c.verdict(c.parse_version("23.0.2")))


class DockerfileFromTest(unittest.TestCase):
    def test_floating_and_old_tags_fail(self):
        for ref in ["eclipse-temurin:17-jre-jammy", "gradle:8.6-jdk17",
                    "eclipse-temurin:21", "sbtscala/scala-sbt:eclipse-temurin-jammy-17.0.10_7_1.9.9_3.4.1",
                    "eclipse-temurin:17.0.21_9-jre-jammy"]:
            self.assertIsNotNone(c.check_from(ref), ref)

    def test_pinned_fixed_and_unrelated_tags_pass(self):
        for ref in ["eclipse-temurin:17.0.21.1_2-jre-jammy", "eclipse-temurin:21.0.13.1_2-jdk",
                    "eclipse-temurin:11-jre-jammy", "eclipse-temurin:8-jre",
                    "maven:3.8.7-eclipse-temurin-8", "python:3.12-slim", "golang:1.22"]:
            self.assertIsNone(c.check_from(ref), ref)


class SetupJavaTest(unittest.TestCase):
    def test_versions(self):
        self.assertIsNone(c.check_setup_java("'17.0.21+100000002'"))
        self.assertIsNone(c.check_setup_java("11"))
        self.assertIsNone(c.check_setup_java("'8'"))
        self.assertIsNotNone(c.check_setup_java("'17'"))
        self.assertIsNotNone(c.check_setup_java("17.0.21+9"))
        self.assertIsNotNone(c.check_setup_java("21.x"))

    def test_static_scan(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "svc").mkdir()
            (root / "svc" / "Dockerfile").write_text("FROM eclipse-temurin:17-jre-jammy\n")
            wf = root / ".github" / "workflows"
            wf.mkdir(parents=True)
            (wf / "ci.yml").write_text("      with:\n        java-version: |\n          17\n          11\n")
            self.assertFalse(c.cmd_static([d]))
            (root / "svc" / "Dockerfile").write_text("FROM eclipse-temurin:17.0.21.1_2-jre-jammy\n")
            (wf / "ci.yml").write_text("      with:\n        java-version: |\n          17.0.21+100000002\n          11\n")
            self.assertTrue(c.cmd_static([d]))


if __name__ == "__main__":
    unittest.main()
