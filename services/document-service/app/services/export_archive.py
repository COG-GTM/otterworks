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


def _no_symlink_opener(path: str, flags: int) -> int:
    """Open ``path`` refusing to follow a symlink at the final component.

    The path is already fully resolved, so a symlink there can only be one
    swapped in after the containment check.
    """
    return os.open(path, flags | os.O_NOFOLLOW)


class ExportArchive:
    """Serves rendered export files from the archive directory."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = base_dir or os.environ.get(
            "EXPORT_ARCHIVE_DIR", DEFAULT_ARCHIVE_DIR
        )

    def _resolve(self, name: str) -> str | None:
        """Resolve ``name`` under the archive root, or ``None`` if it escapes."""
        root = os.path.realpath(self.base_dir)
        resolved = os.path.realpath(os.path.join(root, name))
        if os.path.commonpath((root, resolved)) != root:
            return None
        return resolved

    def read_export(self, name: str) -> str:
        """Return the contents of the named export.

        ``name`` may include a subdirectory (``"reports/q3.md"``). Raises
        ``FileNotFoundError`` when the export does not exist or resolves
        outside the archive directory.
        """
        logger.debug("export_read", name=name)
        resolved = self._resolve(name)
        if resolved is None:
            logger.warning("export_read_outside_archive", name=name)
            raise FileNotFoundError(
                errno.ENOENT, os.strerror(errno.ENOENT), os.path.join(self.base_dir, "")
            )
        with open(resolved, encoding="utf-8", opener=_no_symlink_opener) as handle:
            return handle.read()
