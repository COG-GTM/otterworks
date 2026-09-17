"""Reads previously generated export files back out of the export archive.

Exports are rendered to disk by the export worker under ``EXPORT_ARCHIVE_DIR``
(optionally in per-folder subdirectories) and served back to the caller by name.
"""

from __future__ import annotations

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

    def _is_contained(self, path: str) -> bool:
        """Whether ``path`` resolves to a location inside the archive root."""
        root = os.path.realpath(self.base_dir)
        resolved = os.path.realpath(path)
        return resolved == root or resolved.startswith(root + os.sep)

    def read_export(self, name: str) -> str:
        """Return the contents of the named export.

        ``name`` may include a subdirectory (``"reports/q3.md"``), but must
        resolve to a file inside the archive root. Raises ``FileNotFoundError``
        when the export does not exist or escapes the archive.
        """
        path = os.path.join(self.base_dir, name)
        logger.debug("export_read", name=name)
        if not self._is_contained(path):
            logger.warning("export_read_outside_archive", name=name)
            raise FileNotFoundError(2, "No such file or directory", name)
        with open(path, encoding="utf-8") as handle:
            return handle.read()
