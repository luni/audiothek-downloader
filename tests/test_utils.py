"""Tests for utility functions."""

import pytest

from audiothek import sanitize_folder_name


def test_sanitize_folder_name_basic() -> None:
    """Test basic folder name sanitization."""
    assert sanitize_folder_name("Test Program") == "Test Program"
    assert sanitize_folder_name("Simple") == "Simple"


def test_sanitize_folder_name_special_characters() -> None:
    """Test sanitization of special characters."""
    assert sanitize_folder_name("Test/Program") == "Test_Program"
    assert sanitize_folder_name("Test\\Program") == "Test_Program"
    assert sanitize_folder_name("Test:Program") == "Test_Program"
    assert sanitize_folder_name("Test*Program") == "Test_Program"
    assert sanitize_folder_name("Test?Program") == "Test_Program"
    assert sanitize_folder_name('Test"Program') == "Test_Program"
    assert sanitize_folder_name("Test<Program>") == "Test_Program_"
    assert sanitize_folder_name("Test|Program") == "Test_Program"


def test_sanitize_folder_name_multiple_special_chars() -> None:
    """Test sanitization of multiple special characters."""
    assert sanitize_folder_name("Test/Program\\Episode") == "Test_Program_Episode"
    assert sanitize_folder_name("Test:Program*Episode?Show") == "Test_Program_Episode_Show"


def test_sanitize_folder_name_whitespace() -> None:
    """Test sanitization of whitespace."""
    assert sanitize_folder_name(" Test Program ") == "Test Program"
    assert sanitize_folder_name("Test\tProgram") == "Test Program"  # Tab becomes space
    assert sanitize_folder_name("Test\nProgram") == "Test Program"  # Newline becomes space


def test_sanitize_folder_name_empty_and_none() -> None:
    """Test sanitization of empty and None inputs."""
    assert sanitize_folder_name("") == ""
    assert sanitize_folder_name("   ") == ""


def test_sanitize_folder_name_unicode() -> None:
    """Test sanitization of unicode characters."""
    assert sanitize_folder_name("Tëst Prögram") == "Tëst Prögram"  # Unicode chars preserved
    assert sanitize_folder_name("测试节目") == "测试节目"  # Chinese chars preserved


def test_sanitize_folder_name_very_long() -> None:
    """Test sanitization of very long names."""
    long_name = "A" * 300
    result = sanitize_folder_name(long_name)
    # Should truncate to reasonable length
    assert len(result) <= 255


def test_sanitize_folder_name_edge_cases() -> None:
    """Test edge cases for folder name sanitization."""
    # Only special characters
    assert sanitize_folder_name("/\\:*?\"<>|") == "_________"

    # Mixed with numbers
    assert sanitize_folder_name("Test123/Program456") == "Test123_Program456"

    # Leading/trailing special chars
    assert sanitize_folder_name("/Test Program/") == "_Test Program_"
    assert sanitize_folder_name("\\Test Program\\") == "_Test Program_"


def test_audiothek_downloader_initialization() -> None:
    """Test AudiothekDownloader initialization."""
    from audiothek import AudiothekDownloader

    # Test with default folder
    downloader = AudiothekDownloader()
    assert downloader.base_folder == "./output"

    # Test with custom folder
    custom_folder = "/custom/output"
    downloader = AudiothekDownloader(custom_folder)
    assert downloader.base_folder == custom_folder

    # Test that client session is created
    assert downloader.client._session is not None
