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

# O_PATH directory handles need only search (x) permission, matching what open(path) needs.
_DIR_FLAGS = getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY


class ExportArchive:
    """Serves rendered export files from the archive directory."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.environ.get("EXPORT_ARCHIVE_DIR", DEFAULT_ARCHIVE_DIR)

    def read_export(self, name: str) -> str:
        """Return the contents of the named export.

        ``name`` may include a subdirectory (``"reports/q3.md"``). Raises
        ``FileNotFoundError`` when the export does not exist or when ``name``
        does not resolve to a file inside the archive root.
        """
        path = os.path.join(self.base_dir, name)
        logger.debug("export_read", name=name)
        parts = self._archive_relative_parts(name, path)
        try:
            fd = self._open_inside_archive(parts)
        except (FileNotFoundError, NotADirectoryError):
            raise _not_found(path) from None
        except OSError as exc:
            if exc.errno == errno.ELOOP:
                logger.warning("export_read_rejected", reason="symlink")
                raise _not_found(path) from None
            raise
        with open(fd, encoding="utf-8") as handle:
            return handle.read()

    def _archive_relative_parts(self, name: str, path: str) -> list[str]:
        """Split ``name`` into components that stay inside the archive root."""
        parts = name.split("/")
        if "\x00" in name or os.path.isabs(name) or any(part in ("", ".", "..") for part in parts):
            logger.warning("export_read_rejected", reason="invalid_name")
            raise _not_found(path)
        root = os.path.realpath(self.base_dir)
        resolved = os.path.realpath(path)
        if os.path.commonpath([root, resolved]) != root or resolved == root:
            logger.warning("export_read_rejected", reason="outside_archive")
            raise _not_found(path)
        return parts

    def _open_inside_archive(self, parts: list[str]) -> int:
        """Open ``parts`` component by component from the archive root.

        Every component is opened relative to its parent with ``O_NOFOLLOW``, so a
        symlink planted or swapped in after the containment check cannot redirect
        the read outside the archive.
        """
        dir_fd = os.open(self.base_dir, _DIR_FLAGS)
        try:
            for part in parts[:-1]:
                next_fd = os.open(part, _DIR_FLAGS | os.O_NOFOLLOW, dir_fd=dir_fd)
                os.close(dir_fd)
                dir_fd = next_fd
            return os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        finally:
            os.close(dir_fd)


def _not_found(path: str) -> FileNotFoundError:
    return FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), path)
