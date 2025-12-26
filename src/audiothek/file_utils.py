"""File utility functions for the audiothek-downloader."""

import json
import logging
import os
from datetime import datetime
from typing import Any, TypeVar

import filelock

T = TypeVar("T")


class FileOperationResult:
    """Result of a file operation."""

    def __init__(self, success: bool, message: str, file_path: str, backup_path: str | None = None, content_length: int | None = None) -> None:
        """Initialize the file operation result.

        Args:
            success: Whether the operation was successful
            message: Message describing the result
            file_path: Path to the file that was operated on
            backup_path: Path to the backup file if one was created
            content_length: Length of the content if applicable

        """
        self.success = success
        self.message = message
        self.file_path = file_path
        self.backup_path = backup_path
        self.content_length = content_length

    def __str__(self) -> str:
        """Return a string representation of the result."""
        return f"{self.message} - {self.file_path}"


def ensure_directory_exists(path: str, logger: logging.Logger) -> bool:
    """Create directory if it doesn't exist.

    Args:
        path: Directory path to create
        logger: Logger instance for logging messages

    Returns:
        True if directory exists or was created, False otherwise

    """
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError as e:
        logger.error("Couldn't create directory %s: %s", path, e)
        return False


def compare_json_content(file_path: str, new_data: dict[str, Any]) -> bool:
    """Check if JSON file content matches new data.

    Args:
        file_path: Path to the JSON file
        new_data: New data to compare with

    Returns:
        True if file exists and content matches, False otherwise

    """
    if not os.path.exists(file_path):
        return False

    try:
        with open(file_path) as f:
            existing_data = json.load(f)
        return existing_data == new_data
    except (json.JSONDecodeError, OSError):
        # If file is corrupted or can't be read, don't skip
        return False


def safe_write_json(file_path: str, data: dict[str, Any], logger: logging.Logger) -> FileOperationResult:
    """Write JSON data with file locking to prevent corruption.

    Args:
        file_path: Path to the JSON file
        data: Data to write
        logger: Logger instance for logging messages

    Returns:
        FileOperationResult with operation result

    """
    lock_path = f"{file_path}.lock"
    lock = filelock.FileLock(lock_path)

    try:
        with lock:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=4)
        return FileOperationResult(success=True, message="Successfully wrote JSON data", file_path=file_path)
    except Exception as e:
        logger.error("Failed to write JSON data to %s: %s", file_path, e)
        return FileOperationResult(success=False, message=f"Failed to write JSON data: {str(e)}", file_path=file_path)
    finally:
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except OSError:
                pass


def set_file_modification_time(file_path: str, publish_date: str, logger: logging.Logger) -> bool:
    """Set file modification time based on publish date.

    Args:
        file_path: Path to the file to modify
        publish_date: Publish date string from the API
        logger: Logger instance for logging messages

    Returns:
        True if successful, False otherwise

    """
    try:
        # Parse the publish date - ARD Audiothek typically uses ISO 8601 format
        # Example: "2023-12-01T10:00:00.000Z" or "2023-12-01T10:00:00Z"
        if publish_date.endswith("Z"):
            # Handle UTC timestamp
            dt = datetime.fromisoformat(publish_date.replace("Z", "+00:00"))
        else:
            # Handle timestamp without timezone info
            dt = datetime.fromisoformat(publish_date)

        # Convert to timestamp and set file modification time
        timestamp = dt.timestamp()
        os.utime(file_path, (timestamp, timestamp))
        logger.debug("Set file modification time for %s to %s", file_path, publish_date)
        return True
    except (ValueError, OSError) as e:
        logger.warning("Failed to set file modification time for %s: %s", file_path, e)
        return False


def backup_file(file_path: str, logger: logging.Logger) -> tuple[bool, str | None]:
    """Create a backup of a file.

    Args:
        file_path: Path to the file to back up
        logger: Logger instance for logging messages

    Returns:
        Tuple of (success, backup_path)

    """
    if not os.path.exists(file_path):
        return False, None

    backup_path = f"{file_path}.bak"
    try:
        os.rename(file_path, backup_path)
        logger.info("Backed up file to: %s", backup_path)
        return True, backup_path
    except OSError as e:
        logger.error("Failed to backup file %s: %s", file_path, e)
        return False, None


def restore_backup(backup_path: str, original_path: str, logger: logging.Logger) -> bool:
    """Restore a file from backup.

    Args:
        backup_path: Path to the backup file
        original_path: Path to restore to
        logger: Logger instance for logging messages

    Returns:
        True if successful, False otherwise

    """
    if not os.path.exists(backup_path):
        return False

    try:
        os.rename(backup_path, original_path)
        logger.info("Restored file from backup: %s", original_path)
        return True
    except OSError as e:
        logger.error("Failed to restore backup file %s: %s", backup_path, e)
        return False


def get_file_size(file_path: str) -> int | None:
    """Get the size of a file.

    Args:
        file_path: Path to the file

    Returns:
        File size in bytes, or None if file doesn't exist

    """
    try:
        return os.path.getsize(file_path)
    except OSError:
        return None
