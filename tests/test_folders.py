"""Tests for folder management functionality."""

import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from audiothek import AudiothekDownloader, DownloadResult, AudiothekClient
from audiothek.models import ResourceInfo
from audiothek.utils import cleanup_files, migrate_folders, rename_files


def test_program_folder_name_sanitizes_whitespace_only_title() -> None:
    """Whitespace-only titles must not produce trailing spaces in folder names."""
    assert AudiothekDownloader._program_folder_name("ps1", "   ") == "ps1"
    assert AudiothekDownloader._program_folder_name("ps1", "\t\n") == "ps1"
    assert AudiothekDownloader._program_folder_name("ps1", "A Normal Title") == "ps1 A Normal Title"


def test_update_all_folders_numeric_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test update_all_folders with numeric folder names"""
    # Create test folders with numeric names
    (tmp_path / "123456").mkdir()
    (tmp_path / "789012").mkdir()
    (tmp_path / "non_numeric_folder").mkdir()

    calls = []

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))
        return DownloadResult(success=True, message=f"Downloaded {resource_id}")

    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    with monkeypatch.context():
        downloader = AudiothekDownloader()
        downloader.update_all_folders(str(tmp_path))

    # Should have called download_collection for both numeric folders (order doesn't matter)
    assert len(calls) == 2

    # Check that both expected calls are present, regardless of order
    expected_calls = [
        ("download_collection", "123456", str(tmp_path), False),
        ("download_collection", "789012", str(tmp_path), False)
    ]

    for expected_call in expected_calls:
        assert expected_call in calls


def test_update_all_folders_mixed_folder_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test update_all_folders with mixed folder names (new format and legacy numeric)"""
    # Create test folders with realistic names
    (tmp_path / "123456").mkdir()
    (tmp_path / "789012 Show Title").mkdir()
    (tmp_path / "999999 Another Show").mkdir()
    (tmp_path / "non_numeric").mkdir()

    calls = []

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))
        return DownloadResult(success=True, message=f"Downloaded {resource_id}")

    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    with monkeypatch.context():
        downloader = AudiothekDownloader()
        downloader.update_all_folders(str(tmp_path))

    # Should have called download_collection for all three folders (order doesn't matter)
    assert len(calls) == 3

    # Check that all expected calls are present, regardless of order
    expected_calls = [
        ("download_collection", "123456", str(tmp_path), False),
        ("download_collection", "789012", str(tmp_path), False),
        ("download_collection", "999999", str(tmp_path), False)
    ]

    for expected_call in expected_calls:
        assert expected_call in calls


def test_update_all_folders_skips_non_numeric_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test update_all_folders skips folders without numeric IDs"""
    # Create test folders
    (tmp_path / "123456").mkdir()
    (tmp_path / "789012").mkdir()
    (tmp_path / "no_numeric").mkdir()

    calls = []

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))
        return DownloadResult(success=True, message=f"Downloaded {resource_id}")

    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    with monkeypatch.context():
        downloader = AudiothekDownloader()
        downloader.update_all_folders(str(tmp_path))

    # Should have called download_collection for numeric folders
    assert len(calls) == 2

    expected_ids = ["123456", "789012"]
    called_ids = [c[1] for c in calls]
    for eid in expected_ids:
        assert eid in called_ids


def test_update_all_folders_exception_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test update_all_folders handles exceptions gracefully"""
    # Create test folder
    (tmp_path / "123456").mkdir()

    calls = []

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))
        raise Exception("Download failed")

    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    with monkeypatch.context():
        downloader = AudiothekDownloader()
        # Should not raise exception, should handle it gracefully
        downloader.update_all_folders(str(tmp_path))

    # Should have attempted the download
    assert len(calls) == 1


def test_migrate_folders_numeric_to_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test migrate_folders converts numeric folders to named folders"""
    # Create numeric folder with metadata
    (tmp_path / "123456").mkdir()
    metadata = {"id": "urn:ard:episode:test1", "programSet": {"id": "ps1", "title": "Test Program"}}
    (tmp_path / "123456" / "metadata.json").write_text(json.dumps(metadata))
    (tmp_path / "123456" / "test.mp3").write_bytes(b"audio content")

    # Mock as static method to match the original class method behavior or just accept self if bound
    # Since determine_resource_type_from_id is called on instance, if we put a plain function on class, it binds.
    # So we accept 'self' (ignored) and the argument.
    def _mock_determine_resource_type_from_id(self, resource_id):
        return ResourceInfo("program", resource_id)

    def _mock_get_title(self, resource_id, resource_type):
        return "Test Program"

    monkeypatch.setattr(AudiothekClient, "determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekClient, "get_title", _mock_get_title)

    downloader = AudiothekDownloader()
    migrate_folders(str(tmp_path), downloader, downloader.logger)

    # Should have created named folder
    named_folder = tmp_path / "123456 Test Program"
    assert named_folder.exists()

    # Should have moved files
    assert (named_folder / "metadata.json").exists()
    assert (named_folder / "test.mp3").exists()

    # Original folder should be gone
    assert not (tmp_path / "123456").exists()


def test_migrate_folders_already_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test migrate_folders skips already named folders"""
    # Create named folder with metadata
    (tmp_path / "ps1 Test Program").mkdir()
    metadata = {"id": "urn:ard:episode:test1", "programSet": {"id": "ps1", "title": "Test Program"}}
    (tmp_path / "ps1 Test Program" / "metadata.json").write_text(json.dumps(metadata))

    downloader = AudiothekDownloader()
    migrate_folders(str(tmp_path), downloader, downloader.logger)

    # Folder should still exist
    assert (tmp_path / "ps1 Test Program").exists()


def test_migrate_folders_no_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test migrate_folders skips folders without metadata"""
    # Create numeric folder without metadata
    (tmp_path / "123456").mkdir()
    (tmp_path / "123456" / "test.mp3").write_bytes(b"audio content")

    downloader = AudiothekDownloader()
    migrate_folders(str(tmp_path), downloader, downloader.logger)

    # Folder should still exist (no migration)
    assert (tmp_path / "123456").exists()


def test_migrate_folders_exception_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test migrate_folders handles exceptions gracefully"""
    # Create numeric folder with metadata
    (tmp_path / "123456").mkdir()
    metadata = {"id": "urn:ard:episode:test1", "programSet": {"id": "ps1", "title": "Test Program"}}
    (tmp_path / "123456" / "metadata.json").write_text(json.dumps(metadata))

    def _mock_determine_resource_type_from_id(self, resource_id):
        return ResourceInfo("program", resource_id)

    def _mock_get_title(self, resource_id, resource_type):
        return "Test Program"

    # Mock os.rename to raise exception
    def _mock_rename(old_path, new_path):
        raise OSError("Permission denied")

    monkeypatch.setattr(AudiothekClient, "determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekClient, "get_title", _mock_get_title)
    monkeypatch.setattr("os.rename", _mock_rename)

    with caplog.at_level("ERROR"):
        downloader = AudiothekDownloader()
        migrate_folders(str(tmp_path), downloader, downloader.logger)

    # Should have logged error
    assert any("Failed to rename folder" in r.message and "123456" in r.message for r in caplog.records)

    # Original folder should still exist
    assert (tmp_path / "123456").exists()


def test_migrate_folders_resource_type_none_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test migrate_folders handles None resource_type gracefully"""
    # Create numeric folder with metadata
    (tmp_path / "123456").mkdir()
    metadata = {"id": "urn:ard:episode:test1", "programSet": {"id": "ps1", "title": "Test Program"}}
    (tmp_path / "123456" / "metadata.json").write_text(json.dumps(metadata))

    # Mock _determine_resource_type_from_id to return None
    def _mock_determine_resource_type_from_id(self, rid):
        return None

    monkeypatch.setattr(AudiothekClient, "determine_resource_type_from_id", _mock_determine_resource_type_from_id)

    downloader = AudiothekDownloader()
    migrate_folders(str(tmp_path), downloader, downloader.logger)

    # Folder should still exist (no migration)
    assert (tmp_path / "123456").exists()


def test_migrate_folders_logs_warning_when_no_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test migrate_folders logs warning when programSet has no title"""
    # Create numeric folder with metadata (no title)
    (tmp_path / "123456").mkdir()
    metadata = {"id": "urn:ard:episode:test1", "programSet": {"id": "ps1"}}
    (tmp_path / "123456" / "metadata.json").write_text(json.dumps(metadata))

    def _mock_determine_resource_type_from_id(self, resource_id):
        return ResourceInfo("program", resource_id)

    def _mock_get_title(self, resource_id, resource_type):
        return None

    monkeypatch.setattr(AudiothekClient, "determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekClient, "get_title", _mock_get_title)

    with caplog.at_level("WARNING"):
        downloader = AudiothekDownloader()
        migrate_folders(str(tmp_path), downloader, downloader.logger)

    # Should have logged warning
    assert any("Could not get title for folder" in r.message and "123456" in r.message for r in caplog.records)

    # Folder should still exist (no migration)
    assert (tmp_path / "123456").exists()


def test_migrate_folders_skips_whitespace_only_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test migrate_folders does not rename when title is only whitespace."""
    (tmp_path / "123456").mkdir()
    metadata = {"id": "urn:ard:episode:test1", "programSet": {"id": "ps1"}}
    (tmp_path / "123456" / "metadata.json").write_text(json.dumps(metadata))

    def _mock_determine_resource_type_from_id(self, resource_id):
        return ResourceInfo("program", resource_id)

    def _mock_get_title(self, resource_id, resource_type):
        return "   "

    monkeypatch.setattr(AudiothekClient, "determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekClient, "get_title", _mock_get_title)

    with caplog.at_level("WARNING"):
        downloader = AudiothekDownloader()
        migrate_folders(str(tmp_path), downloader, downloader.logger)

    assert any("Could not get title for folder" in r.message and "123456" in r.message for r in caplog.records)
    assert (tmp_path / "123456").exists()


def test_program_folder_name_sanitizes_id() -> None:
    """Program set IDs (especially URNs) must be sanitized for the filesystem."""
    assert AudiothekDownloader._program_folder_name("urn:ard:show:abc", "Title") == "urn_ard_show_abc Title"
    assert AudiothekDownloader._program_folder_name("../../../etc", "Title") == "_.._.._etc Title"
    assert AudiothekDownloader._program_folder_name("/etc/passwd", "Title") == "_etc_passwd Title"


def test_program_folder_name_handles_blank_id() -> None:
    """A blank or all-dots ID must fall back to a safe default."""
    assert AudiothekDownloader._program_folder_name("..", "") == "program_set"
    assert AudiothekDownloader._program_folder_name("", "") == "program_set"


def test_update_all_folders_partial_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """update_all_folders must report failure when one folder update fails."""
    (tmp_path / "123456").mkdir()
    (tmp_path / "789012").mkdir()

    def _mock_download_from_id(self, resource_id, folder):
        if resource_id == "123456":
            return DownloadResult(success=False, message="failed")
        return DownloadResult(success=True, message="ok")

    monkeypatch.setattr(AudiothekDownloader, "download_from_id", _mock_download_from_id)

    downloader = AudiothekDownloader()
    result = downloader.update_all_folders(str(tmp_path))

    assert isinstance(result, DownloadResult)
    assert result.success is False
    assert "Updated: 1, Errors: 1" in result.message


def test_update_all_folders_sanitized_urn_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """update_all_folders resolves sanitized URN folders using metadata."""
    folder = tmp_path / "urn_ard_show_xyz Program"
    folder.mkdir()
    metadata = {"id": "urn:ard:show:xyz", "title": "Program"}
    (folder / "urn_ard_show_xyz.json").write_text(json.dumps(metadata))

    calls = []

    def _mock_download_from_id(self, resource_id, folder):
        calls.append(resource_id)
        return DownloadResult(success=True, message="ok")

    monkeypatch.setattr(AudiothekDownloader, "download_from_id", _mock_download_from_id)

    downloader = AudiothekDownloader()
    result = downloader.update_all_folders(str(tmp_path))

    assert result.success is True
    assert calls == ["urn:ard:show:xyz"]


def test_migrate_folders_returns_false_on_rename_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """migrate_folders must return False when a rename operation fails."""
    (tmp_path / "123456").mkdir()

    def _mock_determine_resource_type_from_id(self, resource_id):
        return ResourceInfo("program", resource_id)

    def _mock_get_title(self, resource_id, resource_type):
        return "Test Program"

    def _mock_rename(old_path, new_path):
        raise OSError("Permission denied")

    monkeypatch.setattr(AudiothekClient, "determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekClient, "get_title", _mock_get_title)
    monkeypatch.setattr("os.rename", _mock_rename)

    downloader = AudiothekDownloader()
    assert migrate_folders(str(tmp_path), downloader, downloader.logger) is False
    assert (tmp_path / "123456").exists()


def test_migrate_folders_raw_urn_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """migrate_folders can migrate raw URN folders to sanitized names."""
    # Colons are valid in Linux filenames, so this simulates a pre-sanitization folder.
    folder = tmp_path / "urn:ard:show:xyz"
    folder.mkdir()

    def _mock_determine_resource_type_from_id(self, resource_id):
        return ResourceInfo("program", resource_id)

    def _mock_get_title(self, resource_id, resource_type):
        return "Test Program"

    monkeypatch.setattr(AudiothekClient, "determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekClient, "get_title", _mock_get_title)

    downloader = AudiothekDownloader()
    assert migrate_folders(str(tmp_path), downloader, downloader.logger) is True

    assert not folder.exists()
    assert (tmp_path / "urn_ard_show_xyz Test Program").exists()


def _episode_json(path: Path, node_id: str, title: str) -> None:
    path.write_text(json.dumps({
        "id": node_id,
        "title": title,
        "programSet": {"id": "urn:ard:show:s1", "title": "Show", "path": "/p"},
    }))


def test_rename_files_missing_folder(caplog: pytest.LogCaptureFixture) -> None:
    """rename_files fails cleanly for a nonexistent directory."""
    logger = logging.getLogger("test")
    assert rename_files(str("/nonexistent/path"), logger) is False


def test_rename_files_sanitizes_folder_names(tmp_path: Path) -> None:
    """Folders with invalid characters get renamed to sanitized names."""
    logger = logging.getLogger("test")
    bad_dir = tmp_path / "urn:ard:show:xyz My: Show"
    bad_dir.mkdir()
    (bad_dir / "ep.mp3").write_bytes(b"audio")

    assert rename_files(str(tmp_path), logger) is True

    assert not bad_dir.exists()
    assert (tmp_path / "urn_ard_show_xyz My_ Show" / "ep.mp3").exists()


def test_rename_files_metadata_anchors_episode_names(tmp_path: Path) -> None:
    """Episode files are renamed to the stem derived from their JSON metadata."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "urn_ard_show_s1 Show"
    program_dir.mkdir()
    _episode_json(program_dir / "weird_name.json", "urn:ard:episode:e1", "Real Title")
    (program_dir / "weird_name.mp3").write_bytes(b"audio")
    (program_dir / "weird_name.jpg").write_bytes(b"img")
    (program_dir / "weird_name_x1.jpg").write_bytes(b"img1x1")

    assert rename_files(str(tmp_path), logger) is True

    stem = "Real_Title_urn_ard_episode_e1"
    assert (program_dir / f"{stem}.mp3").exists()
    assert (program_dir / f"{stem}.json").exists()
    assert (program_dir / f"{stem}.jpg").exists()
    assert (program_dir / f"{stem}_x1.jpg").exists()
    assert not (program_dir / "weird_name.mp3").exists()


def test_rename_files_normalizes_invalid_orphan_files(tmp_path: Path) -> None:
    """Orphan files get renamed only when their name is actually invalid."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir()
    (program_dir / "bad:name.MP3").write_bytes(b"audio")
    (program_dir / "with spaces.m4a").write_bytes(b"audio")

    assert rename_files(str(tmp_path), logger) is True

    # Invalid characters and uppercase extension are fixed.
    assert (program_dir / "bad_name.mp3").exists()
    # Valid-but-foreign names are untouched; renaming cannot improve recognition.
    assert (program_dir / "with spaces.m4a").exists()


def test_rename_files_skips_transient_artifacts(tmp_path: Path) -> None:
    """Lock/backup/partial files are never renamed."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir()
    for name in ("ep.mp3.lock", "ep.mp3.bak", "ep.mp3.part", "ep.json.tmp", "ep.mp3-temp"):
        (program_dir / name).write_bytes(b"x")

    assert rename_files(str(tmp_path), logger) is True

    for name in ("ep.mp3.lock", "ep.mp3.bak", "ep.mp3.part", "ep.json.tmp", "ep.mp3-temp"):
        assert (program_dir / name).exists()


def test_rename_files_leaves_valid_names_alone(tmp_path: Path) -> None:
    """Files already matching the current scheme are untouched."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir()
    audio = program_dir / "Episode_Title_e1.mp3"
    audio.write_bytes(b"audio")
    _episode_json(program_dir / "Episode_Title_e1.json", "e1", "Episode Title")

    assert rename_files(str(tmp_path), logger) is True

    assert audio.exists()
    assert (program_dir / "Episode_Title_e1.json").exists()


def test_rename_files_skips_colliding_target(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A rename that would overwrite an existing file is skipped."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir()
    (program_dir / "foo:bar.mp3").write_bytes(b"new")
    existing = program_dir / "foo_bar.mp3"
    existing.write_bytes(b"existing")

    with caplog.at_level("WARNING"):
        assert rename_files(str(tmp_path), logger) is False

    assert existing.read_bytes() == b"existing"
    assert (program_dir / "foo:bar.mp3").exists()
    assert any("target already exists" in r.message for r in caplog.records)


def test_rename_files_dry_run_changes_nothing(tmp_path: Path) -> None:
    """Dry run logs renames without modifying the filesystem."""
    logger = logging.getLogger("test")
    bad_dir = tmp_path / "urn:ard:show:xyz"
    bad_dir.mkdir()
    (bad_dir / "bad:name.mp3").write_bytes(b"audio")

    assert rename_files(str(tmp_path), logger, dry_run=True) is True

    assert bad_dir.exists()
    assert (bad_dir / "bad:name.mp3").exists()


def test_rename_files_skips_hidden_files_and_dirs(tmp_path: Path) -> None:
    """Dotfiles and hidden directories must not be renamed."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir()
    (program_dir / ".DS_Store").write_bytes(b"junk")
    hidden_dir = tmp_path / ".hidden:dir"
    hidden_dir.mkdir()
    (hidden_dir / "we:ird.mp3").write_bytes(b"audio")

    assert rename_files(str(tmp_path), logger) is True

    assert (program_dir / ".DS_Store").exists()
    assert hidden_dir.exists()
    assert (hidden_dir / "we:ird.mp3").exists()


def test_migrate_folders_skips_when_target_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """migrate_folders must not clobber an existing folder."""
    folder = tmp_path / "urn:ard:show:xyz"
    folder.mkdir()
    target = tmp_path / "urn_ard_show_xyz Test Program"
    target.mkdir()
    (target / "keep.mp3").write_bytes(b"keep")

    def _mock_determine_resource_type_from_id(self, resource_id):
        return ResourceInfo("program", resource_id)

    def _mock_get_title(self, resource_id, resource_type):
        return "Test Program"

    monkeypatch.setattr(AudiothekClient, "determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekClient, "get_title", _mock_get_title)

    downloader = AudiothekDownloader()
    with caplog.at_level("WARNING"):
        assert migrate_folders(str(tmp_path), downloader, downloader.logger) is False

    assert folder.exists()
    assert (target / "keep.mp3").exists()
    assert any("target folder already exists" in r.message for r in caplog.records)


def test_cleanup_files_deletes_dead_artifacts(tmp_path: Path) -> None:
    """cleanup_files removes stale locks, parts and temp files."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir()
    content = program_dir / "ep.mp3"
    content.write_bytes(b"audio")
    for name in ("ep.mp3.lock", "ep.mp3.part", "ep.json.tmp", "ep.mp3-temp"):
        (program_dir / name).write_bytes(b"x")

    assert cleanup_files(str(tmp_path), logger) is True

    assert content.exists()
    for name in ("ep.mp3.lock", "ep.mp3.part", "ep.json.tmp", "ep.mp3-temp"):
        assert not (program_dir / name).exists()


def test_cleanup_files_keeps_bak_and_content(tmp_path: Path) -> None:
    """cleanup_files must not remove .bak backups or content files."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir()
    for name in ("ep.mp3", "ep.mp3.bak", "ep.json", "ep.jpg"):
        (program_dir / name).write_bytes(b"x")

    assert cleanup_files(str(tmp_path), logger) is True

    for name in ("ep.mp3", "ep.mp3.bak", "ep.json", "ep.jpg"):
        assert (program_dir / name).exists()


def test_cleanup_files_skips_hidden_entries(tmp_path: Path) -> None:
    """Dotfiles and hidden directories are never touched."""
    logger = logging.getLogger("test")
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir()
    (program_dir / ".hidden.lock").write_bytes(b"x")
    hidden_dir = tmp_path / ".hidden"
    hidden_dir.mkdir()
    (hidden_dir / "stale.lock").write_bytes(b"x")

    assert cleanup_files(str(tmp_path), logger) is True

    assert (program_dir / ".hidden.lock").exists()
    assert (hidden_dir / "stale.lock").exists()


def test_cleanup_files_dry_run_deletes_nothing(tmp_path: Path) -> None:
    """Dry run only logs deletions."""
    logger = logging.getLogger("test")
    stale = tmp_path / "ep.mp3.lock"
    stale.write_bytes(b"x")

    assert cleanup_files(str(tmp_path), logger, dry_run=True) is True
    assert stale.exists()


def test_cleanup_files_missing_folder() -> None:
    """cleanup_files fails cleanly for a nonexistent directory."""
    logger = logging.getLogger("test")
    assert cleanup_files("/nonexistent/path", logger) is False


def test_cleanup_files_delete_error_returns_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed deletion marks the run as failed but keeps going."""
    logger = logging.getLogger("test")
    (tmp_path / "a.lock").write_bytes(b"x")
    (tmp_path / "b.lock").write_bytes(b"x")

    real_remove = os.remove
    calls = []

    def _fail_on_a(path):
        calls.append(path)
        if path.endswith("a.lock"):
            raise OSError("denied")
        return real_remove(path)

    monkeypatch.setattr("os.remove", _fail_on_a)

    assert cleanup_files(str(tmp_path), logger) is False
    assert len(calls) == 2
    assert (tmp_path / "a.lock").exists()
    assert not (tmp_path / "b.lock").exists()
