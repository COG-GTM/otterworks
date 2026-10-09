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



@pytest.fixture
def jailed_archive(tmp_path):
    root = tmp_path / "archive"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "q3.md").write_text("# Q3\n", encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "tenant-secrets.env").write_text("SUPPLIER_API_KEY=secret\n", encoding="utf-8")
    return ExportArchive(base_dir=str(root)), root, outside


@pytest.mark.parametrize(
    "name",
    [
        "../outside/tenant-secrets.env",
        "reports/../../outside/tenant-secrets.env",
        "..",
        ".",
        "",
        "/etc/passwd",
        "/proc/self/environ",
        "report.md\x00.txt",
    ],
)
def test_names_escaping_the_archive_raise_not_found(jailed_archive, name):
    archive, _, _ = jailed_archive
    with pytest.raises(FileNotFoundError):
        archive.read_export(name)


def test_absolute_path_inside_archive_is_rejected(jailed_archive):
    archive, root, _ = jailed_archive
    with pytest.raises(FileNotFoundError):
        archive.read_export(str(root / "reports" / "q3.md"))


def test_symlink_pointing_outside_the_archive_is_rejected(jailed_archive):
    archive, root, outside = jailed_archive
    (root / "leak.env").symlink_to(outside / "tenant-secrets.env")
    with pytest.raises(FileNotFoundError):
        archive.read_export("leak.env")



def test_symlink_swapped_in_after_the_check_is_not_followed(jailed_archive, monkeypatch):
    archive, root, outside = jailed_archive
    resolve = ExportArchive._resolve_inside_archive

    def resolve_then_swap(self, name, path):
        resolved = resolve(self, name, path)
        (root / "reports" / "q3.md").unlink()
        (root / "reports" / "q3.md").symlink_to(outside / "tenant-secrets.env")
        return resolved

    monkeypatch.setattr(ExportArchive, "_resolve_inside_archive", resolve_then_swap)
    with pytest.raises(OSError):
        archive.read_export("reports/q3.md")


def test_directory_swapped_for_symlink_after_the_check_is_not_followed(
    jailed_archive, monkeypatch
):
    archive, root, outside = jailed_archive
    (outside / "q3.md").write_text("SUPPLIER_API_KEY=secret\n", encoding="utf-8")
    resolve = ExportArchive._resolve_inside_archive

    def resolve_then_swap(self, name, path):
        resolved = resolve(self, name, path)
        (root / "reports").rename(root / "reports-old")
        (root / "reports").symlink_to(outside, target_is_directory=True)
        return resolved

    monkeypatch.setattr(ExportArchive, "_resolve_inside_archive", resolve_then_swap)
    with pytest.raises(OSError):
        archive.read_export("reports/q3.md")

def test_symlinked_archive_root_still_serves_exports(jailed_archive, tmp_path):
    _, root, _ = jailed_archive
    link = tmp_path / "archive-link"
    link.symlink_to(root, target_is_directory=True)
    assert ExportArchive(base_dir=str(link)).read_export("reports/q3.md") == "# Q3\n"


def test_rejected_name_error_matches_missing_export(jailed_archive):
    archive, root, _ = jailed_archive
    with pytest.raises(FileNotFoundError) as missing:
        archive.read_export("absent.md")
    with pytest.raises(FileNotFoundError) as escaped:
        archive.read_export("../outside/tenant-secrets.env")
    assert missing.value.errno == escaped.value.errno
    assert missing.value.filename == str(root / "absent.md")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    ["../outside/tenant-secrets.env", "/proc/self/environ", "/etc/passwd", "a\x00b"],
)
async def test_export_endpoint_404s_for_names_outside_the_archive(
    client, monkeypatch, jailed_archive, name
):
    _, root, _ = jailed_archive
    monkeypatch.setenv("EXPORT_ARCHIVE_DIR", str(root))

    resp = await client.get("/api/v1/documents/exports", params={"name": name})

    assert resp.status_code == 404
    assert "SUPPLIER_API_KEY" not in resp.text
    assert "root:" not in resp.text

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
