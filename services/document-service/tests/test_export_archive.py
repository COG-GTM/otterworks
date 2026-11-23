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
def secret_outside_archive(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    (root / "report.md").write_text("# Report\n", encoding="utf-8")
    nested = root / "reports"
    nested.mkdir()
    (nested / "q3.md").write_text("# Q3\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secrets.env"
    secret.write_text("JWT_SECRET=leaked\n", encoding="utf-8")
    (root / "escape.md").symlink_to(secret)
    (root / "escape-dir").symlink_to(outside, target_is_directory=True)
    return root, secret


@pytest.mark.parametrize(
    "name",
    [
        "../outside/secrets.env",
        "reports/../../outside/secrets.env",
        "../../../../../../etc/passwd",
        "/etc/passwd",
        "escape.md",
        "escape-dir/secrets.env",
        ".",
        "reports/..",
        "report.md\x00.txt",
    ],
)
def test_rejects_paths_outside_archive(secret_outside_archive, name):
    root, _ = secret_outside_archive
    with pytest.raises(FileNotFoundError):
        ExportArchive(base_dir=str(root)).read_export(name)


def test_rejects_absolute_path_to_real_file(secret_outside_archive):
    root, secret = secret_outside_archive
    with pytest.raises(FileNotFoundError):
        ExportArchive(base_dir=str(root)).read_export(str(secret))


def test_allows_dot_segments_that_stay_inside(secret_outside_archive):
    root, _ = secret_outside_archive
    archive = ExportArchive(base_dir=str(root))
    assert archive.read_export("reports/../report.md") == "# Report\n"
    assert archive.read_export("./reports/q3.md") == "# Q3\n"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "../outside/secrets.env",
        "../../etc/passwd",
        "/etc/passwd",
        "escape.md",
        "../../../../proc/self/environ",
    ],
)
async def test_export_endpoint_404s_for_traversal(
    client, monkeypatch, secret_outside_archive, name
):
    root, _ = secret_outside_archive
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(root))

    resp = await client.get("/api/v1/documents/exports", params={"name": name})

    assert resp.status_code == 404
    assert "leaked" not in resp.text


@pytest.mark.asyncio
async def test_export_endpoint_serves_subdirectory_export(
    client, monkeypatch, secret_outside_archive
):
    root, _ = secret_outside_archive
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(root))

    resp = await client.get("/api/v1/documents/exports", params={"name": "reports/q3.md"})

    assert resp.status_code == 200
    assert resp.text == "# Q3\n"
