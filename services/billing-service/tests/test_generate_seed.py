from __future__ import annotations

import runpy
from pathlib import Path

import pytest

import scripts.generate_seed as generate_seed

SCRIPT = Path(generate_seed.__file__)


def test_generate_rewrites_schema_for_each_table(tmp_path, monkeypatch) -> None:
    legacy = tmp_path / "seed.sql"
    legacy.write_text(
        "-- header\n"
        "INSERT INTO billing.tenants (id) VALUES\n    ('t');\n"
        "INSERT INTO billing.plans (id) VALUES ('p');\n"
        "INSERT INTO billing.subscriptions (id) VALUES ('s');\n"
        "INSERT INTO billing.invoices (id) VALUES ('i');\n"
    )
    monkeypatch.setattr(generate_seed, "LEGACY", legacy)
    assert generate_seed.generate() == (
        "INSERT INTO billing_svc.tenants (id) VALUES\n    ('t');\n"
        "\nINSERT INTO billing_svc.plans (id) VALUES ('p');\n"
        "\nINSERT INTO billing_svc.subscriptions (id) VALUES ('s');\n"
    )


def test_generate_fails_when_legacy_section_missing(tmp_path, monkeypatch) -> None:
    legacy = tmp_path / "seed.sql"
    legacy.write_text("INSERT INTO billing.tenants (id) VALUES ('t');\n")
    monkeypatch.setattr(generate_seed, "LEGACY", legacy)
    with pytest.raises(RuntimeError, match="missing legacy seed section: plans"):
        generate_seed.generate()


def test_main_writes_generated_seed(monkeypatch) -> None:
    written: dict[Path, str] = {}
    monkeypatch.setattr(Path, "write_text", lambda self, text: written.setdefault(self, text))
    runpy.run_path(str(SCRIPT), run_name="__main__")
    output = SCRIPT.resolve().parents[1] / "db" / "seed.sql"
    assert written == {output: generate_seed.generate()}
