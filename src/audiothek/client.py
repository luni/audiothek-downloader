"""Audiothek API client for handling HTTP requests and GraphQL operations."""

import json
import logging
import re
from typing import Any

import requests

from .utils import REQUEST_TIMEOUT, load_graphql_query


class AudiothekClient:
    """Client for ARD Audiothek API operations."""

    def __init__(self, proxy: str | None = None) -> None:
        """Initialize the API client.

        Args:
            proxy: Proxy URL (e.g. "http://proxy.example.com:8080" or "socks5://proxy.example.com:1080")

        """
        self.logger = logging.getLogger(__name__)
        self._session = requests.Session()

        # Configure proxy if provided
        if proxy:
            proxies = {"http": proxy, "https": proxy}
            self._session.proxies = proxies

    def _graphql_get(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Execute GraphQL query."""
        response = self._session.get(
            "https://api.ardaudiothek.de/graphql",
            params={"query": query, "variables": json.dumps(variables)},
            timeout=REQUEST_TIMEOUT,
        )
        return response.json()

    def _download_to_file(self, url: str, file_path: str, *, check_status: bool = False) -> None:
        """Download content from URL to file."""
        response = self._session.get(url, timeout=REQUEST_TIMEOUT)
        if check_status:
            response.raise_for_status()
        with open(file_path, "wb") as f:
            f.write(response.content)

    def _download_audio_to_file(self, url: str, file_path: str) -> bool:
        """Download audio content from URL to file with validation.

        Args:
            url: The URL to download from
            file_path: The local file path to save to

        Returns:
            True if download was successful, False if file was not found or invalid

        Raises:
            requests.HTTPError: For HTTP errors other than 404

        """
        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                self.logger.warning("Audio file not found (404): %s", url)
                return False
            else:
                self.logger.error("HTTP error downloading audio: %s - %s", url, e)
                raise

        # Check if content is likely an error response rather than audio
        content = response.content
        if len(content) < 1000:  # Very small files are likely error responses
            content_text = content.decode("utf-8", errors="ignore").lower()
            if any(error_indicator in content_text for error_indicator in ["not found", "error", "deleted", "removed", "unavailable", "404"]):
                self.logger.warning("Audio file appears to be unavailable (error response): %s - Content: %s", url, content_text[:100])
                return False

        # Save the valid audio content
        with open(file_path, "wb") as f:
            f.write(content)
        return True

    def _get_content_length(self, url: str) -> int | None:
        """Get content length from URL using HEAD request."""
        try:
            response = self._session.head(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return int(response.headers.get("content-length", 0))
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                self.logger.warning("Audio file not found (404) during content length check: %s", url)
            return None
        except Exception:
            return None

    def _check_file_availability(self, url: str) -> tuple[bool, int | None]:
        """Check if file is available and get content length.

        Returns:
            Tuple of (is_available, content_length_or_none)
            is_available is False for 404s, True for other cases

        """
        try:
            response = self._session.head(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return True, int(response.headers.get("content-length", 0))
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                self.logger.warning("Audio file not found (404) during availability check: %s", url)
                return False, None
            else:
                # Other HTTP errors - file might be available, just can't check length
                return True, None
        except Exception:
            # Network errors - assume file might be available
            return True, None

    def find_program_sets_by_editorial_category_id(self, editorial_category_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Find program sets by editorial category ID."""
        query = load_graphql_query("ProgramSetsByEditorialCategoryId.graphql")

        nodes: list[dict[str, Any]] = []
        offset = 0
        count = 24
        while True:
            remaining = max(0, limit - len(nodes))
            if remaining == 0:
                break

            variables = {"editorialCategoryId": editorial_category_id, "offset": offset, "count": min(count, remaining)}
            response_json = self._graphql_get(query, variables)
            result = response_json.get("data", {}).get("result") or {}
            page_nodes = result.get("nodes") or []
            if isinstance(page_nodes, list):
                nodes.extend(page_nodes)

            page_info = result.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break
            offset += count

        return nodes

    def find_editorial_collections_by_editorial_category_id(self, editorial_category_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Find editorial collections by editorial category ID."""
        query = load_graphql_query("EditorialCategoryCollections.graphql")

        collections_by_id: dict[str, dict[str, Any]] = {}
        offset = 0
        count = 24
        while True:
            remaining = max(0, limit - len(collections_by_id))
            if remaining == 0:
                break

            before_count = len(collections_by_id)

            variables = {"id": editorial_category_id, "offset": offset, "count": min(count, remaining)}
            response_json = self._graphql_get(query, variables)
            result = response_json.get("data", {}).get("result") or {}
            sections = result.get("sections") or []
            if not isinstance(sections, list) or not sections:
                break

            for section in sections:
                section_nodes = (section or {}).get("nodes") or []
                if not isinstance(section_nodes, list):
                    continue
                for node in section_nodes:
                    node_id = (node or {}).get("id")
                    if not node_id:
                        continue
                    collections_by_id[str(node_id)] = node

            if len(collections_by_id) == before_count:
                break

            offset += count

        return list(collections_by_id.values())

    def get_episode_title(self, episode_id: str) -> str | None:
        """Get program set title from episode."""
        try:
            query = load_graphql_query("EpisodeQuery.graphql")
            response_json = self._graphql_get(query, {"id": episode_id})

            node = response_json.get("data", {}).get("result")
            if node:
                program_set = node.get("programSet") or {}
                return program_set.get("title")
        except Exception as e:
            self.logger.error("Error getting episode title: %s", e)

        return None

    def get_program_set_title(self, program_id: str) -> str | None:
        """Get program set title directly."""
        try:
            query = load_graphql_query("ProgramSetEpisodesQuery.graphql")
            response_json = self._graphql_get(query, {"id": program_id, "offset": 0, "count": 1})

            result = response_json.get("data", {}).get("result", {})
            if result:
                # For editorial collections, the structure is slightly different
                if "items" in result:
                    items = result.get("items", {})
                    nodes = items.get("nodes", []) or []
                    if nodes:
                        first_node = nodes[0]
                        program_set = first_node.get("programSet") or {}
                        return program_set.get("title")
        except Exception as e:
            self.logger.error("Error getting program set title: %s", e)

        return None

    @staticmethod
    def determine_resource_type_from_id(resource_id: str) -> tuple[str, str] | None:
        """Determine resource type from ID pattern.

        Args:
            resource_id: The ID to analyze

        Returns:
            A tuple of (resource_type, id) where resource_type is one of 'episode', 'collection', or 'program'

        """
        if resource_id.startswith("urn:ard:episode:"):
            return "episode", resource_id
        if resource_id.startswith("urn:ard:page:"):
            return "collection", resource_id
        if resource_id.startswith("urn:ard:show:"):
            return "program", resource_id
        # fallback: treat other urns as program sets
        if resource_id.startswith("urn:ard:"):
            return "program", resource_id
        # numeric IDs are typically programs
        if resource_id.isdigit():
            return "program", resource_id
        # alphanumeric IDs (like "ps1") are also treated as programs
        if re.match(r"^[a-zA-Z0-9]+$", resource_id):
            return "program", resource_id
        return None

    @staticmethod
    def parse_url(url: str) -> tuple[str, str] | None:
        """Parse Audiothek URL and return (resource_type, id).

        Args:
            url: The URL to parse

        Returns:
            A tuple of (resource_type, id) where resource_type is one of 'episode', 'collection', or 'program'

        """
        urn_match = re.search(r"/(urn:ard:[^/]+)/?$", url)
        if urn_match:
            return AudiothekClient.determine_resource_type_from_id(urn_match.group(1))

        numeric_match = re.search(r"/(\d+)/?$", url)
        if numeric_match:
            return AudiothekClient.determine_resource_type_from_id(numeric_match.group(1))

        return None
