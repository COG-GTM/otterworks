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
        ``FileNotFoundError`` when the export does not exist or ``name`` resolves
        to a path outside the archive root.
        """
        path, resolved = self._resolve(name)
        logger.debug("export_read", name=name)
        try:
            fd = os.open(resolved, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError as exc:
            raise FileNotFoundError(exc.errno, exc.strerror, path) from None
        with open(fd, encoding="utf-8") as handle:
            return handle.read()

    def _resolve(self, name: str) -> tuple[str, str]:
        if "\x00" in name or os.path.isabs(name):
            raise self._not_found(name)
        path = os.path.join(self.base_dir, name)
        root = os.path.realpath(self.base_dir)
        resolved = os.path.realpath(path)
        if resolved == root or os.path.commonpath([root, resolved]) != root:
            raise self._not_found(name)
        return path, resolved

    def _not_found(self, name: str) -> FileNotFoundError:
        logger.warning("export_read_rejected", name=name)
        return FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), name)
