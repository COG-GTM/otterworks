"""Tests for the export archive reader."""

import os

import pytest

from app.services import export_archive
from app.services.export_archive import ExportArchive


@pytest.fixture
def archive(tmp_path):
    (tmp_path / "report.md").write_text("# Report\n", encoding="utf-8")
    nested = tmp_path / "reports"
    nested.mkdir()
    (nested / "q3.md").write_text("# Q3\n", encoding="utf-8")
    return ExportArchive(base_dir=str(tmp_path))


@pytest.fixture
def archive_with_outside_secret(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    (root / "report.md").write_text("# Report\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "tenant-secrets.env"
    secret.write_text("SUPPLIER_API_KEY=sk-test\n", encoding="utf-8")
    return ExportArchive(base_dir=str(root)), root, secret


def test_reads_export(archive):
    assert archive.read_export("report.md") == "# Report\n"


def test_reads_export_in_subdirectory(archive):
    assert archive.read_export("reports/q3.md") == "# Q3\n"


def test_missing_export_raises(archive):
    with pytest.raises(FileNotFoundError):
        archive.read_export("absent.md")


@pytest.mark.asyncio
async def test_export_endpoint_serves_archived_file(client, monkeypatch, tmp_path):
    (tmp_path / "report.md").write_text("# Report\n", encoding="utf-8")
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(tmp_path))

    resp = await client.get("/api/v1/documents/exports", params={"name": "report.md"})

    assert resp.status_code == 200
    assert resp.text == "# Report\n"


@pytest.mark.asyncio
async def test_export_endpoint_404s_for_unknown_name(client, monkeypatch, tmp_path):
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(tmp_path))

    resp = await client.get("/api/v1/documents/exports", params={"name": "absent.md"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_endpoint_404s_for_undecodable_file(client, monkeypatch, tmp_path):
    (tmp_path / "report.bin").write_bytes(b"\xff\xfe\x00binary")
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(tmp_path))

    resp = await client.get("/api/v1/documents/exports", params={"name": "report.bin"})

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_endpoint_404s_for_unreadable_file(client, monkeypatch, tmp_path):
    (tmp_path / "locked.md").write_text("# Locked\n", encoding="utf-8")
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(tmp_path))

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(export_archive, "open", refuse, raising=False)

    resp = await client.get("/api/v1/documents/exports", params={"name": "locked.md"})

    assert resp.status_code == 404


@pytest.mark.parametrize(
    "name",
    [
        "../outside/tenant-secrets.env",
        "reports/../../outside/tenant-secrets.env",
        "./report.md",
        "reports//q3.md",
        "report.md\x00.txt",
        "",
    ],
)
def test_rejects_names_that_leave_or_obscure_the_archive(archive_with_outside_secret, name):
    reader, _, _ = archive_with_outside_secret
    with pytest.raises(FileNotFoundError):
        reader.read_export(name)


def test_rejects_absolute_name(archive_with_outside_secret):
    reader, _, secret = archive_with_outside_secret
    with pytest.raises(FileNotFoundError):
        reader.read_export(str(secret))


def test_rejects_symlink_to_file_outside_archive(archive_with_outside_secret):
    reader, root, secret = archive_with_outside_secret
    os.symlink(secret, root / "leak.md")
    with pytest.raises(FileNotFoundError):
        reader.read_export("leak.md")


def test_rejects_symlinked_directory_outside_archive(archive_with_outside_secret):
    reader, root, secret = archive_with_outside_secret
    os.symlink(secret.parent, root / "reports")
    with pytest.raises(FileNotFoundError):
        reader.read_export("reports/tenant-secrets.env")


def test_symlink_swapped_in_after_containment_check_is_not_followed(
    archive_with_outside_secret, monkeypatch
):
    reader, root, secret = archive_with_outside_secret
    (root / "reports").mkdir()
    (root / "reports" / "tenant-secrets.env").write_text("# fine\n", encoding="utf-8")
    check = reader._archive_relative_parts

    def check_then_swap(name, path):
        parts = check(name, path)
        (root / "reports" / "tenant-secrets.env").unlink()
        (root / "reports").rmdir()
        os.symlink(secret.parent, root / "reports")
        return parts

    monkeypatch.setattr(reader, "_archive_relative_parts", check_then_swap)
    with pytest.raises(FileNotFoundError):
        reader.read_export("reports/tenant-secrets.env")


def test_traversal_error_does_not_reveal_resolved_target(archive_with_outside_secret):
    reader, root, _ = archive_with_outside_secret
    with pytest.raises(FileNotFoundError) as excinfo:
        reader.read_export("../outside/tenant-secrets.env")
    assert excinfo.value.filename == os.path.join(str(root), "../outside/tenant-secrets.env")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["../outside/tenant-secrets.env", "OUTSIDE_ABSOLUTE", "report.md\x00"],
)
async def test_export_endpoint_404s_for_names_outside_the_archive(
    client, monkeypatch, tmp_path, name
):
    root = tmp_path / "archive"
    root.mkdir()
    (root / "report.md").write_text("# Report\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "tenant-secrets.env"
    secret.write_text("SUPPLIER_API_KEY=sk-test\n", encoding="utf-8")
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(root))
    if name == "OUTSIDE_ABSOLUTE":
        name = str(secret)

    resp = await client.get("/api/v1/documents/exports", params={"name": name})

    assert resp.status_code == 404
    assert "SUPPLIER_API_KEY" not in resp.text

    owner = await client.get("/api/v1/documents/exports", params={"name": "report.md"})
    assert owner.status_code == 200
    assert owner.text == "# Report\n"
