"""Tests for file utility functions."""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from audiothek.file_utils import (
    FileOperationResult,
    ensure_directory_exists,
    compare_json_content,
    safe_write_json,
    set_file_modification_time,
    backup_file,
    restore_backup,
    get_file_size,
)


class TestFileOperationResult:
    """Test cases for FileOperationResult class."""

    def test_file_operation_result_initialization(self) -> None:
        """Test FileOperationResult initialization with all parameters."""
        result = FileOperationResult(
            success=True,
            message="Operation successful",
            file_path="/path/to/file.txt",
            backup_path="/path/to/backup.bak",
            content_length=1024
        )

        assert result.success is True
        assert result.message == "Operation successful"
        assert result.file_path == "/path/to/file.txt"
        assert result.backup_path == "/path/to/backup.bak"
        assert result.content_length == 1024

    def test_file_operation_result_minimal_parameters(self) -> None:
        """Test FileOperationResult initialization with minimal parameters."""
        result = FileOperationResult(
            success=False,
            message="Operation failed",
            file_path="/path/to/file.txt"
        )

        assert result.success is False
        assert result.message == "Operation failed"
        assert result.file_path == "/path/to/file.txt"
        assert result.backup_path is None
        assert result.content_length is None

    def test_file_operation_result_str_representation(self) -> None:
        """Test FileOperationResult string representation."""
        result = FileOperationResult(
            success=True,
            message="Success",
            file_path="/path/to/file.txt"
        )

        assert str(result) == "Success - /path/to/file.txt"


class TestEnsureDirectoryExists:
    """Test cases for ensure_directory_exists function."""

    def test_ensure_directory_exists_new_directory(self, tmp_path: Path) -> None:
        """Test ensure_directory_exists creates new directory."""
        mock_logger = Mock()
        new_dir = tmp_path / "new_directory"

        result = ensure_directory_exists(str(new_dir), mock_logger)

        assert result is True
        assert new_dir.exists()
        assert new_dir.is_dir()
        mock_logger.error.assert_not_called()

    def test_ensure_directory_exists_existing_directory(self, tmp_path: Path) -> None:
        """Test ensure_directory_exists handles existing directory."""
        mock_logger = Mock()
        existing_dir = tmp_path / "existing_directory"
        existing_dir.mkdir()

        result = ensure_directory_exists(str(existing_dir), mock_logger)

        assert result is True
        assert existing_dir.exists()
        mock_logger.error.assert_not_called()

    def test_ensure_directory_exists_nested_path(self, tmp_path: Path) -> None:
        """Test ensure_directory_exists creates nested directory structure."""
        mock_logger = Mock()
        nested_dir = tmp_path / "level1" / "level2" / "level3"

        result = ensure_directory_exists(str(nested_dir), mock_logger)

        assert result is True
        assert nested_dir.exists()
        assert nested_dir.is_dir()

    @patch('os.makedirs')
    def test_ensure_directory_exists_permission_error(self, mock_makedirs: Mock) -> None:
        """Test ensure_directory_exists handles permission errors."""
        mock_logger = Mock()
        mock_makedirs.side_effect = PermissionError("Permission denied")

        result = ensure_directory_exists("/restricted/path", mock_logger)

        assert result is False
        mock_logger.error.assert_called_once()

    @patch('os.makedirs')
    def test_ensure_directory_exists_os_error(self, mock_makedirs: Mock) -> None:
        """Test ensure_directory_exists handles other OS errors."""
        mock_logger = Mock()
        mock_makedirs.side_effect = OSError("Disk full")

        result = ensure_directory_exists("/full/disk/path", mock_logger)

        assert result is False
        mock_logger.error.assert_called_once()


class TestCompareJsonContent:
    """Test cases for compare_json_content function."""

    def test_compare_json_content_file_not_exists(self) -> None:
        """Test compare_json_content when file doesn't exist."""
        result = compare_json_content("/nonexistent/file.json", {"key": "value"})
        assert result is False

    def test_compare_json_content_matching_content(self, tmp_path: Path) -> None:
        """Test compare_json_content with matching content."""
        test_file = tmp_path / "test.json"
        test_data = {"key": "value", "number": 42}

        with open(test_file, 'w') as f:
            json.dump(test_data, f)

        result = compare_json_content(str(test_file), test_data)
        assert result is True

    def test_compare_json_content_different_content(self, tmp_path: Path) -> None:
        """Test compare_json_content with different content."""
        test_file = tmp_path / "test.json"
        file_data = {"key": "old_value", "number": 42}
        new_data = {"key": "new_value", "number": 42}

        with open(test_file, 'w') as f:
            json.dump(file_data, f)

        result = compare_json_content(str(test_file), new_data)
        assert result is False

    def test_compare_json_content_invalid_json(self, tmp_path: Path) -> None:
        """Test compare_json_content with invalid JSON file."""
        test_file = tmp_path / "invalid.json"

        with open(test_file, 'w') as f:
            f.write("{ invalid json content")

        result = compare_json_content(str(test_file), {"key": "value"})
        assert result is False

    def test_compare_json_content_complex_structure(self, tmp_path: Path) -> None:
        """Test compare_json_content with complex nested structure."""
        test_file = tmp_path / "complex.json"
        test_data = {
            "nested": {
                "array": [1, 2, 3],
                "object": {"a": "b", "c": "d"}
            },
            "simple": "value"
        }

        with open(test_file, 'w') as f:
            json.dump(test_data, f)

        # Same data should match
        result = compare_json_content(str(test_file), test_data)
        assert result is True

        # Different data should not match
        different_data = test_data.copy()
        different_data["nested"]["array"][0] = 999
        result = compare_json_content(str(test_file), different_data)
        assert result is False

    @patch('builtins.open')
    def test_compare_json_content_file_read_error(self, mock_open: Mock) -> None:
        """Test compare_json_content handles file read errors."""
        mock_open.side_effect = OSError("Permission denied")

        result = compare_json_content("/restricted/file.json", {"key": "value"})
        assert result is False


class TestSafeWriteJson:
    """Test cases for safe_write_json function."""

    def test_safe_write_json_success(self, tmp_path: Path) -> None:
        """Test safe_write_json successful write."""
        mock_logger = Mock()
        test_file = tmp_path / "test.json"
        test_data = {"key": "value", "number": 42}

        result = safe_write_json(str(test_file), test_data, mock_logger)

        assert result.success is True
        assert result.message == "Successfully wrote JSON data"
        assert result.file_path == str(test_file)
        assert result.backup_path is None
        assert result.content_length is None

        # Verify file was written correctly
        with open(test_file) as f:
            loaded_data = json.load(f)
        assert loaded_data == test_data

        mock_logger.error.assert_not_called()

    def test_safe_write_json_with_complex_data(self, tmp_path: Path) -> None:
        """Test safe_write_json with complex nested data."""
        mock_logger = Mock()
        test_file = tmp_path / "complex.json"
        test_data = {
            "nested": {"array": [1, 2, 3], "object": {"a": "b"}},
            "string": "value",
            "number": 42.5,
            "boolean": True,
            "null": None
        }

        result = safe_write_json(str(test_file), test_data, mock_logger)

        assert result.success is True

        # Verify file content
        with open(test_file) as f:
            loaded_data = json.load(f)
        assert loaded_data == test_data

    @patch('builtins.open')
    def test_safe_write_json_permission_error(self, mock_open: Mock) -> None:
        """Test safe_write_json handles permission errors."""
        mock_logger = Mock()
        mock_open.side_effect = PermissionError("Permission denied")

        result = safe_write_json("/restricted/file.json", {"key": "value"}, mock_logger)

        assert result.success is False
        assert "Failed to write JSON data" in result.message
        assert result.file_path == "/restricted/file.json"
        mock_logger.error.assert_called_once()

    @patch('json.dump')
    def test_safe_write_json_json_error(self, mock_dump: Mock) -> None:
        """Test safe_write_json handles JSON serialization errors."""
        mock_logger = Mock()
        mock_dump.side_effect = TypeError("Object not serializable")

        # Use a non-serializable object
        non_serializable = {"function": lambda x: x}

        result = safe_write_json("/test/file.json", non_serializable, mock_logger)

        assert result.success is False
        assert "Failed to write JSON data" in result.message
        mock_logger.error.assert_called_once()

    @patch('filelock.FileLock')
    def test_safe_write_json_lock_error(self, mock_filelock: Mock) -> None:
        """Test safe_write_json handles file locking errors."""
        mock_logger = Mock()
        mock_lock = Mock()
        mock_lock.__enter__ = Mock(side_effect=OSError("Lock error"))
        mock_lock.__exit__ = Mock(return_value=None)
        mock_filelock.return_value = mock_lock

        result = safe_write_json("/test/file.json", {"key": "value"}, mock_logger)

        assert result.success is False
        assert "Failed to write JSON data" in result.message
        mock_logger.error.assert_called_once()

    def test_safe_write_json_cleanup_lock_file(self, tmp_path: Path) -> None:
        """Test safe_write_json cleans up lock file even on error."""
        mock_logger = Mock()
        test_file = tmp_path / "test.json"
        lock_file = tmp_path / "test.json.lock"

        # Create a lock file that should be cleaned up
        lock_file.write_text("lock")

        # Mock open to raise an exception
        with patch('builtins.open', side_effect=OSError("Write error")):
            result = safe_write_json(str(test_file), {"key": "value"}, mock_logger)

        assert result.success is False
        # Lock file should be cleaned up
        assert not lock_file.exists()


class TestSetFileModificationTime:
    """Test cases for set_file_modification_time function."""

    def test_set_file_modification_time_utc_timestamp(self, tmp_path: Path) -> None:
        """Test set_file_modification_time with UTC timestamp."""
        mock_logger = Mock()
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        publish_date = "2023-12-01T10:00:00.000Z"

        result = set_file_modification_time(str(test_file), publish_date, mock_logger)

        assert result is True
        mock_logger.debug.assert_called_once()
        mock_logger.warning.assert_not_called()

    def test_set_file_modification_time_utc_timestamp_without_milliseconds(self, tmp_path: Path) -> None:
        """Test set_file_modification_time with UTC timestamp without milliseconds."""
        mock_logger = Mock()
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        publish_date = "2023-12-01T10:00:00Z"

        result = set_file_modification_time(str(test_file), publish_date, mock_logger)

        assert result is True

    def test_set_file_modification_time_local_timestamp(self, tmp_path: Path) -> None:
        """Test set_file_modification_time with local timestamp."""
        mock_logger = Mock()
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        publish_date = "2023-12-01T10:00:00"

        result = set_file_modification_time(str(test_file), publish_date, mock_logger)

        assert result is True

    def test_set_file_modification_time_invalid_date_format(self, tmp_path: Path) -> None:
        """Test set_file_modification_time with invalid date format."""
        mock_logger = Mock()
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        publish_date = "invalid-date"

        result = set_file_modification_time(str(test_file), publish_date, mock_logger)

        assert result is False
        mock_logger.warning.assert_called_once()

    @patch('os.utime')
    def test_set_file_modification_time_utime_error(self, mock_utime: Mock, tmp_path: Path) -> None:
        """Test set_file_modification_time handles utime errors."""
        mock_logger = Mock()
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        mock_utime.side_effect = OSError("Permission denied")

        result = set_file_modification_time(str(test_file), "2023-12-01T10:00:00Z", mock_logger)

        assert result is False
        mock_logger.warning.assert_called_once()

    def test_set_file_modification_time_nonexistent_file(self) -> None:
        """Test set_file_modification_time with nonexistent file."""
        mock_logger = Mock()

        result = set_file_modification_time("/nonexistent/file.txt", "2023-12-01T10:00:00Z", mock_logger)

        assert result is False
        mock_logger.warning.assert_called_once()


class TestBackupFile:
    """Test cases for backup_file function."""

    def test_backup_file_success(self, tmp_path: Path) -> None:
        """Test backup_file successful backup."""
        mock_logger = Mock()
        original_file = tmp_path / "original.txt"
        original_file.write_text("original content")

        success, backup_path = backup_file(str(original_file), mock_logger)

        assert success is True
        assert backup_path is not None
        assert backup_path == str(original_file) + ".bak"
        assert not original_file.exists()  # Original should be renamed
        assert Path(backup_path).exists()
        assert Path(backup_path).read_text() == "original content"
        mock_logger.info.assert_called_once()

    def test_backup_file_nonexistent_file(self) -> None:
        """Test backup_file with nonexistent file."""
        mock_logger = Mock()

        success, backup_path = backup_file("/nonexistent/file.txt", mock_logger)

        assert success is False
        assert backup_path is None
        mock_logger.info.assert_not_called()

    @patch('os.rename')
    def test_backup_file_permission_error(self, mock_rename: Mock, tmp_path: Path) -> None:
        """Test backup_file handles permission errors."""
        mock_logger = Mock()
        original_file = tmp_path / "original.txt"
        original_file.write_text("content")

        mock_rename.side_effect = PermissionError("Permission denied")

        success, backup_path = backup_file(str(original_file), mock_logger)

        assert success is False
        assert backup_path is None
        mock_logger.error.assert_called_once()

    @patch('os.rename')
    def test_backup_file_os_error(self, mock_rename: Mock, tmp_path: Path) -> None:
        """Test backup_file handles other OS errors."""
        mock_logger = Mock()
        original_file = tmp_path / "original.txt"
        original_file.write_text("content")

        mock_rename.side_effect = OSError("Disk full")

        success, backup_path = backup_file(str(original_file), mock_logger)

        assert success is False
        assert backup_path is None
        mock_logger.error.assert_called_once()


class TestRestoreBackup:
    """Test cases for restore_backup function."""

    def test_restore_backup_success(self, tmp_path: Path) -> None:
        """Test restore_backup successful restore."""
        mock_logger = Mock()
        backup_file = tmp_path / "original.txt.bak"
        backup_file.write_text("backup content")
        original_path = tmp_path / "original.txt"

        result = restore_backup(str(backup_file), str(original_path), mock_logger)

        assert result is True
        assert not backup_file.exists()  # Backup should be renamed
        assert original_path.exists()
        assert original_path.read_text() == "backup content"
        mock_logger.info.assert_called_once()

    def test_restore_backup_nonexistent_backup(self) -> None:
        """Test restore_backup with nonexistent backup file."""
        mock_logger = Mock()

        result = restore_backup("/nonexistent/backup.bak", "/path/original.txt", mock_logger)

        assert result is False
        mock_logger.info.assert_not_called()

    @patch('os.rename')
    def test_restore_backup_permission_error(self, mock_rename: Mock, tmp_path: Path) -> None:
        """Test restore_backup handles permission errors."""
        mock_logger = Mock()
        backup_file = tmp_path / "backup.bak"
        backup_file.write_text("content")

        mock_rename.side_effect = PermissionError("Permission denied")

        result = restore_backup(str(backup_file), "/path/original.txt", mock_logger)

        assert result is False
        mock_logger.error.assert_called_once()

    @patch('os.rename')
    def test_restore_backup_os_error(self, mock_rename: Mock, tmp_path: Path) -> None:
        """Test restore_backup handles other OS errors."""
        mock_logger = Mock()
        backup_file = tmp_path / "backup.bak"
        backup_file.write_text("content")

        mock_rename.side_effect = OSError("Disk full")

        result = restore_backup(str(backup_file), "/path/original.txt", mock_logger)

        assert result is False
        mock_logger.error.assert_called_once()


class TestGetFileSize:
    """Test cases for get_file_size function."""

    def test_get_file_size_existing_file(self, tmp_path: Path) -> None:
        """Test get_file_size with existing file."""
        test_file = tmp_path / "test.txt"
        content = "This is test content for file size testing"
        test_file.write_text(content)

        size = get_file_size(str(test_file))

        assert size == len(content.encode('utf-8'))

    def test_get_file_size_empty_file(self, tmp_path: Path) -> None:
        """Test get_file_size with empty file."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        size = get_file_size(str(test_file))

        assert size == 0

    def test_get_file_size_nonexistent_file(self) -> None:
        """Test get_file_size with nonexistent file."""
        size = get_file_size("/nonexistent/file.txt")

        assert size is None

    @patch('os.path.getsize')
    def test_get_file_size_os_error(self, mock_getsize: Mock) -> None:
        """Test get_file_size handles OS errors."""
        mock_getsize.side_effect = OSError("Permission denied")

        size = get_file_size("/restricted/file.txt")

        assert size is None

    def test_get_file_size_binary_file(self, tmp_path: Path) -> None:
        """Test get_file_size with binary file."""
        test_file = tmp_path / "binary.bin"
        binary_content = b'\x00\x01\x02\x03\x04\x05'
        test_file.write_bytes(binary_content)

        size = get_file_size(str(test_file))

        assert size == len(binary_content)
