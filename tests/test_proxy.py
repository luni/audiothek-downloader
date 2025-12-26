"""Tests for proxy functionality."""

import pytest
from unittest.mock import Mock, patch

from audiothek import AudiothekClient, AudiothekDownloader


class TestProxySupport:
    """Test cases for proxy support in Audiothek classes."""

    def test_downloader_without_proxy_uses_default_session(self) -> None:
        """Test that downloader without proxy creates a client without proxy configuration."""
        downloader = AudiothekDownloader()

        # Check that no proxies are configured in the client
        assert downloader.client._session.proxies == {}

    def test_downloader_with_http_proxy_configures_session(self) -> None:
        """Test that downloader with HTTP proxy correctly configures client."""
        proxy_url = "http://proxy.example.com:8080"
        downloader = AudiothekDownloader(proxy=proxy_url)

        expected_proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        assert downloader.client._session.proxies == expected_proxies

    def test_downloader_with_https_proxy_configures_session(self) -> None:
        """Test that downloader with HTTPS proxy correctly configures client."""
        proxy_url = "https://secure-proxy.example.com:3128"
        downloader = AudiothekDownloader(proxy=proxy_url)

        expected_proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        assert downloader.client._session.proxies == expected_proxies

    def test_downloader_with_socks5_proxy_configures_session(self) -> None:
        """Test that downloader with SOCKS5 proxy correctly configures client."""
        proxy_url = "socks5://socks-proxy.example.com:1080"
        downloader = AudiothekDownloader(proxy=proxy_url)

        expected_proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        assert downloader.client._session.proxies == expected_proxies

    def test_downloader_with_authenticated_proxy_configures_session(self) -> None:
        """Test that downloader with authenticated proxy correctly configures client."""
        proxy_url = "http://user:password@proxy.example.com:8080"
        downloader = AudiothekDownloader(proxy=proxy_url)

        expected_proxies = {
            "http": proxy_url,
            "https": proxy_url,
        }
        assert downloader.client._session.proxies == expected_proxies

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

    def test_proxy_none_uses_no_proxy(self) -> None:
        """Test that passing None as proxy uses no proxy configuration."""
        downloader = AudiothekDownloader(proxy=None)

        # Check that no proxies are configured
        assert downloader.client._session.proxies == {}

    def test_proxy_empty_string_uses_no_proxy(self) -> None:
        """Test that passing empty string as proxy uses no proxy configuration."""
        downloader = AudiothekDownloader(proxy="")

        # Check that no proxies are configured
        assert downloader.client._session.proxies == {}

    @patch('requests.Session.get')
    def test_proxy_used_in_actual_download_workflow(self, mock_get: Mock, tmp_path) -> None:
        """Test that proxy is used throughout the download workflow."""
        proxy_url = "http://proxy.example.com:8080"
        downloader = AudiothekDownloader(proxy=proxy_url)

        # Mock GraphQL response
        mock_graphql_response = Mock()
        mock_graphql_response.json.return_value = {
            "data": {
                "result": {
                    "id": "test_episode",
                    "title": "Test Episode",
                    "description": "Test Description",
                    "summary": "Test Summary",
                    "duration": 1800,
                    "publishDate": "2023-01-01T00:00:00Z",
                    "image": {"url": "http://example.com/image_{width}.jpg"},
                    "programSet": {"id": "test_program", "title": "Test Program"},
                    "audios": [{"downloadUrl": "http://example.com/audio.mp3"}]
                }
            }
        }

        # Mock file download response
        mock_file_response = Mock()
        mock_file_response.content = b"test audio content"
        mock_file_response.raise_for_status.return_value = None

        # Configure mock to return different responses based on URL
        def side_effect(*args, **kwargs):
            if "graphql" in args[0]:
                return mock_graphql_response
            else:
                return mock_file_response

        mock_get.side_effect = side_effect

        # Perform download
        downloader._download_single_episode("test_episode", str(tmp_path))

        assert mock_get.call_count >= 2  # GraphQL + download
        assert downloader.client._session.proxies == {"http": proxy_url, "https": proxy_url}
