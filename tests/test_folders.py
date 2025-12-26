"""Tests for folder management functionality."""

import json
import logging
import os
from pathlib import Path
from typing import Any

import pytest

from audiothek import AudiothekDownloader
from audiothek.utils import migrate_folders


def test_update_all_folders_numeric_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test update_all_folders with numeric folder names"""
    # Create test folders with numeric names
    (tmp_path / "123456").mkdir()
    (tmp_path / "789012").mkdir()
    (tmp_path / "non_numeric_folder").mkdir()

    calls = []

    def _mock_determine_resource_type_from_id(self, folder_id):
        if folder_id in ["123456", "789012"]:
            return "program", folder_id
        return None

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", _mock_determine_resource_type_from_id)
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

    def _mock_determine_resource_type_from_id(self, folder_id):
        if folder_id in ["123456", "789012", "999999"]:
            return "program", folder_id
        return None

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", _mock_determine_resource_type_from_id)
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

    def _mock_determine_resource_type_from_id(self, folder_id):
        if folder_id == "123456":
            return "program", folder_id
        return None

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    with monkeypatch.context():
        downloader = AudiothekDownloader()
        downloader.update_all_folders(str(tmp_path))

    # Should have called download_collection only for folder that returned a resource type
    assert len(calls) == 1
    assert calls[0] == ("download_collection", "123456", str(tmp_path), False)


def test_update_all_folders_exception_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test update_all_folders handles exceptions gracefully"""
    # Create test folder
    (tmp_path / "123456").mkdir()

    calls = []

    def _mock_determine_resource_type_from_id(self, folder_id):
        return "program", folder_id

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))
        raise Exception("Download failed")

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", _mock_determine_resource_type_from_id)
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

    def _mock_determine_resource_type_from_id(self, folder_id):
        return "program", folder_id

    def _mock_get_program_title(self, resource_id, resource_type):
        return "Test Program"

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekDownloader, "_get_program_title", _mock_get_program_title)

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

    def _mock_determine_resource_type_from_id(self, folder_id):
        return "program", folder_id

    def _mock_get_program_title(self, resource_id, resource_type):
        return "Test Program"

    # Mock os.rename to raise exception
    def _mock_rename(old_path, new_path):
        raise OSError("Permission denied")

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekDownloader, "_get_program_title", _mock_get_program_title)
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
    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", lambda self, rid: None)

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

    def _mock_get_program_title(self, resource_id, resource_type):
        return None

    monkeypatch.setattr(AudiothekDownloader, "_get_program_title", _mock_get_program_title)

    with caplog.at_level("WARNING"):
        downloader = AudiothekDownloader()
        migrate_folders(str(tmp_path), downloader, downloader.logger)

    # Should have logged warning
    assert any("Could not get title for folder" in r.message and "123456" in r.message for r in caplog.records)

    # Folder should still exist (no migration)
    assert (tmp_path / "123456").exists()
