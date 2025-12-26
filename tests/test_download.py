"""Tests for download functionality."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import requests

from audiothek import AudiothekDownloader
from tests.conftest import GraphQLMock, MockResponse


def test_download_single_episode_writes_files(tmp_path: Path, mock_requests_get: object) -> None:
    downloader = AudiothekDownloader()
    downloader._download_single_episode("urn:ard:episode:test", str(tmp_path))

    # written under programSet id and title from mock: "ps1 Prog"
    program_dir = tmp_path / "ps1 Prog"
    assert program_dir.exists()

    files = {p.name for p in program_dir.iterdir()}
    assert any(name.endswith(".mp3") for name in files)
    assert any(name.endswith(".jpg") for name in files)
    assert any(name.endswith(".json") for name in files)

    meta_path = next(p for p in program_dir.iterdir() if p.name.endswith(".json"))
    meta = json.loads(meta_path.read_text())
    assert meta["id"] == "urn:ard:episode:test"
    assert meta["programSet"]["id"] == "ps1"


def test_download_collection_paginates_and_writes(tmp_path: Path, mock_requests_get: object, graphql_mock: GraphQLMock) -> None:
    downloader = AudiothekDownloader()
    downloader._download_collection("ps1", str(tmp_path), is_editorial_collection=False)

    program_dir = tmp_path / "ps1 Prog"
    assert program_dir.exists()

    # Two pages x two nodes => four episode meta json files + one collection metadata file + episode images + collection cover image
    json_files = [p for p in program_dir.iterdir() if p.name.endswith(".json")]
    jpg_files = [p for p in program_dir.iterdir() if p.name.endswith(".jpg")]
    assert len(json_files) == 5  # 4 episodes + 1 collection metadata
    assert len(jpg_files) >= 1  # At least 1 collection cover image (plus episode images)

    # Check that collection cover image exists
    collection_cover = program_dir / "ps1.jpg"
    assert collection_cover.exists()

    # Ensure pagination occurred: graphql was called twice for ProgramSetEpisodesQuery
    calls = [c for c in graphql_mock.calls if c["operation"] == "ProgramSetEpisodesQuery"]
    assert len(calls) == 2
    assert calls[0]["variables"]["offset"] == 0
    assert calls[1]["variables"]["offset"] == 24


def test_save_nodes_skips_when_no_audio(tmp_path: Path, mock_requests_get: object) -> None:
    downloader = AudiothekDownloader()
    downloader._save_nodes(
        [
            {
                "id": "e1",
                "title": "t",
                "audios": [],
                "programSet": {"id": "ps1"},
            }
        ],
        str(tmp_path),
    )

    assert not (tmp_path / "ps1 Prog").exists()


def test_download_single_episode_not_found_logs_and_returns(tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch) -> None:
    def _mock_get(self, url: str, params: dict | None = None, timeout: int | None = None, **kwargs: Any):
        class _Resp:
            def json(self):
                return {"data": {"result": None}}
        return _Resp()

    monkeypatch.setattr("requests.Session.get", _mock_get)

    with caplog.at_level("ERROR"):
        downloader = AudiothekDownloader()
        downloader._download_single_episode("urn:ard:episode:nonexistent", str(tmp_path))

    assert any("Episode not found" in r.message for r in caplog.records)


def test_download_collection_no_results_breaks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, graphql_mock: GraphQLMock) -> None:
    def _mock_get(self, url: str, params: dict | None = None, timeout: int | None = None, **kwargs: Any):
        if url == "https://api.ardaudiothek.de/graphql":
            # Return empty results to trigger break
            return MockResponse(_json={"data": {"result": None}})
        return MockResponse(content=b"binary")

    monkeypatch.setattr("requests.Session.get", _mock_get)

    # Should not create any directories since no results
    downloader = AudiothekDownloader()
    downloader._download_collection("ps1", str(tmp_path), is_editorial_collection=False)
    assert not (tmp_path / "ps1 Prog").exists()


def test_download_collection_no_metadata_when_no_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that no metadata file is created when API returns no results."""
    def _mock_get_no_results(self, url: str, params: dict | None = None, timeout: int | None = None, **kwargs: Any):
        if url == "https://api.ardaudiothek.de/graphql":
            return MockResponse(_json={"data": {"result": None}})
        return MockResponse(content=b"binary")

    monkeypatch.setattr("requests.Session.get", _mock_get_no_results)

    downloader = AudiothekDownloader()
    downloader._download_collection("test_id", str(tmp_path), is_editorial_collection=False)

    # No series folder should be created, so no metadata file should exist
    assert not (tmp_path / "test_id.json").exists()
    assert not (tmp_path / "test_id Prog").exists()


def test_save_nodes_directory_creation_error_logs_and_returns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def _mock_makedirs(path, exist_ok=False):
        raise OSError("Permission denied")

    monkeypatch.setattr("os.makedirs", _mock_makedirs)

    nodes = [
        {
            "id": "e1",
            "title": "Test Episode",
            "audios": [{"downloadUrl": "https://cdn.test/audio.mp3"}],
            "programSet": {"id": "ps1", "title": "Prog"},
        }
    ]

    with caplog.at_level("ERROR"):
        downloader = AudiothekDownloader()
        downloader._save_nodes(nodes, str(tmp_path))

    assert any("Couldn't create output directory" in r.message for r in caplog.records)


def test_save_nodes_does_not_redownload_existing_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir(parents=True)

    # save_nodes builds filename as: <sanitized_title>_<node_id>
    filename = "Existing_e1_e1"
    (program_dir / f"{filename}.mp3").write_bytes(b"old")
    (program_dir / f"{filename}.jpg").write_bytes(b"old")
    (program_dir / f"{filename}_x1.jpg").write_bytes(b"old")

    calls: list[str] = []

    def _get(self, url: str, params: dict | None = None, timeout: int | None = None):
        calls.append(f"GET:{url}")

        class _Resp:
            content = b"new"

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return _Resp()

    def _head(self, url: str, timeout: int | None = None):
        calls.append(f"HEAD:{url}")

        class _Resp:
            headers = {"content-length": "3"}  # Same size as existing file (b"old" = 3 bytes)

            def raise_for_status(self):
                pass

        return _Resp()

    monkeypatch.setattr("requests.Session.get", _get)
    monkeypatch.setattr("requests.Session.head", _head)

    downloader = AudiothekDownloader()
    downloader._save_nodes(
        [
            {
                "id": "e1",
                "title": "Existing e1",
                "image": {"url": "https://cdn.test/image_{width}.jpg", "url1X1": "https://cdn.test/image1x1_{width}.jpg"},
                "audios": [{"downloadUrl": "https://cdn.test/audio.mp3"}],
                "programSet": {"id": "ps1", "title": "Prog"},
            }
        ],
        str(tmp_path),
    )

    # Should only make HEAD request to check content length, no GET requests
    assert calls == ["HEAD:https://cdn.test/audio.mp3"]
    assert os.path.exists(program_dir / f"{filename}.json")


def test_save_nodes_redownloads_incomplete_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that incomplete files are backed up and re-downloaded when new version is larger."""
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir(parents=True)

    # save_nodes builds filename as: <sanitized_title>_<node_id>
    filename = "Existing_e1_e1"
    (program_dir / f"{filename}.mp3").write_bytes(b"old")  # 3 bytes
    (program_dir / f"{filename}.jpg").write_bytes(b"old")
    (program_dir / f"{filename}_x1.jpg").write_bytes(b"old")

    calls: list[str] = []

    def _get(self, url: str, params: dict | None = None, timeout: int | None = None):
        calls.append(f"GET:{url}")

        class _Resp:
            content = b"new"

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return _Resp()

    def _head(self, url: str, timeout: int | None = None):
        calls.append(f"HEAD:{url}")

        class _Resp:
            headers = {"content-length": "10"}  # Larger than existing file (3 bytes)

            def raise_for_status(self):
                pass

        return _Resp()

    monkeypatch.setattr("requests.Session.get", _get)
    monkeypatch.setattr("requests.Session.head", _head)

    downloader = AudiothekDownloader()
    downloader._save_nodes(
        [
            {
                "id": "e1",
                "title": "Existing e1",
                "image": {"url": "https://cdn.test/image_{width}.jpg", "url1X1": "https://cdn.test/image1x1_{width}.jpg"},
                "audios": [{"downloadUrl": "https://cdn.test/audio.mp3"}],
                "programSet": {"id": "ps1", "title": "Prog"},
            }
        ],
        str(tmp_path),
    )

    # Should make HEAD request to check content length, then GET to re-download
    assert calls == ["HEAD:https://cdn.test/audio.mp3", "GET:https://cdn.test/audio.mp3"]
    assert os.path.exists(program_dir / f"{filename}.json")
    # Original file should be backed up
    assert os.path.exists(program_dir / f"{filename}.mp3.bak")
    # New file should be downloaded
    assert (program_dir / f"{filename}.mp3").read_bytes() == b"new"


def test_save_nodes_skips_smaller_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that files are not re-downloaded when new version is smaller."""
    program_dir = tmp_path / "ps1 Prog"
    program_dir.mkdir(parents=True)

    # save_nodes builds filename as: <sanitized_title>_<node_id>
    filename = "Existing_e1_e1"
    (program_dir / f"{filename}.mp3").write_bytes(b"larger")  # 6 bytes
    (program_dir / f"{filename}.jpg").write_bytes(b"old")
    (program_dir / f"{filename}_x1.jpg").write_bytes(b"old")

    calls: list[str] = []

    def _get(self, url: str, params: dict | None = None, timeout: int | None = None):
        calls.append(f"GET:{url}")

        class _Resp:
            content = b"new"

            def json(self):
                return {}

            def raise_for_status(self):
                pass

        return _Resp()

    def _head(self, url: str, timeout: int | None = None):
        calls.append(f"HEAD:{url}")

        class _Resp:
            headers = {"content-length": "3"}  # Smaller than existing file (6 bytes)

            def raise_for_status(self):
                pass

        return _Resp()

    monkeypatch.setattr("requests.Session.get", _get)
    monkeypatch.setattr("requests.Session.head", _head)

    downloader = AudiothekDownloader()
    downloader._save_nodes(
        [
            {
                "id": "e1",
                "title": "Existing e1",
                "image": {"url": "https://cdn.test/image_{width}.jpg", "url1X1": "https://cdn.test/image1x1_{width}.jpg"},
                "audios": [{"downloadUrl": "https://cdn.test/audio.mp3"}],
                "programSet": {"id": "ps1", "title": "Prog"},
            }
        ],
        str(tmp_path),
    )

    # Should make HEAD request to check content length, but no GET request
    assert calls == ["HEAD:https://cdn.test/audio.mp3"]
    assert os.path.exists(program_dir / f"{filename}.json")
    # Original file should not be backed up
    assert not os.path.exists(program_dir / f"{filename}.mp3.bak")
    # Original file should remain unchanged
    assert (program_dir / f"{filename}.mp3").read_bytes() == b"larger"


def test_save_nodes_no_download_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _save_nodes when node has no download URL."""
    downloader = AudiothekDownloader()

    # Node with empty audios array
    node = {
        "id": "test_id",
        "title": "Test Episode",
        "audios": [],
        "programSet": {"id": "ps1", "title": "Test Program"}
    }

    downloader._save_nodes([node], str(tmp_path))

    # No folder should be created since no audio URL
    assert not (tmp_path / "ps1 Test Program").exists()


def test_save_nodes_no_audio_in_first_item(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _save_nodes when first audio item is not a dict."""
    downloader = AudiothekDownloader()

    # Node with audios array where first item is not a dict
    node = {
        "id": "test_id",
        "title": "Test Episode",
        "audios": ["not_a_dict"],
        "programSet": {"id": "ps1", "title": "Test Program"}
    }

    downloader._save_nodes([node], str(tmp_path))

    # No folder should be created since no valid audio
    assert not (tmp_path / "ps1 Test Program").exists()


def test_save_nodes_empty_download_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _save_nodes when audio has empty download URL."""
    downloader = AudiothekDownloader()

    # Node with audio but empty URLs
    node = {
        "id": "test_id",
        "title": "Test Episode",
        "audios": [{"downloadUrl": "", "url": ""}],
        "programSet": {"id": "ps1", "title": "Test Program"}
    }

    downloader._save_nodes([node], str(tmp_path))

    # No folder should be created since no valid audio URL
    assert not (tmp_path / "ps1 Test Program").exists()


def test_save_nodes_without_programset_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test _save_nodes when programSet has no title."""
    downloader = AudiothekDownloader()

    # Node with no programSet title
    node = {
        "id": "test_id",
        "title": "Test Episode",
        "audios": [{"downloadUrl": "https://example.com/audio.mp3"}],
        "programSet": {"id": "ps1"}  # No title field
    }

    def _mock_requests_get(self, *args, **kwargs):
        class MockResponse:
            content = b"audio data"
            def raise_for_status(self):
                pass
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_requests_get)

    downloader._save_nodes([node], str(tmp_path))

    # Should create folder with just the ID when no title
    assert (tmp_path / "ps1").exists()


def test_download_from_id_with_base_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test download_from_id uses base_folder when no folder provided."""
    downloader = AudiothekDownloader("/default/path")

    calls = []

    def _mock_download_single_episode(self, episode_id, folder):
        calls.append(("download_single_episode", episode_id, folder))

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder))

    # Mock client method instead of downloader wrapper
    monkeypatch.setattr(downloader.client, "determine_resource_type_from_id", lambda rid: ("program", rid))

    monkeypatch.setattr(AudiothekDownloader, "_download_single_episode", _mock_download_single_episode)
    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    downloader.download_from_id("test_id")

    # Should have used the base_folder and called download_collection
    assert len(calls) == 1
    assert calls[0][0] == "download_collection"
    assert calls[0][2] == "/default/path"


def test_download_from_id_with_custom_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test download_from_id uses custom folder when provided."""
    downloader = AudiothekDownloader("/default/path")

    calls = []

    def _mock_download_single_episode(self, episode_id, folder):
        calls.append(("download_single_episode", episode_id, folder))

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder))

    # Mock client method instead of downloader wrapper
    monkeypatch.setattr(downloader.client, "determine_resource_type_from_id", lambda rid: ("episode", rid))

    monkeypatch.setattr(AudiothekDownloader, "_download_single_episode", _mock_download_single_episode)
    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    downloader.download_from_id("test_id", str(tmp_path))

    # Should have used the custom folder and called download_single_episode
    assert len(calls) == 1
    assert calls[0][0] == "download_single_episode"
    assert calls[0][2] == str(tmp_path)


def test_download_from_url_calls_collection_with_editorial_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test download_from_url calls _download_collection with correct editorial flag."""
    downloader = AudiothekDownloader()

    calls = []

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))

    def _mock_parse_url(url):
        return "collection", "test_id"

    # Mock client method instead of downloader wrapper (note: parse_url is static in client but used as instance method if not careful,
    # but here we mock it on the instance's client or class)
    # Since parse_url is static, we can mock it on the class or instance.
    monkeypatch.setattr(downloader.client, "parse_url", _mock_parse_url)

    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    downloader.download_from_url("https://example.com/test")

    # Should have called download_collection with is_editorial=True for collection
    assert len(calls) == 1
    assert calls[0][0] == "download_collection"
    assert calls[0][3] is True  # is_editorial flag


def test_download_from_url_calls_collection_for_program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test download_from_url calls _download_collection for program type."""
    downloader = AudiothekDownloader()

    calls = []

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder, is_editorial))

    def _mock_parse_url(url):
        return "program", "test_id"

    # Mock client method instead of downloader wrapper
    monkeypatch.setattr(downloader.client, "parse_url", _mock_parse_url)

    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    downloader.download_from_url("https://example.com/test", str(tmp_path))

    # Should have called download_collection with is_editorial=False for program
    assert len(calls) == 1
    assert calls[0][0] == "download_collection"
    assert calls[0][3] is False  # is_editorial flag for program type


def test_file_modification_time_set_from_publish_date(tmp_path: Path, mock_requests_get: object) -> None:
    """Test that file modification time is set from publishDate."""
    downloader = AudiothekDownloader()

    # Test the _set_file_modification_time method directly
    test_file = tmp_path / "test.mp3"
    test_file.write_bytes(b"dummy audio content")

    # Initial modification time should be recent
    initial_mtime = test_file.stat().st_mtime
    recent_time = datetime.now().timestamp()
    assert abs(initial_mtime - recent_time) < 10  # Within 10 seconds

    # Set modification time to a specific publish date
    publish_date = "2023-12-01T10:00:00.000Z"
    downloader._set_file_modification_time(str(test_file), publish_date)

    # Check that modification time was updated
    updated_mtime = test_file.stat().st_mtime
    expected_time = datetime.fromisoformat("2023-12-01T10:00:00.000+00:00").timestamp()

    # Allow small tolerance for filesystem precision
    assert abs(updated_mtime - expected_time) < 1


def test_extract_audio_url_chooses_larger_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that _extract_audio_url chooses the larger file when sizes differ."""
    downloader = AudiothekDownloader()

    # Mock content length requests
    head_calls = {}

    def _mock_head(self, url: str, timeout: int | None = None):
        head_calls[url] = True
        class MockResponse:
            def raise_for_status(self):
                pass
            headers = {}
        response = MockResponse()
        if "larger" in url:
            response.headers["content-length"] = "1000"
        else:
            response.headers["content-length"] = "500"
        return response

    monkeypatch.setattr("requests.Session.head", _mock_head)

    node = {
        "audios": [{
            "downloadUrl": "https://example.com/smaller.mp3",
            "url": "https://example.com/larger.mp4"
        }]
    }

    audio_urls = downloader._extract_audio_url(node)
    assert len(audio_urls) >= 2
    assert audio_urls[0] == "https://example.com/larger.mp4"
    assert audio_urls[1] == "https://example.com/smaller.mp3"
    assert "https://example.com/smaller.mp3" in head_calls
    assert "https://example.com/larger.mp4" in head_calls


def test_extract_audio_url_chooses_downloadUrl_when_same_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that _extract_audio_url chooses downloadUrl when sizes are equal."""
    downloader = AudiothekDownloader()

    def _mock_head(self, url: str, timeout: int | None = None):
        class MockResponse:
            def raise_for_status(self):
                pass
            headers = {"content-length": "1000"}
        return MockResponse()

    monkeypatch.setattr("requests.Session.head", _mock_head)

    node = {
        "audios": [{
            "downloadUrl": "https://example.com/audio.mp3",
            "url": "https://example.com/audio.mp4"
        }]
    }

    audio_urls = downloader._extract_audio_url(node)
    # Should choose downloadUrl when sizes are equal (>= comparison)
    assert len(audio_urls) >= 2
    assert audio_urls[0] == "https://example.com/audio.mp3"
    assert audio_urls[1] == "https://example.com/audio.mp4"


def test_get_audio_file_extension() -> None:
    """Test file extension detection for different audio formats."""
    downloader = AudiothekDownloader()

    assert downloader._get_audio_file_extension("https://example.com/audio.mp3") == ".mp3"
    assert downloader._get_audio_file_extension("https://example.com/audio.MP3") == ".mp3"
    assert downloader._get_audio_file_extension("https://example.com/audio.mp4") == ".mp4"
    assert downloader._get_audio_file_extension("https://example.com/audio.aac") == ".aac"
    assert downloader._get_audio_file_extension("https://example.com/audio.m4a") == ".m4a"
    assert downloader._get_audio_file_extension("https://example.com/audio?format=aac") == ".aac"
    assert downloader._get_audio_file_extension("https://example.com/audio?format=mp4") == ".mp4"
    assert downloader._get_audio_file_extension("https://example.com/audio") == ".mp3"  # Default


def test_all_files_get_timestamp_from_publish_date(tmp_path: Path, mock_requests_get: object) -> None:
    """Test that all downloaded files (audio, images, metadata) get timestamps from publishDate."""
    downloader = AudiothekDownloader()

    # Create test files of different types
    audio_file = tmp_path / "test_audio.mp3"
    image_file = tmp_path / "test_image.jpg"
    metadata_file = tmp_path / "test_metadata.json"

    audio_file.write_bytes(b"dummy audio content")
    image_file.write_bytes(b"dummy image content")
    metadata_file.write_text('{"test": "metadata"}')

    # Set modification times for all files
    publish_date = "2023-11-15T14:30:00.000Z"
    expected_time = datetime.fromisoformat("2023-11-15T14:30:00.000+00:00").timestamp()

    downloader._set_file_modification_time(str(audio_file), publish_date)
    downloader._set_file_modification_time(str(image_file), publish_date)
    downloader._set_file_modification_time(str(metadata_file), publish_date)

    # Check that all files have the correct modification time
    for file_path in [audio_file, image_file, metadata_file]:
        file_mtime = file_path.stat().st_mtime
        assert abs(file_mtime - expected_time) < 1, f"Timestamp not set correctly for {file_path.name}"


def test_download_audio_file_handles_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that _download_audio_file returns False for 404 responses."""
    downloader = AudiothekDownloader()

    def _mock_download_audio_file(url: str, file_path: str) -> bool:
        return False  # Simulate 404 response

    monkeypatch.setattr(downloader.client, "_download_audio_to_file", _mock_download_audio_file)

    audio_file_path = tmp_path / "test.mp3"
    result = downloader.client._download_audio_to_file("https://example.com/notfound.mp3", str(audio_file_path))

    assert result is False
    assert not audio_file_path.exists()


def test_download_audio_file_handles_error_response_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that _download_audio_file returns False for error response content."""
    downloader = AudiothekDownloader()

    def _mock_download_audio_file(url: str, file_path: str) -> bool:
        return False  # Simulate error response content

    monkeypatch.setattr(downloader.client, "_download_audio_to_file", _mock_download_audio_file)

    audio_file_path = tmp_path / "test.mp3"
    result = downloader.client._download_audio_to_file("https://example.com/error.mp3", str(audio_file_path))

    assert result is False
    assert not audio_file_path.exists()


def test_save_audio_file_handles_deleted_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test that _save_audio_file handles deleted/unavailable audio files correctly."""
    downloader = AudiothekDownloader()

    def _mock_download_audio_file(self, url: str, file_path: str, fallback_url: str | None = None) -> bool:
        return False  # Simulate failed download

    monkeypatch.setattr(downloader.client, "_download_audio_to_file", _mock_download_audio_file)

    # Create a directory
    program_dir = tmp_path / "test_program"
    program_dir.mkdir()

    with caplog.at_level("ERROR"):
        downloader._save_audio_file(
            ["https://example.com/deleted.mp3", "https://example.com/fallback.mp3"],
            "test_audio",
            str(program_dir),
            1,
            1,
            "2023-12-01T10:00:00.000Z"
        )

    # Should log error about failed download
    assert any("Failed to download audio file" in r.message for r in caplog.records)
    # Audio file should not exist
    assert not (program_dir / "test_audio.mp3").exists()


def test_save_audio_file_restores_backup_on_download_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test that _save_audio_file restores backup file when download fails."""
    downloader = AudiothekDownloader()

    def _mock_download_audio_file(self, url: str, file_path: str, fallback_url: str | None = None) -> bool:
        return False  # Simulate failed download

    def _mock_check_file_availability(url: str) -> tuple[bool, int | None]:
        return True, 1000  # Available and larger than existing file to trigger backup

    monkeypatch.setattr(downloader.client, "_download_audio_to_file", _mock_download_audio_file)
    monkeypatch.setattr(downloader.client, "_check_file_availability", _mock_check_file_availability)

    # Create a directory and existing file
    program_dir = tmp_path / "test_program"
    program_dir.mkdir()
    original_file = program_dir / "test_audio.mp3"
    original_file.write_bytes(b"original content")

    with caplog.at_level("INFO"):
        downloader._save_audio_file(
            ["https://example.com/larger.mp3", "https://example.com/fallback.mp3"],
            "test_audio",
            str(program_dir),
            1,
            1,
            "2023-12-01T10:00:00.000Z"
        )

    # Should log backup creation and restoration
    log_messages = [r.message for r in caplog.records]
    assert any("Backed up smaller file to:" in msg for msg in log_messages)
    assert any("Restored original file from backup:" in msg for msg in log_messages)

    # Original file should be restored
    assert original_file.exists()
    assert original_file.read_bytes() == b"original content"
    # Backup file should be gone
    assert not (program_dir / "test_audio.mp3.bak").exists()


def test_save_audio_file_skips_download_on_404_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test that _save_audio_file skips download when 404 is detected during availability check."""
    downloader = AudiothekDownloader()

    def _mock_check_file_availability(url: str) -> tuple[bool, int | None]:
        return False, None  # 404 - not available

    monkeypatch.setattr(downloader.client, "_check_file_availability", _mock_check_file_availability)

    # Create a directory and existing file
    program_dir = tmp_path / "test_program"
    program_dir.mkdir()
    original_file = program_dir / "test_audio.mp3"
    original_file.write_bytes(b"original content")

    with caplog.at_level("WARNING"):
        downloader._save_audio_file(
            ["https://example.com/deleted.mp3", "https://example.com/fallback.mp3"],
            "test_audio",
            str(program_dir),
            1,
            1,
            "2023-12-01T10:00:00.000Z"
        )

    # Should log 404 warning and keep existing file
    log_messages = [r.message for r in caplog.records]
    assert any("Audio file not available (404), keeping existing file:" in msg for msg in log_messages)

    # Original file should remain unchanged
    assert original_file.exists()
    assert original_file.read_bytes() == b"original content"
    # No backup should be created
    assert not (program_dir / "test_audio.mp3.bak").exists()


def test_download_audio_file_uses_fallback_on_404(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """Test that _download_audio_to_file uses fallback URL when primary URL returns 404."""
    from audiothek.client import AudiothekClient
    client = AudiothekClient()

    call_count = 0

    def _mock_get(self, url: str, timeout: int | None = None):
        nonlocal call_count
        call_count += 1

        class MockResponse:
            content = b"valid audio content"

            def raise_for_status(self):
                if url == "https://example.com/primary.mp3":
                    # Primary URL - simulate 404
                    # Create a mock response object that has status_code
                    response = requests.Response()
                    response.status_code = 404
                    raise requests.HTTPError(response=response)
                # Fallback URL succeeds

        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_get)

    with caplog.at_level("INFO"):
        audio_file_path = tmp_path / "test.mp3"
        result = client._download_audio_to_file("https://example.com/primary.mp3", str(audio_file_path), "https://example.com/fallback.mp3")

    assert result is True
    assert audio_file_path.exists()
    assert audio_file_path.read_bytes() == b"valid audio content"

    # Should log fallback usage
    log_messages = [r.message for r in caplog.records]
    assert any("Trying fallback URL:" in msg for msg in log_messages)
    assert any("Successfully downloaded from fallback URL:" in msg for msg in log_messages)


def test_remove_lower_quality_files_no_files(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test remove_lower_quality_files with empty directory."""
    downloader = AudiothekDownloader()

    with caplog.at_level("INFO"):
        downloader.remove_lower_quality_files(str(tmp_path))

    # Should log starting message but no removals
    log_messages = [r.message for r in caplog.records]
    assert any("Starting removal of lower quality files" in msg for msg in log_messages)


def test_remove_lower_quality_files_no_audio_files(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test remove_lower_quality_files with directory containing no audio files."""
    # Create non-audio files
    (tmp_path / "test.txt").write_text("test")
    (tmp_path / "image.jpg").write_bytes(b"fake image")

    downloader = AudiothekDownloader()

    with caplog.at_level("INFO"):
        downloader.remove_lower_quality_files(str(tmp_path))

    # Should log starting message but no removals
    log_messages = [r.message for r in caplog.records]
    assert any("Starting removal of lower quality files" in msg for msg in log_messages)


def test_get_audio_quality_invalid_file(tmp_path: Path) -> None:
    """Test _get_audio_quality with invalid file."""
    downloader = AudiothekDownloader()

    # Create a non-audio file
    invalid_file = tmp_path / "invalid.txt"
    invalid_file.write_text("not audio")

    quality = downloader._get_audio_quality(str(invalid_file))
    assert quality is None


def test_remove_lower_quality_files_dry_run(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test remove_lower_quality_files with dry_run=True."""
    downloader = AudiothekDownloader()

    with caplog.at_level("INFO"):
        downloader.remove_lower_quality_files(str(tmp_path), dry_run=True)

    # Should log dry run message
    log_messages = [r.message for r in caplog.records]
    assert any("DRY RUN: Showing what would be removed" in msg for msg in log_messages)


def test_remove_lower_quality_files_dry_run_with_subdirs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test remove_lower_quality_files with dry_run=True and subdirectories."""
    # Create subdirectories
    subdir1 = tmp_path / "subdir1"
    subdir2 = tmp_path / "subdir2"
    subdir1.mkdir()
    subdir2.mkdir()

    downloader = AudiothekDownloader()

    with caplog.at_level("INFO"):
        downloader.remove_lower_quality_files(str(tmp_path), dry_run=True)

    # Should log dry run message
    log_messages = [r.message for r in caplog.records]
    assert any("DRY RUN: Showing what would be removed" in msg for msg in log_messages)


def test_process_folder_quality_dry_run(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test _process_folder_quality with dry_run=True."""
    downloader = AudiothekDownloader()

    # Create a directory with some test files
    test_dir = tmp_path / "test_folder"
    test_dir.mkdir()

    with caplog.at_level("INFO"):
        downloader._process_folder_quality(str(test_dir), dry_run=True)

    # Should not error, even with dry_run=True


def test_compare_and_remove_files_dry_run(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test _compare_and_remove_files with dry_run=True."""
    downloader = AudiothekDownloader()

    # Mock _get_audio_quality to return bitrates
    def mock_get_quality(file_path):
        if file_path.endswith('.mp3'):
            return 128
        elif file_path.endswith('.mp4'):
            return 96
        return None

    downloader._get_audio_quality = mock_get_quality

    # Create mock files
    mp3_file = tmp_path / "test.mp3"
    mp4_file = tmp_path / "test.mp4"
    mp3_file.write_bytes(b"fake mp3 content")
    mp4_file.write_bytes(b"fake mp4 content")

    files = {'.mp3': str(mp3_file), '.mp4': str(mp4_file)}

    with caplog.at_level("INFO"):
        downloader._compare_and_remove_files("test", files, str(tmp_path), dry_run=True)

    # Should log dry run message for removal
    log_messages = [r.message for r in caplog.records]
    assert any("DRY RUN: Would remove lower quality file" in msg for msg in log_messages)


def test_remove_lower_quality_files_directory_not_found(caplog: pytest.LogCaptureFixture) -> None:
    """Test remove_lower_quality_files with non-existent directory."""
    downloader = AudiothekDownloader()

    with caplog.at_level("ERROR"):
        downloader.remove_lower_quality_files("/non/existent/path")

    # Should log error about directory not existing
    log_messages = [r.message for r in caplog.records]
    assert any("Output directory /non/existent/path does not exist" in msg for msg in log_messages)


def test_process_folder_quality_error_handling(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test _process_folder_quality error handling."""
    downloader = AudiothekDownloader()

    # Create a directory that will cause an error (permission denied simulation)
    restricted_dir = tmp_path / "restricted"
    restricted_dir.mkdir()

    # Mock os.listdir to raise an exception
    def mock_listdir(path):
        raise PermissionError("Permission denied")

    import audiothek.downloader
    original_listdir = audiothek.downloader.os.listdir
    audiothek.downloader.os.listdir = mock_listdir

    try:
        with caplog.at_level("ERROR"):
            downloader._process_folder_quality(str(restricted_dir))

        # Should log error
        log_messages = [r.message for r in caplog.records]
        assert any("Error processing folder" in msg for msg in log_messages)
    finally:
        audiothek.downloader.os.listdir = original_listdir


def test_compare_and_remove_files_single_file(tmp_path: Path) -> None:
    """Test _compare_and_remove_files with only one file (no comparison)."""
    downloader = AudiothekDownloader()

    # Test with single file - should not attempt removal
    files = {'.mp3': str(tmp_path / "test.mp3")}
    downloader._compare_and_remove_files("test", files, str(tmp_path))

    # Should not raise any errors


def test_compare_and_remove_files_no_quality_info(tmp_path: Path) -> None:
    """Test _compare_and_remove_files when quality info cannot be determined."""
    downloader = AudiothekDownloader()

    # Mock _get_audio_quality to return None
    def mock_get_quality(file_path):
        return None

    downloader._get_audio_quality = mock_get_quality

    files = {'.mp3': str(tmp_path / "test.mp3"), '.mp4': str(tmp_path / "test.mp4")}
    downloader._compare_and_remove_files("test", files, str(tmp_path))

    # Should not raise any errors


def test_remove_lower_quality_files_with_subdirs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Test remove_lower_quality_files with subdirectories."""
    # Create subdirectories
    subdir1 = tmp_path / "subdir1"
    subdir2 = tmp_path / "subdir2"
    subdir1.mkdir()
    subdir2.mkdir()

    downloader = AudiothekDownloader()

    with caplog.at_level("INFO"):
        downloader.remove_lower_quality_files(str(tmp_path))

    # Should log starting message
    log_messages = [r.message for r in caplog.records]
    assert any("Starting removal of lower quality files" in msg for msg in log_messages)
