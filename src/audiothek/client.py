"""Audiothek API client for handling HTTP requests and GraphQL operations."""

import json
import logging
import re
from typing import Any
from urllib.parse import urlparse

import requests

from .cache import GraphQLCache
from .exceptions import DownloadError, GraphQLError
from .models import EpisodeMetadata, ResourceInfo
from .utils import REQUEST_TIMEOUT, load_graphql_query


class AudiothekClient:
    """Client for ARD Audiothek API operations."""

    def __init__(
        self,
        proxy: str | None = None,
        *,
        cache: GraphQLCache | None = None,
    ) -> None:
        """Initialize the API client.

        Args:
            proxy: Proxy URL (e.g. "http://proxy.example.com:8080" or "socks5://proxy.example.com:1080")
            cache: Optional GraphQL cache instance.

        """
        self.logger = logging.getLogger(__name__)
        self._session = requests.Session()
        self._base_url = "https://api.ardaudiothek.de/graphql"
        self._cache = cache or GraphQLCache()

        # Configure proxy if provided
        if proxy:
            proxies = {"http": proxy, "https": proxy}
            self._session.proxies = proxies

    def _graphql_get(self, query: str, variables: dict[str, Any], query_name: str = "") -> dict[str, Any]:
        """Execute GraphQL query.

        Args:
            query: GraphQL query string
            variables: Variables for the query
            query_name: Name of the query for error reporting

        Returns:
            JSON response as dictionary

        Raises:
            GraphQLError: If the query fails

        """
        cached = self._cache.get(query, variables, query_name)
        if cached is not None:
            self.logger.debug("Cache hit for %s", query_name or "unknown")
            return cached

        try:
            response = self._session.get(
                self._base_url,
                params={"query": query, "variables": json.dumps(variables)},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            data = response.json()
            self._cache.set(query, variables, data, query_name)
            return data
        except requests.RequestException as e:
            error_msg = f"GraphQL request failed: {str(e)}"
            self.logger.error(error_msg)
            raise GraphQLError(query_name or "unknown", variables, error_msg) from e
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON response: {str(e)}"
            self.logger.error(error_msg)
            raise GraphQLError(query_name or "unknown", variables, error_msg) from e

    def _download_to_file(self, url: str, file_path: str, *, check_status: bool = False) -> None:
        """Download content from URL to file.

        Args:
            url: URL to download from
            file_path: Path to save the file to
            check_status: Whether to check the HTTP status code

        Raises:
            DownloadError: If the download fails

        """
        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT)
            if check_status:
                response.raise_for_status()
            with open(file_path, "wb") as f:
                f.write(response.content)
        except requests.RequestException as e:
            status_code = None
            if hasattr(e, "response") and e.response is not None and hasattr(e.response, "status_code"):
                status_code = e.response.status_code
            error_msg = f"Failed to download {url}: {str(e)}"
            self.logger.error(error_msg)
            raise DownloadError(url, status_code, error_msg) from e
        except OSError as e:
            error_msg = f"Failed to write to {file_path}: {str(e)}"
            self.logger.error(error_msg)
            raise DownloadError(url, None, error_msg) from e

    def _fetch_and_validate_audio(self, url: str) -> bytes | None:
        """Fetch audio content and validate it's not an error response.

        Args:
            url: The URL to fetch

        Returns:
            The content bytes if valid audio, None if 404 or soft 404 (error text)

        Raises:
            DownloadError: For HTTP errors other than 404

        """
        try:
            response = self._session.get(url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.HTTPError as e:
            if e.response.status_code == 404:
                self.logger.warning("Audio file not found (404): %s", url)
                return None
            self.logger.error("HTTP error downloading audio: %s - %s", url, e)
            raise DownloadError(url, e.response.status_code, str(e)) from e

        # Check if content is likely an error response rather than audio
        content = response.content
        if len(content) < 1000:  # Very small files are likely error responses
            content_text = content.decode("utf-8", errors="ignore").lower()
            if any(error_indicator in content_text for error_indicator in ["not found", "error", "deleted", "removed", "unavailable", "404"]):
                self.logger.warning("Audio file appears to be unavailable (error response): %s - Content: %s", url, content_text[:100])
                return None

        return content

    def _download_audio_to_file(self, url: str, file_path: str, fallback_url: str | None = None) -> bool:
        """Download audio content from URL to file with validation.

        Args:
            url: The URL to download from
            file_path: The local file path to save to
            fallback_url: Optional fallback URL to try if primary URL fails with 404

        Returns:
            True if download was successful, False if file was not found or invalid

        """
        content = self._fetch_and_validate_audio(url)

        if content is None:
            if fallback_url and fallback_url != url:
                self.logger.info("Trying fallback URL: %s", fallback_url)
                try:
                    content = self._fetch_and_validate_audio(fallback_url)
                    if content:
                        self.logger.info("Successfully downloaded from fallback URL: %s", fallback_url)
                    else:
                        self.logger.warning("Fallback URL also appears to be unavailable: %s", fallback_url)
                except Exception as e:
                    self.logger.error("Error downloading fallback audio: %s - %s", fallback_url, e)
                    content = None

        if content is None:
            return False

        # Save the valid audio content
        try:
            with open(file_path, "wb") as f:
                f.write(content)
            return True
        except OSError as e:
            self.logger.error("Failed to write audio file: %s - %s", file_path, e)
            return False

    def _get_content_length(self, url: str) -> int | None:
        """Get content length from URL using HEAD request.

        Args:
            url: URL to check

        Returns:
            Content length in bytes, or None if not available

        """
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

        Args:
            url: URL to check

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

    def get_episode_data(self, episode_id: str) -> dict[str, Any] | None:
        """Get episode data from the API.

        Args:
            episode_id: Episode ID

        Returns:
            Episode data as dictionary, or None if not found

        Raises:
            GraphQLError: If the query fails

        """
        query = load_graphql_query("EpisodeQuery.graphql")
        response_json = self._graphql_get(query, {"id": episode_id}, "EpisodeQuery")

        node = response_json.get("data", {}).get("result")
        return node

    def get_episode_metadata(self, episode_id: str) -> EpisodeMetadata | None:
        """Get episode metadata.

        Args:
            episode_id: Episode ID

        Returns:
            Episode metadata, or None if not found

        Raises:
            GraphQLError: If the query fails

        """
        node = self.get_episode_data(episode_id)
        if not node:
            return None

        program_set = node.get("programSet") or {}

        # Extract audio URLs
        audio_urls = []
        audios = node.get("audios") or []
        for audio in audios:
            if isinstance(audio, dict):
                if audio.get("downloadUrl"):
                    audio_urls.append(audio["downloadUrl"])
                if audio.get("url"):
                    audio_urls.append(audio["url"])

        # Extract image URLs
        image = node.get("image") or {}
        image_url = image.get("url", "").replace("{width}", "2000") if image.get("url") else ""
        image_url_x1 = image.get("url1X1", "").replace("{width}", "2000") if image.get("url1X1") else ""

        return EpisodeMetadata(
            id=str(node.get("id", "")),
            title=node.get("title", ""),
            description=node.get("description"),
            summary=node.get("summary"),
            duration=node.get("duration"),
            publish_date=node.get("publishDate"),
            program_set_id=program_set.get("id"),
            program_set_title=program_set.get("title"),
            program_set_path=program_set.get("path"),
            audio_urls=audio_urls,
            image_url=image_url,
            image_url_x1=image_url_x1,
        )

    def get_episode_title(self, episode_id: str) -> str | None:
        """Get program set title from episode.

        Args:
            episode_id: Episode ID

        Returns:
            Program set title, or None if not found

        """
        try:
            metadata = self.get_episode_metadata(episode_id)
            return metadata.program_set_title if metadata else None
        except Exception as e:
            self.logger.error("Error getting episode title: %s", e)
            return None

    def get_program_set_data(self, program_id: str, offset: int = 0, count: int = 1) -> dict[str, Any] | None:
        """Get program set data from the API.

        Args:
            program_id: Program set ID
            offset: Pagination offset
            count: Number of items to return

        Returns:
            Program set data as dictionary, or None if not found

        Raises:
            GraphQLError: If the query fails

        """
        query = load_graphql_query("ProgramSetEpisodesQuery.graphql")
        response_json = self._graphql_get(query, {"id": program_id, "offset": offset, "count": count}, "ProgramSetEpisodesQuery")

        result = response_json.get("data", {}).get("result", {})
        return result if result else None

    def get_program_set_title(self, program_id: str) -> str | None:
        """Get program set title directly.

        Args:
            program_id: Program set ID

        Returns:
            Program set title, or None if not found

        """
        try:
            result = self.get_program_set_data(program_id)
            if not result:
                return None

            # For editorial collections, the structure is slightly different
            if "items" in result:
                items = result.get("items", {})
                nodes = items.get("nodes", []) or []
                if nodes:
                    first_node = nodes[0]
                    program_set = first_node.get("programSet") or {}
                    return program_set.get("title")

            # For direct program sets
            return result.get("title")
        except Exception as e:
            self.logger.error("Error getting program set title: %s", e)
            return None

    def get_title(self, resource_id: str, resource_type: str) -> str | None:
        """Get title for a resource based on its type.

        Args:
            resource_id: The resource ID
            resource_type: The resource type ('episode', 'program', or 'collection')

        Returns:
            The title or None if not found

        """
        if resource_type == "episode":
            return self.get_episode_title(resource_id)
        elif resource_type in ["program", "collection"]:
            return self.get_program_set_title(resource_id)
        return None

    @staticmethod
    def determine_resource_type_from_id(resource_id: str) -> ResourceInfo | None:
        """Determine resource type from ID pattern.

        Args:
            resource_id: The ID to analyze

        Returns:
            ResourceInfo object with resource type and ID, or None if not recognized

        """
        if resource_id.startswith("urn:ard:episode:"):
            return ResourceInfo("episode", resource_id)
        if resource_id.startswith("urn:ard:page:"):
            return ResourceInfo("collection", resource_id)
        if resource_id.startswith("urn:ard:show:"):
            return ResourceInfo("program", resource_id)
        # fallback: treat other urns as program sets
        if resource_id.startswith("urn:ard:"):
            return ResourceInfo("program", resource_id)
        # numeric IDs are typically programs
        if resource_id.isdigit():
            return ResourceInfo("program", resource_id)
        # alphanumeric IDs (like "ps1") are also treated as programs
        if re.match(r"^[a-zA-Z0-9]+$", resource_id):
            return ResourceInfo("program", resource_id)
        return None

    @staticmethod
    def parse_url(url: str) -> ResourceInfo | None:
        """Parse Audiothek URL and return resource info.

        Args:
            url: The URL to parse

        Returns:
            ResourceInfo object with resource type and ID, or None if not recognized

        """
        # Validate URL
        try:
            parsed_url = urlparse(url)
            if not parsed_url.netloc or not parsed_url.path:
                return None
        except Exception:
            return None

        # Extract URN or numeric ID
        urn_match = re.search(r"/(urn:ard:[^/]+)/?$", url)
        if urn_match:
            resource_id = urn_match.group(1)
            resource_info = AudiothekClient.determine_resource_type_from_id(resource_id)
            return resource_info

        numeric_match = re.search(r"/(\d+)/?$", url)
        if numeric_match:
            resource_id = numeric_match.group(1)
            return ResourceInfo("program", resource_id)

        return None

    def fetch_program_set_episodes(self, program_id: str, limit: int = 1000) -> list[dict[str, Any]]:
        """Fetch all episodes for a program set using pagination.

        Args:
            program_id: Program set ID
            limit: Maximum number of episodes to fetch

        Returns:
            List of episode data dictionaries

        Raises:
            GraphQLError: If the query fails

        """
        query = load_graphql_query("ProgramSetEpisodesQuery.graphql")

        nodes: list[dict[str, Any]] = []
        offset = 0
        count = 24  # API default page size

        while True:
            remaining = max(0, limit - len(nodes))
            if remaining == 0:
                break

            variables = {"id": program_id, "offset": offset, "count": min(count, remaining)}
            response_json = self._graphql_get(query, variables, "ProgramSetEpisodesQuery")

            result = response_json.get("data", {}).get("result", {})
            if not result:
                break

            items = result.get("items", {}) or {}
            page_nodes = items.get("nodes", []) or []

            if not page_nodes:
                break

            nodes.extend(page_nodes)

            page_info = items.get("pageInfo", {}) or {}
            if not page_info.get("hasNextPage"):
                break

            offset += count

        return nodes

    def fetch_editorial_collection(self, collection_id: str, limit: int = 1000) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Fetch all nodes for an editorial collection using pagination.

        Args:
            collection_id: Collection ID
            limit: Maximum number of nodes to fetch

        Returns:
            Tuple of (nodes list, collection_data dict)

        Raises:
            GraphQLError: If the query fails

        """
        query = load_graphql_query("editorialCollection.graphql")

        nodes: list[dict[str, Any]] = []
        collection_data: dict[str, Any] | None = None
        offset = 0
        count = 24  # API default page size

        while True:
            remaining = max(0, limit - len(nodes))
            if remaining == 0:
                break

            variables = {"id": collection_id, "offset": offset, "count": min(count, remaining)}
            response_json = self._graphql_get(query, variables, "editorialCollection")

            results = response_json.get("data", {}).get("result", {})
            if not results:
                break

            # Store collection data on first iteration
            if collection_data is None:
                collection_data = results

            items = results.get("items", {}) or {}
            page_nodes = items.get("nodes", []) or []

            if not page_nodes:
                break

            nodes.extend(page_nodes)

            page_info = items.get("pageInfo", {}) or {}
            if not page_info.get("hasNextPage"):
                break

            offset += count

        return nodes, collection_data or {}

    def find_program_sets_by_editorial_category_id(self, editorial_category_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Find program sets by editorial category ID.

        Args:
            editorial_category_id: Editorial category ID
            limit: Maximum number of program sets to fetch

        Returns:
            List of program set data dictionaries

        Raises:
            GraphQLError: If the query fails

        """
        query = load_graphql_query("ProgramSetsByEditorialCategoryId.graphql")

        nodes: list[dict[str, Any]] = []
        offset = 0
        count = 24  # API default page size

        while True:
            remaining = max(0, limit - len(nodes))
            if remaining == 0:
                break

            variables = {"editorialCategoryId": editorial_category_id, "offset": offset, "count": min(count, remaining)}
            response_json = self._graphql_get(query, variables, "ProgramSetsByEditorialCategoryId")

            result = response_json.get("data", {}).get("result") or {}
            page_nodes = result.get("nodes") or []

            if not page_nodes:
                break

            nodes.extend(page_nodes)

            page_info = result.get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                break

            offset += count

        return nodes

    def find_editorial_collections_by_editorial_category_id(self, editorial_category_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Find editorial collections by editorial category ID.

        Args:
            editorial_category_id: Editorial category ID
            limit: Maximum number of collections to fetch

        Returns:
            List of collection data dictionaries

        Raises:
            GraphQLError: If the query fails

        """
        query = load_graphql_query("EditorialCategoryCollections.graphql")

        collections_by_id: dict[str, dict[str, Any]] = {}
        offset = 0
        count = 24  # API default page size

        while True:
            remaining = max(0, limit - len(collections_by_id))
            if remaining == 0:
                break

            before_count = len(collections_by_id)

            variables = {"id": editorial_category_id, "offset": offset, "count": min(count, remaining)}
            response_json = self._graphql_get(query, variables, "EditorialCategoryCollections")

            result = response_json.get("data", {}).get("result") or {}
            sections = result.get("sections") or []

            if not sections:
                break

            for section in sections:
                section_nodes = (section or {}).get("nodes") or []
                if not section_nodes:
                    continue

                for node in section_nodes:
                    node_id = (node or {}).get("id")
                    if not node_id:
                        continue

                    collections_by_id[str(node_id)] = node

            # If no new collections were found, we're done
            if len(collections_by_id) == before_count:
                break

            offset += count

        return list(collections_by_id.values())
