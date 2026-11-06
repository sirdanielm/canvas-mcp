"""Private, immutable local artifacts. No grade records in source control."""

from __future__ import annotations

import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

from .client import GradebookError
from .model import digest

_SUPPORTS_OPEN_DIR_FD = os.open in os.supports_dir_fd


class Store:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)

    def save(self, kind: str, value: dict[str, Any]) -> tuple[str, Path]:
        if kind not in (
            "snapshot",
            "review",
            "refresh",
            "push",
            "receipt",
            "source_sidecar",
        ):
            raise GradebookError("Invalid artifact type.")
        if kind == "source_sidecar":
            from .source_sidecar_store import validate_envelope_for_save

            validate_envelope_for_save(self, value)
        artifact_id = digest(value)
        path = self.root / f"{kind}-{artifact_id}.json"
        fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(value, stream, allow_nan=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if self.load(kind, artifact_id) != value:
                    raise GradebookError(
                        "Stored artifact failed integrity verification."
                    ) from None
            directory = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return artifact_id, path

    def load(self, kind: str, artifact_id: str) -> dict[str, Any]:
        if kind not in (
            "snapshot",
            "review",
            "refresh",
            "push",
            "receipt",
            "source_sidecar",
        ) or not re.fullmatch(r"[a-f0-9]{64}", artifact_id):
            raise GradebookError("Invalid artifact reference.")
        if kind == "source_sidecar":
            return self._load_source_sidecar(artifact_id)
        path = self.root / f"{kind}-{artifact_id}.json"
        if path.is_symlink():
            raise GradebookError("Artifact must not be a symlink.")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GradebookError("Local artifact is unavailable.") from exc
        if not isinstance(value, dict) or digest(value) != artifact_id:
            raise GradebookError("Local artifact failed integrity verification.")
        return value

    def _load_source_sidecar(self, artifact_id: str) -> dict[str, Any]:
        """Open once, no symlinks or blocking special files; hash exact bounded bytes."""
        from .source_sidecar_store import MAX_BYTES

        if (
            not all(
                hasattr(os, name)
                for name in ("O_NOFOLLOW", "O_NONBLOCK", "O_DIRECTORY")
            )
            or not _SUPPORTS_OPEN_DIR_FD
        ):
            raise GradebookError("Safe sidecar reading is unavailable.")
        directory = fd = None
        try:
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            fd = os.open(
                f"source_sidecar-{artifact_id}.json",
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                dir_fd=directory,
            )
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES + 1:
                raise GradebookError("Sidecar is unavailable or invalid.")
            chunks = []
            remaining = MAX_BYTES + 2
            while remaining:
                chunk = os.read(fd, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            if len(raw) > MAX_BYTES + 1:
                raise GradebookError("Sidecar is unavailable or invalid.")
            value = json.loads(raw)
            if not isinstance(value, dict) or digest(value) != artifact_id:
                raise GradebookError("Sidecar failed integrity verification.")
            return value
        except (OSError, ValueError, UnicodeError, TypeError, RecursionError):
            raise GradebookError("Sidecar is unavailable or invalid.") from None
        finally:
            if fd is not None:
                os.close(fd)
            if directory is not None:
                os.close(directory)

    def read_edits(
        self,
        filename: str,
        baseline: dict[str, Any] | None = None,
        tab_names: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        path = self.inbox_file(filename)
        if path.suffix == ".xlsx":
            from .workbook import read_workbook_edits

            if baseline is None:
                raise GradebookError("An immutable baseline is required.")
            return read_workbook_edits(path, baseline, tab_names)
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise GradebookError("Cannot read edit file.") from exc
        if not isinstance(result, dict):
            raise GradebookError("Invalid edit file.")
        return result

    def inbox_file(self, filename: str) -> Path:
        # Only explicit files in the private inbox, never arbitrary filesystem reads.
        if not re.fullmatch(r"[a-zA-Z0-9_-]+\.(json|xlsx)", filename):
            raise GradebookError("Use an edit filename from the local inbox.")
        inbox = self.root / "inbox"
        path = inbox / filename
        if inbox.is_symlink() or path.is_symlink() or not path.is_file():
            raise GradebookError("Edit file is unavailable or is a symlink.")
        if path.stat().st_size > 5_000_000:
            raise GradebookError("Edit file is too large.")
        return path
