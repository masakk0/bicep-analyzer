"""Versioned and workspace-confined Bicep document editing."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class DocumentSnapshot:
    path: Optional[str]
    content: str
    revision: int
    dirty: bool


class BicepWorkspace:
    """Owns the active Bicep document and applies conflict-safe edits."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self._path: Optional[Path] = None
        self._content = ""
        self._revision = 0
        self._dirty = False

    def snapshot(self) -> DocumentSnapshot:
        relative_path = self._path.relative_to(self.root).as_posix() if self._path else None
        return DocumentSnapshot(relative_path, self._content, self._revision, self._dirty)

    def open(self, relative_path: str) -> DocumentSnapshot:
        path = self._resolve(relative_path)
        if not path.is_file():
            raise FileNotFoundError(f"Bicep file not found: {relative_path}")
        self._path = path
        self._content = path.read_text(encoding="utf-8")
        self._revision += 1
        self._dirty = False
        return self.snapshot()

    def update(self, content: str, revision: Optional[int] = None) -> DocumentSnapshot:
        self._check_revision(revision)
        self._content = content
        self._revision += 1
        self._dirty = True
        return self.snapshot()

    def new(self, content: str) -> DocumentSnapshot:
        self._path = None
        self._content = content
        self._revision += 1
        self._dirty = True
        return self.snapshot()

    def replace(self, old_text: str, new_text: str, revision: Optional[int] = None) -> DocumentSnapshot:
        self._check_revision(revision)
        occurrences = self._content.count(old_text)
        if not old_text or occurrences != 1:
            raise ValueError(
                f"The text to replace must occur exactly once; occurrences: {occurrences}"
            )
        return self.update(self._content.replace(old_text, new_text, 1))

    def save(self, relative_path: Optional[str] = None) -> DocumentSnapshot:
        path = self._resolve(relative_path) if relative_path else self._path
        if path is None:
            raise ValueError("Specify a .bicep path before saving")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temporary_file:
                temporary_file.write(self._content)
            os.replace(temporary_name, path)
        except Exception:
            Path(temporary_name).unlink(missing_ok=True)
            raise
        self._path = path
        self._dirty = False
        return self.snapshot()

    def _resolve(self, relative_path: str) -> Path:
        if not relative_path:
            raise ValueError("Bicep path is required")
        path = (self.root / relative_path).resolve()
        try:
            path.relative_to(self.root)
        except ValueError as error:
            raise ValueError("The file must be inside the workspace") from error
        if path.suffix.lower() != ".bicep":
            raise ValueError("Only .bicep files can be modified")
        return path

    def _check_revision(self, revision: Optional[int]) -> None:
        if revision is not None and revision != self._revision:
            raise ValueError(
                f"Revision conflict: expected {revision}, current {self._revision}"
            )