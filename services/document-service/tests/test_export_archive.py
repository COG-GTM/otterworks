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


@pytest.fixture
def archive_with_outside_file(tmp_path):
    root = tmp_path / "archive"
    (root / "reports").mkdir(parents=True)
    (root / "report.md").write_text("# Report\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secrets.env").write_text("JWT_SECRET=leaked\n", encoding="utf-8")
    return ExportArchive(base_dir=str(root)), tmp_path


@pytest.mark.parametrize(
    "name",
    [
        "../outside/secrets.env",
        "reports/../../outside/secrets.env",
        "..",
        ".",
        "reports/..",
    ],
)
def test_rejects_relative_traversal(archive_with_outside_file, name):
    archive, _ = archive_with_outside_file
    with pytest.raises(FileNotFoundError):
        archive.read_export(name)


def test_rejects_absolute_name(archive_with_outside_file):
    archive, tmp_path = archive_with_outside_file
    with pytest.raises(FileNotFoundError):
        archive.read_export(str(tmp_path / "outside" / "secrets.env"))


def test_rejects_proc_environ(archive_with_outside_file):
    archive, _ = archive_with_outside_file
    with pytest.raises(FileNotFoundError):
        archive.read_export("/proc/self/environ")


def test_rejects_nul_byte(archive_with_outside_file):
    archive, _ = archive_with_outside_file
    with pytest.raises(FileNotFoundError):
        archive.read_export("report.md\x00.txt")


def test_rejects_symlink_escaping_archive(archive_with_outside_file):
    archive, tmp_path = archive_with_outside_file
    link = tmp_path / "archive" / "escape.md"
    link.symlink_to(tmp_path / "outside" / "secrets.env")
    with pytest.raises(FileNotFoundError):
        archive.read_export("escape.md")


def test_allows_dotdot_that_stays_inside(archive_with_outside_file):
    archive, _ = archive_with_outside_file
    assert archive.read_export("reports/../report.md") == "# Report\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name", ["../outside/secrets.env", "/proc/self/environ", "%2e%2e/outside/secrets.env"]
)
async def test_export_endpoint_404s_for_traversal(client, monkeypatch, tmp_path, name):
    root = tmp_path / "archive"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secrets.env").write_text("JWT_SECRET=leaked\n", encoding="utf-8")
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(root))

    resp = await client.get("/api/v1/documents/exports", params={"name": name})

    assert resp.status_code == 404
    assert "leaked" not in resp.text
