"""Tests for the export archive reader."""

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


def test_reads_export(archive):
    assert archive.read_export("report.md") == "# Report\n"


def test_reads_export_in_subdirectory(archive):
    assert archive.read_export("reports/q3.md") == "# Q3\n"


def test_missing_export_raises(archive):
    with pytest.raises(FileNotFoundError):
        archive.read_export("absent.md")


def test_traversal_outside_archive_raises(archive, tmp_path):
    (tmp_path.parent / "tenant-secrets.env").write_text(
        "SUPPLIER_API_KEY=secret\n", encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError):
        archive.read_export("../tenant-secrets.env")


def test_absolute_path_outside_archive_raises(archive, tmp_path):
    outside = tmp_path.parent / "absolute-secrets.env"
    outside.write_text("SUPPLIER_API_KEY=secret\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        archive.read_export(str(outside))


@pytest.mark.asyncio
async def test_export_endpoint_404s_for_traversal(client, monkeypatch, tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    (tmp_path / "tenant-secrets.env").write_text(
        "SUPPLIER_API_KEY=secret\n", encoding="utf-8"
    )
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(root))

    resp = await client.get(
        "/api/v1/documents/exports", params={"name": "../tenant-secrets.env"}
    )

    assert resp.status_code == 404
    assert "SUPPLIER_API_KEY" not in resp.text


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
