from pathlib import Path

import pytest

from src.workspace import BicepWorkspace


def test_open_replace_and_atomic_save(tmp_path: Path):
    path = tmp_path / "main.bicep"
    path.write_text("resource old 'Example/type@2024-01-01' = {}", encoding="utf-8")
    workspace = BicepWorkspace(tmp_path)

    opened = workspace.open("main.bicep")
    changed = workspace.replace("resource old", "resource updated", opened.revision)
    saved = workspace.save()

    assert changed.dirty is True
    assert saved.dirty is False
    assert "resource updated" in path.read_text(encoding="utf-8")


def test_rejects_path_traversal_and_non_bicep_files(tmp_path: Path):
    workspace = BicepWorkspace(tmp_path)

    with pytest.raises(ValueError, match="workspace"):
        workspace.open("../outside.bicep")
    with pytest.raises(ValueError, match="Only .bicep files"):
        workspace.save("main.json")


def test_rejects_stale_or_ambiguous_replacements(tmp_path: Path):
    workspace = BicepWorkspace(tmp_path)
    snapshot = workspace.new("same same")

    with pytest.raises(ValueError, match="occurrences: 2"):
        workspace.replace("same", "new", snapshot.revision)
    with pytest.raises(ValueError, match="Revision conflict"):
        workspace.update("new", snapshot.revision - 1)