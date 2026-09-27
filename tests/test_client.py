"""Tests for AudiothekClient."""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
import requests
from audiothek.exceptions import DownloadError, GraphQLError

from audiothek import AudiothekClient, ResourceInfo


class TestAudiothekClient:
    """Test cases for AudiothekClient."""

    def test_client_without_proxy_uses_default_session(self) -> None:
        """Test that client without proxy creates a session without proxy configuration."""
        client = AudiothekClient()

        # Check that no proxies are configured
        assert client._session.proxies == {}

    def test_client_with_http_proxy_configures_session(self) -> None:
        """Test that client with HTTP proxy correctly configures session."""
        proxy_url = "http://proxy.example.com:8080"
        client = AudiothekClient(proxy=proxy_url)

        expected_proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        assert client._session.proxies == expected_proxies

    def test_client_with_socks5_proxy_configures_session(self) -> None:
        """Test that client with SOCKS5 proxy correctly configures session."""
        proxy_url = "socks5://socks-proxy.example.com:1080"
        client = AudiothekClient(proxy=proxy_url)

        expected_proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        assert client._session.proxies == expected_proxies

    @patch('requests.Session.get')
    def test_graphql_get_uses_proxy(self, mock_get: Mock) -> None:
        """Test that GraphQL requests use the configured proxy."""
        proxy_url = "http://proxy.example.com:8080"
        client = AudiothekClient(proxy=proxy_url)

        # Mock response
        mock_response = Mock()
        mock_response.json.return_value = {"data": {"result": {}}}
        mock_get.return_value = mock_response

        # Make a GraphQL request
        client._graphql_get("query", {"var": "value"})

        mock_get.assert_called_once()
        assert client._session.proxies == {"http": proxy_url, "https": proxy_url}

    @patch('requests.Session.get')
    def test_graphql_get_does_not_cache_error_responses(self, mock_get: Mock) -> None:
        """GraphQL error payloads must not be written to the cache."""
        mock_response = Mock()
        mock_response.json.return_value = {"errors": [{"message": "boom"}]}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = AudiothekClient()
        client._cache = Mock()
        client._cache.get.return_value = None

        data = client._graphql_get("query", {"var": "value"})

        assert data == {"errors": [{"message": "boom"}]}
        client._cache.set.assert_not_called()

    @patch('requests.Session.get')
    def test_graphql_get_caches_success_responses(self, mock_get: Mock) -> None:
        """Successful GraphQL payloads are cached."""
        payload = {"data": {"result": {"id": "1"}}}
        mock_response = Mock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = AudiothekClient()
        client._cache = Mock()
        client._cache.get.return_value = None

        data = client._graphql_get("query", {"var": "value"})

        assert data == payload
        client._cache.set.assert_called_once()

    @patch('requests.Session.get')
    def test_graphql_get_rejects_non_dict_response(self, mock_get: Mock) -> None:
        """A valid-JSON but non-object response raises GraphQLError."""
        mock_response = Mock()
        mock_response.json.return_value = ["unexpected"]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = AudiothekClient()
        client._cache = Mock()
        client._cache.get.return_value = None

        with pytest.raises(GraphQLError):
            client._graphql_get("query", {"var": "value"})
        client._cache.set.assert_not_called()

    @patch('requests.Session.get')
    def test_download_to_file_cleans_part_on_replace_failure(self, mock_get: Mock, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A failed os.replace must not leave the .part file behind."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"img"]
        mock_get.return_value = mock_response

        def _fail_replace(src, dst):
            raise OSError("denied")

        monkeypatch.setattr("os.replace", _fail_replace)
        target = tmp_path / "img.jpg"

        client = AudiothekClient()
        with pytest.raises(DownloadError):
            client._download_to_file("http://example.com/img.jpg", str(target))

        assert not (tmp_path / "img.jpg.part").exists()
        assert not target.exists()

    @patch('requests.Session.get')
    def test_download_to_file_writes_via_part(self, mock_get: Mock, tmp_path: Path) -> None:
        """Successful downloads land atomically with no .part residue."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_get.return_value = mock_response

        target = tmp_path / "img.jpg"
        client = AudiothekClient()
        client._download_to_file("http://example.com/img.jpg", str(target))

        assert target.read_bytes() == b"chunk1chunk2"
        assert not (tmp_path / "img.jpg.part").exists()

    @patch('requests.Session.get')
    def test_download_to_file_uses_proxy(self, mock_get: Mock) -> None:
        """Test that file downloads use the configured proxy."""
        proxy_url = "http://proxy.example.com:8080"
        client = AudiothekClient(proxy=proxy_url)

        # Mock response
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"test content"]
        mock_get.return_value = mock_response

        # Make a file download request
        client._download_to_file("http://example.com/file.mp3", "/tmp/test.mp3")

        mock_get.assert_called_once()
        assert client._session.proxies == {"http": proxy_url, "https": proxy_url}

    def test_parse_url_with_urn_episode(self) -> None:
        """Test parsing URL with episode URN."""
        client = AudiothekClient()
        result = client.parse_url("https://www.ardsounds.de/episode/test-show/test-episode/urn:ard:episode:test123")

        assert result == ResourceInfo(resource_type="episode", resource_id="urn:ard:episode:test123")

    def test_parse_url_with_urn_collection(self) -> None:
        """Test parsing URL with collection URN."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://www.ardsounds.de/collection/urn:ard:page:test123")

        assert result == ResourceInfo(resource_type="collection", resource_id="urn:ard:page:test123")

    def test_parse_url_with_urn_program(self) -> None:
        """Test parsing URL with program URN."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://www.ardsounds.de/program/urn:ard:show:test123")

        assert result == ResourceInfo(resource_type="program", resource_id="urn:ard:show:test123")

    def test_parse_url_with_numeric_id(self) -> None:
        """Test parsing URL with numeric ID."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://www.ardsounds.de/program/123456")

        assert result == ResourceInfo(resource_type="program", resource_id="123456")

    def test_parse_url_invalid(self) -> None:
        """Test parsing invalid URL."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://example.com/invalid")

        assert result is None

    def test_determine_resource_type_from_id_episode(self) -> None:
        """Test determining resource type from episode ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("urn:ard:episode:test123")

        assert result == ResourceInfo(resource_type="episode", resource_id="urn:ard:episode:test123")

    def test_determine_resource_type_from_id_collection(self) -> None:
        """Test determining resource type from collection ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("urn:ard:page:test123")

        assert result == ResourceInfo(resource_type="collection", resource_id="urn:ard:page:test123")

    def test_determine_resource_type_from_id_program(self) -> None:
        """Test determining resource type from program ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("urn:ard:show:test123")

        assert result == ResourceInfo(resource_type="program", resource_id="urn:ard:show:test123")

    def test_determine_resource_type_from_id_numeric(self) -> None:
        """Test determining resource type from numeric ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("123456")

        assert result == ResourceInfo(resource_type="program", resource_id="123456")

    def test_determine_resource_type_from_id_alphanumeric(self) -> None:
        """Test determining resource type from alphanumeric ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("ps1")

        assert result == ResourceInfo(resource_type="program", resource_id="ps1")

    def test_determine_resource_type_from_id_invalid(self) -> None:
        """Test determining resource type from invalid ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("invalid-id!")

        assert result is None

    @patch.object(AudiothekClient, '_graphql_get')
    @patch('audiothek.client.load_graphql_query')
    def test_get_episode_title(self, mock_load_query: Mock, mock_graphql_get: Mock) -> None:
        """Test getting episode title."""
        mock_load_query.return_value = "query"
        mock_graphql_get.return_value = {
            "data": {
                "result": {
                    "programSet": {"title": "Test Program"}
                }
            }
        }

        client = AudiothekClient()
        result = client.get_episode_title("urn:ard:episode:test123")

        assert result == "Test Program"
        mock_load_query.assert_called_once_with("EpisodeQuery.graphql")
        mock_graphql_get.assert_called_once_with("query", {"id": "urn:ard:episode:test123"}, "EpisodeQuery")

    @patch.object(AudiothekClient, '_graphql_get')
    @patch('audiothek.client.load_graphql_query')
    def test_get_program_set_title(self, mock_load_query: Mock, mock_graphql_get: Mock) -> None:
        """Test getting program set title."""
        mock_load_query.return_value = "query"
        mock_graphql_get.return_value = {
            "data": {
                "result": {
                    "items": {
                        "nodes": [
                            {"programSet": {"title": "Test Program"}}
                        ]
                    }
                }
            }
        }

        client = AudiothekClient()
        result = client.get_program_set_title("123456")

        assert result == "Test Program"
        mock_load_query.assert_called_once_with("ProgramSetEpisodesQuery.graphql")
        mock_graphql_get.assert_called_once_with("query", {"id": "123456", "offset": 0, "count": 1}, "ProgramSetEpisodesQuery")

    @patch.object(AudiothekClient, '_graphql_get')
    @patch('audiothek.client.load_graphql_query')
    def test_get_program_set_title_prefers_top_level_title(self, mock_load_query: Mock, mock_graphql_get: Mock) -> None:
        """Top-level result title is preferred over the first node's programSet title."""
        mock_load_query.return_value = "query"
        mock_graphql_get.return_value = {
            "data": {
                "result": {
                    "title": "Top-Level Title",
                    "items": {
                        "nodes": [
                            {"programSet": {"title": "Node Program Title"}}
                        ]
                    }
                }
            }
        }

        client = AudiothekClient()
        result = client.get_program_set_title("123456")

        assert result == "Top-Level Title"

    @patch.object(AudiothekClient, '_graphql_get')
    @patch('audiothek.client.load_graphql_query')
    def test_get_collection_title_returns_top_level_title(self, mock_load_query: Mock, mock_graphql_get: Mock) -> None:
        """get_collection_title reads the editorial collection's top-level title."""
        mock_load_query.return_value = "query"
        mock_graphql_get.return_value = {
            "data": {
                "result": {
                    "id": "ec1",
                    "title": "Editorial Collection",
                    "items": {"pageInfo": {"hasNextPage": False}, "nodes": []},
                }
            }
        }

        client = AudiothekClient()
        result = client.get_collection_title("ec1")

        assert result == "Editorial Collection"

    @patch.object(AudiothekClient, '_graphql_get')
    @patch('audiothek.client.load_graphql_query')
    def test_find_program_sets_by_editorial_category_id(self, mock_load_query: Mock, mock_graphql_get: Mock) -> None:
        """Test finding program sets by editorial category ID."""
        mock_load_query.return_value = "query"
        mock_graphql_get.return_value = {
            "data": {
                "result": {
                    "nodes": [
                        {"id": "1", "title": "Program 1"},
                        {"id": "2", "title": "Program 2"}
                    ],
                    "pageInfo": {"hasNextPage": False}
                }
            }
        }

        client = AudiothekClient()
        result = client.find_program_sets_by_editorial_category_id("cat123", limit=10)

        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "2"
        mock_load_query.assert_called_once_with("ProgramSetsByEditorialCategoryId.graphql")
        mock_graphql_get.assert_called_once_with("query", {"editorialCategoryId": "cat123", "offset": 0, "count": 10}, "ProgramSetsByEditorialCategoryId")

    @patch.object(AudiothekClient, '_graphql_get')
    @patch('audiothek.client.load_graphql_query')
    def test_find_editorial_collections_by_editorial_category_id(self, mock_load_query: Mock, mock_graphql_get: Mock) -> None:
        """Test finding editorial collections by editorial category ID."""
        mock_load_query.return_value = "query"
        mock_graphql_get.return_value = {
            "data": {
                "result": {
                    "sections": [
                        {
                            "nodes": [
                                {"id": "1", "title": "Collection 1"},
                                {"id": "2", "title": "Collection 2"}
                            ]
                        }
                    ]
                }
            }
        }

        client = AudiothekClient()
        result = client.find_editorial_collections_by_editorial_category_id("cat123", limit=10)

        assert len(result) == 2
        assert result[0]["id"] == "1"
        assert result[1]["id"] == "2"
        mock_load_query.assert_called_once_with("EditorialCategoryCollections.graphql")
        # Should be called twice due to pagination logic (first call, then check if more needed)
        assert mock_graphql_get.call_count >= 1
        # Check first call parameters
        first_call = mock_graphql_get.call_args_list[0]
        assert first_call[0] == ("query", {"id": "cat123", "offset": 0, "count": 10}, "EditorialCategoryCollections")

    def test_load_graphql_query(self, tmp_path: Path) -> None:
        """Test loading GraphQL query from file."""

    @patch.object(AudiothekClient, 'get_episode_title')
    @patch.object(AudiothekClient, 'get_program_set_title')
    def test_get_title_episode(self, mock_program_title: Mock, mock_episode_title: Mock) -> None:
        """Test getting title for episode resource."""
        mock_episode_title.return_value = "Episode Title"

        client = AudiothekClient()
        result = client.get_title("episode123", "episode")

        assert result == "Episode Title"
        mock_episode_title.assert_called_once_with("episode123")
        mock_program_title.assert_not_called()

    @patch.object(AudiothekClient, 'get_episode_title')
    @patch.object(AudiothekClient, 'get_program_set_title')
    def test_get_title_program(self, mock_program_title: Mock, mock_episode_title: Mock) -> None:
        """Test getting title for program resource."""
        mock_program_title.return_value = "Program Title"

        client = AudiothekClient()
        result = client.get_title("program123", "program")

        assert result == "Program Title"
        mock_program_title.assert_called_once_with("program123")
        mock_episode_title.assert_not_called()

    @patch.object(AudiothekClient, 'get_episode_title')
    @patch.object(AudiothekClient, 'get_collection_title')
    def test_get_title_collection(self, mock_collection_title: Mock, mock_episode_title: Mock) -> None:
        """Test getting title for collection resource."""
        mock_collection_title.return_value = "Collection Title"

        client = AudiothekClient()
        result = client.get_title("collection123", "collection")

        assert result == "Collection Title"
        mock_collection_title.assert_called_once_with("collection123")
        mock_episode_title.assert_not_called()

    @patch.object(AudiothekClient, 'get_collection_title')
    @patch.object(AudiothekClient, 'get_episode_title')
    @patch.object(AudiothekClient, 'get_program_set_title')
    def test_get_title_unknown_type(self, mock_program_title: Mock, mock_episode_title: Mock, mock_collection_title: Mock) -> None:
        """Test getting title for unknown resource type."""
        mock_episode_title.return_value = None
        mock_program_title.return_value = None

        client = AudiothekClient()
        result = client.get_title("unknown123", "unknown")

        assert result is None
        mock_episode_title.assert_not_called()
        mock_program_title.assert_not_called()
        mock_collection_title.assert_not_called()

    @patch.object(AudiothekClient, 'get_episode_title')
    @patch.object(AudiothekClient, 'get_program_set_title')
    def test_get_title_episode_none(self, mock_program_title: Mock, mock_episode_title: Mock) -> None:
        """Test getting title for episode when episode returns None."""
        mock_episode_title.return_value = None

        client = AudiothekClient()
        result = client.get_title("episode123", "episode")

        assert result is None
        mock_episode_title.assert_called_once_with("episode123")
        mock_program_title.assert_not_called()

    @patch.object(AudiothekClient, 'get_episode_title')
    @patch.object(AudiothekClient, 'get_program_set_title')
    def test_get_title_program_none(self, mock_program_title: Mock, mock_episode_title: Mock) -> None:
        """Test getting title for program when program returns None."""
        mock_program_title.return_value = None

        client = AudiothekClient()
        result = client.get_title("program123", "program")

        assert result is None
        mock_program_title.assert_called_once_with("program123")
        mock_episode_title.assert_not_called()

    @patch('requests.Session.get')
    def test_stream_audio_to_file_success(self, mock_get: Mock, tmp_path: Path) -> None:
        """Test successful audio streaming to file."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"valid audio content" * 1000]  # Large enough to pass validation
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = AudiothekClient()
        target = tmp_path / "audio.mp3"
        result = client._stream_audio_to_file("http://example.com/audio.mp3", str(target))

        assert result is True
        assert target.read_bytes() == b"valid audio content" * 1000
        assert not (tmp_path / "audio.mp3.part").exists()
        mock_get.assert_called_once_with("http://example.com/audio.mp3", timeout=30, stream=True)

    @patch('requests.Session.get')
    def test_stream_audio_to_file_404(self, mock_get: Mock, tmp_path: Path) -> None:
        """Test audio streaming with 404 error."""
        mock_response = Mock()
        mock_response.status_code = 404
        error = requests.HTTPError("404 Not Found")
        error.response = mock_response
        mock_get.side_effect = error

        client = AudiothekClient()
        target = tmp_path / "audio.mp3"
        result = client._stream_audio_to_file("http://example.com/audio.mp3", str(target))

        assert result is False
        assert not target.exists()

    @patch('requests.Session.get')
    def test_stream_audio_to_file_http_error(self, mock_get: Mock, tmp_path: Path) -> None:
        """Test audio streaming with non-404 HTTP error."""
        mock_response = Mock()
        mock_response.status_code = 500
        error = requests.HTTPError("500 Server Error")
        error.response = mock_response
        mock_get.side_effect = error

        client = AudiothekClient()

        with pytest.raises(DownloadError):
            client._stream_audio_to_file("http://example.com/audio.mp3", str(tmp_path / "audio.mp3"))

    @patch('requests.Session.get')
    def test_stream_audio_to_file_small_error_response(self, mock_get: Mock, tmp_path: Path) -> None:
        """Test audio streaming with small error response."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"error: file not found"]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = AudiothekClient()
        target = tmp_path / "audio.mp3"
        result = client._stream_audio_to_file("http://example.com/audio.mp3", str(target))

        assert result is False
        assert not target.exists()

    @patch('requests.Session.get')
    def test_stream_audio_to_file_small_valid_response(self, mock_get: Mock, tmp_path: Path) -> None:
        """Test audio streaming with small but valid response."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"valid audio content but small"]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = AudiothekClient()
        target = tmp_path / "audio.mp3"
        result = client._stream_audio_to_file("http://example.com/audio.mp3", str(target))

        assert result is True
        assert target.read_bytes() == b"valid audio content but small"

    @patch('requests.Session.get')
    def test_stream_audio_to_file_empty_response(self, mock_get: Mock, tmp_path: Path) -> None:
        """An empty response body must be treated as unavailable audio."""
        mock_response = Mock()
        mock_response.iter_content.return_value = []
        mock_response.content = b""
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = AudiothekClient()
        target = tmp_path / "audio.mp3"
        result = client._stream_audio_to_file("http://example.com/audio.mp3", str(target))

        assert result is False
        assert not target.exists()

    @patch("audiothek.client.time.sleep")
    @patch("requests.Session.get")
    def test_stream_audio_to_file_retries_incomplete_read_then_succeeds(self, mock_get: Mock, mock_sleep: Mock, tmp_path: Path) -> None:
        """Retry same URL on transient incomplete-read errors."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"valid audio content" * 1000]
        mock_response.raise_for_status.return_value = None

        incomplete_error = requests.ConnectionError(
            "Connection broken: IncompleteRead(16777216 bytes read, 52616056 more expected)"
        )
        mock_get.side_effect = [incomplete_error, mock_response]

        client = AudiothekClient()
        target = tmp_path / "audio.mp3"
        result = client._stream_audio_to_file("http://example.com/audio.mp3", str(target))

        assert result is True
        assert target.read_bytes() == b"valid audio content" * 1000
        assert mock_get.call_count == 2
        mock_sleep.assert_called_once_with(0.5)

    @patch("audiothek.client.time.sleep")
    @patch("requests.Session.get")
    def test_stream_audio_to_file_incomplete_read_exhausted(self, mock_get: Mock, mock_sleep: Mock, tmp_path: Path) -> None:
        """Raise DownloadError after exhausting retry attempts for incomplete reads."""
        incomplete_error = requests.ConnectionError(
            "Connection broken: IncompleteRead(16777216 bytes read, 52616056 more expected)"
        )
        mock_get.side_effect = [incomplete_error, incomplete_error, incomplete_error]

        client = AudiothekClient()
        with pytest.raises(DownloadError):
            client._stream_audio_to_file("http://example.com/audio.mp3", str(tmp_path / "audio.mp3"))

        assert mock_get.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("audiothek.client.os.replace")
    @patch('requests.Session.get')
    def test_stream_audio_to_file_replace_failure_removes_part_file(self, mock_get: Mock, mock_replace: Mock, tmp_path: Path) -> None:
        """A failed atomic rename must not leave a stale .part file behind."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"valid audio content" * 1000]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response
        mock_replace.side_effect = OSError("rename failed")

        client = AudiothekClient()
        target = tmp_path / "audio.mp3"

        with pytest.raises(OSError, match="rename failed"):
            client._stream_audio_to_file("http://example.com/audio.mp3", str(target))

        assert not target.exists()
        assert not Path(f"{target}.part").exists()

    @patch('requests.Session.get')
    def test_stream_audio_to_file_leaves_no_part_file_on_failure(self, mock_get: Mock, tmp_path: Path) -> None:
        """Failure paths must never leave a .part file behind."""
        mock_response = Mock()
        mock_response.iter_content.return_value = [b"error: not found"]
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        client = AudiothekClient()
        target = tmp_path / "audio.mp3"
        result = client._stream_audio_to_file("http://example.com/audio.mp3", str(target))

        assert result is False
        assert not Path(f"{target}.part").exists()

    @patch.object(AudiothekClient, '_stream_audio_to_file')
    def test_download_audio_to_file_success(self, mock_stream: Mock) -> None:
        """Test successful audio download to file."""
        mock_stream.return_value = True

        client = AudiothekClient()
        result = client._download_audio_to_file("http://example.com/audio.mp3", "/tmp/audio.mp3")

        assert result == "http://example.com/audio.mp3"
        mock_stream.assert_called_once_with("http://example.com/audio.mp3", "/tmp/audio.mp3")

    @patch.object(AudiothekClient, '_stream_audio_to_file')
    def test_download_audio_to_file_404_with_fallback(self, mock_stream: Mock) -> None:
        """Test audio download with 404 and successful fallback."""
        mock_stream.side_effect = [False, True]

        client = AudiothekClient()
        result = client._download_audio_to_file("http://example.com/audio.mp3", "/tmp/audio.mp3", "http://example.com/fallback.mp3")

        assert result == "http://example.com/fallback.mp3"
        assert mock_stream.call_count == 2
        mock_stream.assert_any_call("http://example.com/audio.mp3", "/tmp/audio.mp3")
        mock_stream.assert_any_call("http://example.com/fallback.mp3", "/tmp/audio.mp3")

    @patch.object(AudiothekClient, '_stream_audio_to_file')
    def test_download_audio_to_file_both_fail(self, mock_stream: Mock) -> None:
        """Test audio download when both primary and fallback fail."""
        mock_stream.return_value = False

        client = AudiothekClient()
        result = client._download_audio_to_file("http://example.com/audio.mp3", "/tmp/audio.mp3", "http://example.com/fallback.mp3")

        assert result is None
        assert mock_stream.call_count == 2

    @patch.object(AudiothekClient, '_stream_audio_to_file')
    def test_download_audio_to_file_fallback_exception(self, mock_stream: Mock) -> None:
        """Test audio download when fallback throws exception."""
        mock_stream.side_effect = [False, Exception("Network error")]

        client = AudiothekClient()
        result = client._download_audio_to_file("http://example.com/audio.mp3", "/tmp/audio.mp3", "http://example.com/fallback.mp3")

        assert result is None
        assert mock_stream.call_count == 2

    @patch.object(AudiothekClient, '_stream_audio_to_file')
    def test_download_audio_to_file_no_fallback(self, mock_stream: Mock) -> None:
        """Test audio download without fallback URL."""
        mock_stream.return_value = True

        client = AudiothekClient()
        result = client._download_audio_to_file("http://example.com/audio.mp3", "/tmp/audio.mp3")

        assert result == "http://example.com/audio.mp3"
        mock_stream.assert_called_once_with("http://example.com/audio.mp3", "/tmp/audio.mp3")

    @patch.object(AudiothekClient, "_stream_audio_to_file")
    def test_download_audio_to_file_retries_all_fallback_urls(self, mock_stream: Mock) -> None:
        """Test audio download retries through ordered fallback URL list."""
        mock_stream.side_effect = [False, False, True]

        client = AudiothekClient()
        result = client._download_audio_to_file(
            "http://example.com/audio.mp3",
            "/tmp/audio.mp3",
            fallback_urls=[
                "http://example.com/fallback-1.mp3",
                "http://example.com/fallback-2.mp3",
            ],
        )

        assert result == "http://example.com/fallback-2.mp3"
        assert mock_stream.call_count == 3
        mock_stream.assert_any_call("http://example.com/audio.mp3", "/tmp/audio.mp3")
        mock_stream.assert_any_call("http://example.com/fallback-1.mp3", "/tmp/audio.mp3")
        mock_stream.assert_any_call("http://example.com/fallback-2.mp3", "/tmp/audio.mp3")

    @patch.object(AudiothekClient, "_stream_audio_to_file")
    def test_download_audio_to_file_all_candidates_fail(self, mock_stream: Mock) -> None:
        """Test audio download returns None when all URL candidates fail."""
        mock_stream.return_value = False

        client = AudiothekClient()
        result = client._download_audio_to_file(
            "http://example.com/audio.mp3",
            "/tmp/audio.mp3",
            fallback_urls=["http://example.com/fallback-1.mp3", "http://example.com/fallback-2.mp3"],
        )

        assert result is None
        assert mock_stream.call_count == 3


@patch.object(AudiothekClient, "_graphql_get")
@patch("audiothek.client.load_graphql_query")
def test_get_episode_data_handles_null_data(mock_load_query: Mock, mock_graphql_get: Mock) -> None:
    """A GraphQL response with data: null must not crash get_episode_data."""
    mock_load_query.return_value = "query"
    mock_graphql_get.return_value = {"data": None}

    client = AudiothekClient()
    result = client.get_episode_data("ep1")

    assert result is None


@patch.object(AudiothekClient, "_graphql_get")
@patch("audiothek.client.load_graphql_query")
def test_get_program_set_data_handles_null_data(mock_load_query: Mock, mock_graphql_get: Mock) -> None:
    """A GraphQL response with data: null must not crash get_program_set_data."""
    mock_load_query.return_value = "query"
    mock_graphql_get.return_value = {"data": None}

    client = AudiothekClient()
    result = client.get_program_set_data("ps1")

    assert result is None
