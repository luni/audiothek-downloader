"""Tests for download functionality."""

import json
import os
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
        return MockResponse()

    monkeypatch.setattr("requests.Session.get", _mock_requests_get)

    downloader._save_nodes([node], str(tmp_path))

    # Should create folder with just the ID when no title
    assert (tmp_path / "ps1").exists()


def test_download_from_id_with_base_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test download_from_id uses base_folder when no folder provided."""
    downloader = AudiothekDownloader("/default/path")

    calls = []

    def _mock_download_from_id(self, resource_id, folder):
        calls.append(("download_from_id", resource_id, folder))

    def _mock_download_single_episode(self, episode_id, folder):
        calls.append(("download_single_episode", episode_id, folder))

    def _mock_download_collection(self, resource_id, folder, is_editorial):
        calls.append(("download_collection", resource_id, folder))

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", lambda self, rid: ("program", rid))
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

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", lambda self, rid: ("episode", rid))
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

    def _mock_determine_resource_type_from_id(self, resource_id):
        return "collection", resource_id

    monkeypatch.setattr(AudiothekDownloader, "_determine_resource_type_from_id", _mock_determine_resource_type_from_id)
    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    downloader.download_from_id("test_id")

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

    def _mock_parse_url(self, url):
        return "program", "test_id"

    monkeypatch.setattr(AudiothekDownloader, "_parse_url", _mock_parse_url)
    monkeypatch.setattr(AudiothekDownloader, "_download_collection", _mock_download_collection)

    downloader.download_from_url("https://example.com/test", str(tmp_path))

    # Should have called download_collection with is_editorial=False for program
    assert len(calls) == 1
    assert calls[0][0] == "download_collection"
    assert calls[0][3] is False  # is_editorial flag for program type
