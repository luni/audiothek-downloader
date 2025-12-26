"""Tests for metadata and collection functionality."""

import json
from pathlib import Path
from typing import Any

import pytest
import requests

from audiothek import AudiothekClient, AudiothekDownloader
from tests.conftest import MockResponse


def test_get_episode_title_api_response_handling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_episode_title with various API response scenarios."""
    client = AudiothekClient()

    # Test when API response has no data
    def _mock_requests_get_no_data(self, *args, **kwargs):
        class MockResponse:
            def json(self):
                return {"data": {}}
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_requests_get_no_data)

    result = client.get_episode_title("test_id")
    assert result is None


def test_get_program_set_title_no_items(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_program_set_title when response has no items."""
    client = AudiothekClient()

    def _mock_requests_get_no_items(self, *args, **kwargs):
        class MockResponse:
            def json(self):
                return {"data": {"result": {}}}
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_requests_get_no_items)

    result = client.get_program_set_title("test_id")
    assert result is None


def test_get_program_set_title_empty_nodes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_program_set_title when nodes array is empty."""
    client = AudiothekClient()

    def _mock_requests_get_empty_nodes(self, *args, **kwargs):
        class MockResponse:
            def json(self):
                return {"data": {"result": {"items": {"nodes": []}}}}
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_requests_get_empty_nodes)

    result = client.get_program_set_title("test_id")
    assert result is None


def test_get_episode_title_requests_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_episode_title when requests.Session.get raises exception."""
    client = AudiothekClient()

    def _mock_requests_get_exception(self, *args, **kwargs):
        raise requests.exceptions.RequestException("Network error")

    monkeypatch.setattr("requests.Session.get", _mock_requests_get_exception)

    result = client.get_episode_title("test_id")
    assert result is None


def test_get_program_set_title_requests_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_program_set_title when requests.Session.get raises exception."""
    client = AudiothekClient()

    def _mock_requests_get_exception(self, *args, **kwargs):
        raise requests.exceptions.RequestException("Network error")

    monkeypatch.setattr("requests.Session.get", _mock_requests_get_exception)

    result = client.get_program_set_title("test_id")
    assert result is None


def test_get_program_set_title_missing_title_in_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_program_set_title when node exists but has no title."""
    client = AudiothekClient()

    def _mock_requests_get_no_title(self, *args, **kwargs):
        class MockResponse:
            def json(self):
                return {"data": {"result": {"items": {"nodes": [{"programSet": {}}]}}}}
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_requests_get_no_title)

    result = client.get_program_set_title("test_id")
    assert result is None


def test_get_episode_title_with_valid_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_episode_title with valid API response."""
    client = AudiothekClient()

    def _mock_requests_get_valid(self, *args, **kwargs):
        class MockResponse:
            def json(self):
                return {
                    "data": {
                        "result": {
                            "programSet": {
                                "title": "Test Program Title"
                            }
                        }
                    }
                }
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_requests_get_valid)

    result = client.get_episode_title("test_id")
    assert result == "Test Program Title"


def test_get_program_set_title_with_valid_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test get_program_set_title with valid API response."""
    client = AudiothekClient()

    def _mock_requests_get_valid(self, *args, **kwargs):
        class MockResponse:
            def json(self):
                return {
                    "data": {
                        "result": {
                            "items": {
                                "nodes": [
                                    {
                                        "programSet": {
                                            "title": "Test Program Set Title"
                                        }
                                    }
                                ]
                            }
                        }
                    }
                }
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_requests_get_valid)

    result = client.get_program_set_title("test_id")
    assert result == "Test Program Set Title"


def test_get_program_title_unknown_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _get_program_title with unknown resource type."""
    downloader = AudiothekDownloader()

    # Mock _determine_resource_type_from_id to return None
    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", lambda self, rid: None)

    result = downloader._get_program_title("unknown_id", "unknown")
    assert result is None


def test_download_collection_saves_program_set_metadata(tmp_path: Path, mock_requests_get: object, graphql_mock: object) -> None:
    """Test that _download_collection saves program set metadata."""
    downloader = AudiothekDownloader()
    downloader._download_collection("https://x", "ps1", str(tmp_path), is_editorial_collection=False)

    program_dir = tmp_path / "ps1 Prog"
    assert program_dir.exists()

    # Check that program set metadata file was created
    metadata_file = program_dir / "ps1.json"
    assert metadata_file.exists()

    # Verify it's program set metadata
    metadata = json.loads(metadata_file.read_text())
    assert metadata["id"] == "ps1"
    assert "synopsis" in metadata
    assert "numberOfElements" in metadata


def test_download_collection_saves_editorial_collection_metadata(tmp_path: Path, mock_requests_get: object, graphql_mock: object) -> None:
    """Test that _download_collection saves editorial collection metadata."""
    downloader = AudiothekDownloader()
    downloader._download_collection("https://x", "ec1", str(tmp_path), is_editorial_collection=True)

    program_dir = tmp_path / "ps1 Prog"
    assert program_dir.exists()

    # Check that editorial collection metadata file was created in the series folder
    collection_file = program_dir / "ec1.json"
    assert collection_file.exists()

    # Verify it's editorial collection metadata
    metadata = json.loads(collection_file.read_text())
    assert metadata["id"] == "ec1"
    assert "editorialDescription" in metadata
    assert "summary" in metadata


def test_save_collection_data_editorial_collection(tmp_path: Path, mock_requests_get: object) -> None:
    """Test _save_collection_data with editorial collection."""
    downloader = AudiothekDownloader()
    collection_data = {
        "id": "test_ec",
        "title": "Test Editorial Collection",
        "editorialDescription": "Test editorial description",
        "summary": "Test summary",
        "image": {"url": "https://cdn.test/collection_{width}.jpg"}
    }

    downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=True)

    # Check that metadata file exists
    collection_file = tmp_path / "test_ec.json"
    assert collection_file.exists()

    # Verify metadata content
    metadata = json.loads(collection_file.read_text())
    assert metadata["id"] == "test_ec"
    assert metadata["title"] == "Test Editorial Collection"
    assert metadata["editorialDescription"] == "Test editorial description"
    assert metadata["summary"] == "Test summary"

    # Check that cover image exists
    cover_image_file = tmp_path / "test_ec.jpg"
    assert cover_image_file.exists()


def test_save_collection_data_program_set(tmp_path: Path, mock_requests_get: object) -> None:
    """Test _save_collection_data with program set."""
    downloader = AudiothekDownloader()
    collection_data = {
        "id": "test_ps",
        "title": "Test Program Set",
        "synopsis": "Test synopsis",
        "image": {"url": "https://cdn.test/program_{width}.jpg"}
    }

    downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=False)

    # Check that metadata file exists
    collection_file = tmp_path / "test_ps.json"
    assert collection_file.exists()

    # Verify metadata content
    metadata = json.loads(collection_file.read_text())
    assert metadata["id"] == "test_ps"
    assert metadata["title"] == "Test Program Set"
    assert metadata["synopsis"] == "Test synopsis"
    assert "editorialDescription" not in metadata
    assert "summary" not in metadata

    # Check that cover image exists
    cover_image_file = tmp_path / "test_ps.jpg"
    assert cover_image_file.exists()


def test_save_collection_data_without_id_uses_fallback(tmp_path: Path) -> None:
    """Test _save_collection_data uses fallback ID when no ID is provided."""
    downloader = AudiothekDownloader()

    collection_data = {"title": "Test Collection"}

    # Test editorial collection fallback
    downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=True)
    collection_file = tmp_path / "collection.json"
    assert collection_file.exists()

    # Test program set fallback
    downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=False)
    program_set_file = tmp_path / "program_set.json"
    assert program_set_file.exists()


def test_save_collection_data_directory_creation_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test _save_collection_data when directory creation fails."""
    def _mock_makedirs(path, exist_ok=False):
        raise OSError("Permission denied")

    monkeypatch.setattr("os.makedirs", _mock_makedirs)

    downloader = AudiothekDownloader()
    collection_data = {"id": "test_ec", "title": "Test Collection"}

    with caplog.at_level("ERROR"):
        downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=True)

    # Should have logged error
    assert any("Couldn't create output directory" in r.message for r in caplog.records)


def test_save_collection_data_downloads_cover_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that _save_collection_data downloads cover image when available."""
    downloader = AudiothekDownloader()

    collection_data = {
        "id": "test_ec",
        "title": "Test Collection",
        "image": {"url": "https://cdn.test/collection_{width}.jpg"}
    }

    # Mock requests.Session.get to simulate image download
    def _mock_get(self, url: str, timeout: int | None = None, **kwargs: Any):
        class MockResponse:
            def raise_for_status(self):
                pass
            @property
            def content(self):
                return b"fake_image_data"
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_get)

    downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=True)

    # Check that cover image was saved
    cover_image_file = tmp_path / "test_ec.jpg"
    assert cover_image_file.exists()
    assert cover_image_file.read_bytes() == b"fake_image_data"


def test_save_collection_data_no_image_url(tmp_path: Path) -> None:
    """Test _save_collection_data when no image URL is provided."""
    downloader = AudiothekDownloader()
    collection_data = {
        "id": "test_ec",
        "title": "Test Collection"
        # No image field
    }

    downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=True)

    # Check that metadata file exists but no cover image
    collection_file = tmp_path / "test_ec.json"
    assert collection_file.exists()

    cover_image_file = tmp_path / "test_ec.jpg"
    assert not cover_image_file.exists()


def test_save_collection_data_image_download_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test _save_collection_data when image download fails."""
    def _mock_get_error(self, url: str, timeout: int | None = None, **kwargs: Any):
        class MockResponse:
            def raise_for_status(self):
                raise requests.HTTPError("404 Not Found")
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_get_error)

    downloader = AudiothekDownloader()
    collection_data = {
        "id": "test_ec",
        "title": "Test Collection",
        "image": {"url": "https://cdn.test/collection_{width}.jpg"}
    }

    with caplog.at_level("ERROR"):
        downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=True)

    # Should have logged error but metadata file should still exist
    collection_file = tmp_path / "test_ec.json"
    assert collection_file.exists()

    assert any("Error downloading editorial collection cover image" in r.message for r in caplog.records)


def test_save_collection_data_skips_existing_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _save_collection_data skips image download when file already exists."""
    downloader = AudiothekDownloader()
    collection_data = {
        "id": "test_ec",
        "title": "Test Collection",
        "image": {"url": "https://cdn.test/collection_{width}.jpg"}
    }

    # Create existing image file
    cover_image_file = tmp_path / "test_ec.jpg"
    cover_image_file.write_bytes(b"existing_image_data")

    # Mock requests.Session.get - this should not be called
    get_called = False
    def _mock_get(self, url: str, timeout: int | None = None, **kwargs: Any):
        nonlocal get_called
        get_called = True
        class MockResponse:
            def raise_for_status(self):
                pass
            @property
            def content(self):
                return b"new_image_data"
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_get)

    downloader._save_collection_data(collection_data, str(tmp_path), is_editorial_collection=True)

    # Check that existing file was not overwritten
    assert cover_image_file.read_bytes() == b"existing_image_data"
    assert not get_called  # requests.Session.get should not have been called


def test_download_collection_with_editorial_collection_id_from_url(tmp_path: Path, mock_requests_get: object, graphql_mock: object) -> None:
    """Test downloading editorial collection using URL with editorial collection URN."""
    downloader = AudiothekDownloader()
    downloader.download_from_url("https://www.ardaudiothek.de/sammlung/test/urn:ard:page:ec1/", str(tmp_path))

    # Check that editorial collection metadata file was created in the series folder
    series_folder = tmp_path / "ps1 Prog"  # Based on mock data programSet id and title
    collection_file = series_folder / "ec1.json"
    assert collection_file.exists()

    # Verify it's editorial collection metadata
    metadata = json.loads(collection_file.read_text())
    assert metadata["id"] == "ec1"
    assert "editorialDescription" in metadata


def test_download_collection_with_program_set_id_from_url(tmp_path: Path, mock_requests_get: object, graphql_mock: object) -> None:
    """Test downloading program set using URL with program set URN."""
    downloader = AudiothekDownloader()
    downloader.download_from_url("https://www.ardaudiothek.de/sendung/test/urn:ard:show:ps1/", str(tmp_path))

    # Check that program set metadata file was created in the series folder
    series_folder = tmp_path / "ps1 Prog"  # Based on mock data programSet id and title
    collection_file = series_folder / "ps1.json"
    assert collection_file.exists()

    # Verify it's program set metadata
    metadata = json.loads(collection_file.read_text())
    assert metadata["id"] == "ps1"
    assert "synopsis" in metadata
    assert "editorialDescription" not in metadata
