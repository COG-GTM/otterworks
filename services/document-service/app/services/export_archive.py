"""Reads previously generated export files back out of the export archive.

Exports are rendered to disk by the export worker under ``EXPORT_ARCHIVE_DIR``
(optionally in per-folder subdirectories) and served back to the caller by name.
"""

from __future__ import annotations

import errno
import os

import structlog

logger = structlog.get_logger()

DEFAULT_ARCHIVE_DIR = "/var/lib/otterworks/exports"


class ExportArchive:
    """Serves rendered export files from the archive directory."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.environ.get(
            "EXPORT_ARCHIVE_DIR", DEFAULT_ARCHIVE_DIR
        )

    def read_export(self, name: str) -> str:
        """Return the contents of the named export.

        ``name`` may include a subdirectory (``"reports/q3.md"``). Raises
        ``FileNotFoundError`` when the export does not exist or when ``name``
        does not resolve to a file inside the archive root.
        """
        path = os.path.join(self.base_dir, name)
        resolved = self._resolve_inside_archive(name, path)
        logger.debug("export_read", name=name)
        try:
            fd = self._open_without_following_links(resolved)
        except FileNotFoundError:
            raise _not_found(path) from None
        with open(fd, encoding="utf-8") as handle:
            return handle.read()

    def _open_without_following_links(self, resolved: str) -> int:
        """Open ``resolved`` one component at a time from the archive root.

        ``O_NOFOLLOW`` on every component means a symlink swapped in after
        ``_resolve_inside_archive`` ran fails the open instead of escaping the root.
        """
        root = os.path.realpath(self.base_dir)
        parts = os.path.relpath(resolved, root).split(os.sep)
        dir_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in parts[:-1]:
                next_fd = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=dir_fd
                )
                os.close(dir_fd)
                dir_fd = next_fd
            return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        finally:
            os.close(dir_fd)

    def _resolve_inside_archive(self, name: str, path: str) -> str:
        if "\x00" in name or os.path.isabs(name):
            logger.warning("export_read_rejected", reason="invalid_name")
            raise _not_found(path)
        root = os.path.realpath(self.base_dir)
        resolved = os.path.realpath(path)
        if resolved == root or os.path.commonpath([root, resolved]) != root:
            logger.warning("export_read_rejected", reason="outside_archive")
            raise _not_found(path)
        return resolved


def _not_found(path: str) -> FileNotFoundError:
    return FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)
