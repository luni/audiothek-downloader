"""Tests for AudiothekClient."""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest
import requests

from audiothek import AudiothekClient
from audiothek.utils import load_graphql_query
from tests.conftest import GraphQLMock, MockResponse


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
    def test_download_to_file_uses_proxy(self, mock_get: Mock) -> None:
        """Test that file downloads use the configured proxy."""
        proxy_url = "http://proxy.example.com:8080"
        client = AudiothekClient(proxy=proxy_url)

        # Mock response
        mock_response = Mock()
        mock_response.content = b"test content"
        mock_get.return_value = mock_response

        # Make a file download request
        client._download_to_file("http://example.com/file.mp3", "/tmp/test.mp3")

        mock_get.assert_called_once()
        assert client._session.proxies == {"http": proxy_url, "https": proxy_url}

    def test_parse_url_with_urn_episode(self) -> None:
        """Test parsing URL with episode URN."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://audiothek.ardaudiothek.de/episode/urn:ard:episode:test123")

        assert result == ("episode", "urn:ard:episode:test123")

    def test_parse_url_with_urn_collection(self) -> None:
        """Test parsing URL with collection URN."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://audiothek.ardaudiothek.de/collection/urn:ard:page:test123")

        assert result == ("collection", "urn:ard:page:test123")

    def test_parse_url_with_urn_program(self) -> None:
        """Test parsing URL with program URN."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://audiothek.ardaudiothek.de/program/urn:ard:show:test123")

        assert result == ("program", "urn:ard:show:test123")

    def test_parse_url_with_numeric_id(self) -> None:
        """Test parsing URL with numeric ID."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://audiothek.ardaudiothek.de/program/123456")

        assert result == ("program", "123456")

    def test_parse_url_invalid(self) -> None:
        """Test parsing invalid URL."""
        client = AudiothekClient()
        result = AudiothekClient.parse_url("https://example.com/invalid")

        assert result is None

    def test_determine_resource_type_from_id_episode(self) -> None:
        """Test determining resource type from episode ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("urn:ard:episode:test123")

        assert result == ("episode", "urn:ard:episode:test123")

    def test_determine_resource_type_from_id_collection(self) -> None:
        """Test determining resource type from collection ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("urn:ard:page:test123")

        assert result == ("collection", "urn:ard:page:test123")

    def test_determine_resource_type_from_id_program(self) -> None:
        """Test determining resource type from program ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("urn:ard:show:test123")

        assert result == ("program", "urn:ard:show:test123")

    def test_determine_resource_type_from_id_numeric(self) -> None:
        """Test determining resource type from numeric ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("123456")

        assert result == ("program", "123456")

    def test_determine_resource_type_from_id_alphanumeric(self) -> None:
        """Test determining resource type from alphanumeric ID."""
        client = AudiothekClient()
        result = AudiothekClient.determine_resource_type_from_id("ps1")

        assert result == ("program", "ps1")

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
        mock_graphql_get.assert_called_once_with("query", {"id": "urn:ard:episode:test123"})

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
        mock_graphql_get.assert_called_once_with("query", {"id": "123456", "offset": 0, "count": 1})

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
        mock_graphql_get.assert_called_once_with("query", {"editorialCategoryId": "cat123", "offset": 0, "count": 10})

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
        assert first_call[0] == ("query", {"id": "cat123", "offset": 0, "count": 10})

    def test_load_graphql_query(self, tmp_path: Path) -> None:
        """Test loading GraphQL query from file."""
