import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from .client import AudiothekClient
from .utils import load_graphql_query, sanitize_folder_name


@dataclass
class ImageMetadata:
    """Metadata for saving images and files."""

    node_id: str
    title: str
    filename: str
    program_path: str
    program_set: dict[str, Any]
    image_urls: dict[str, str]


class AudiothekDownloader:
    """ARD Audiothek downloader class."""

    def __init__(self, base_folder: str = "./output", proxy: str | None = None) -> None:
        """Initialize the downloader.

        Args:
            base_folder: Default output directory for downloaded files
            proxy: Proxy URL (e.g. "http://proxy.example.com:8080" or "socks5://proxy.example.com:1080")

        """
        self.base_folder = base_folder
        self.logger = logging.getLogger(__name__)
        self.client = AudiothekClient(proxy=proxy)

    @staticmethod
    def _program_folder_name(programset_id: str, programset_title: str) -> str:
        if programset_title:
            return f"{programset_id} {sanitize_folder_name(programset_title)}"
        return programset_id

    def _graphql_get(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Execute GraphQL query using client."""
        return self.client._graphql_get(query, variables)

    def _download_to_file(self, url: str, file_path: str, *, check_status: bool = False) -> None:
        """Download content using client."""
        self.client._download_to_file(url, file_path, check_status=check_status)

    def _should_skip_json_write(self, file_path: str, new_data: dict[str, Any]) -> bool:
        """Check if JSON file should be skipped because content is the same.

        Args:
            file_path: Path to the JSON file
            new_data: New data to be written

        Returns:
            True if the write should be skipped (content is identical), False otherwise

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

    def find_program_sets_by_editorial_category_id(self, editorial_category_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Find program sets by editorial category ID."""
        return self.client.find_program_sets_by_editorial_category_id(editorial_category_id, limit)

    def find_editorial_collections_by_editorial_category_id(self, editorial_category_id: str, limit: int = 200) -> list[dict[str, Any]]:
        """Find editorial collections by editorial category ID."""
        return self.client.find_editorial_collections_by_editorial_category_id(editorial_category_id, limit)

    def download_from_url(self, url: str, folder: str | None = None) -> None:
        """Download content from an ARD Audiothek URL.

        Args:
            url: The URL of the ARD Audiothek show or collection
            folder: The output directory (overrides base_folder if provided)

        """
        target_folder = folder or self.base_folder
        resource = self._parse_url(url)
        if not resource:
            self.logger.error("Could not determine resource ID from URL.")
            return

        resource_type, resource_id = resource
        if resource_type == "episode":
            self._download_single_episode(resource_id, target_folder)
        else:
            self._download_collection(resource_id, target_folder, resource_type == "collection")

    def download_from_id(self, resource_id: str, folder: str | None = None) -> None:
        """Download content from a resource ID.

        Args:
            resource_id: The direct ID of the resource
            folder: The output directory (overrides base_folder if provided)

        """
        target_folder = folder or self.base_folder
        resource = self._determine_resource_type_from_id(resource_id)
        if not resource:
            self.logger.error("Could not determine resource type from ID.")
            return

        resource_type, parsed_id = resource
        if resource_type == "episode":
            self._download_single_episode(parsed_id, target_folder)
        else:
            self._download_collection(parsed_id, target_folder, resource_type == "collection")

    def update_all_folders(self, folder: str | None = None) -> None:
        """Update all subfolders in the output directory by crawling through existing IDs.

        Args:
            folder: The output directory containing subfolders to update (overrides base_folder if provided)

        """
        target_folder = folder or self.base_folder
        if not os.path.exists(target_folder):
            self.logger.error("Output directory %s does not exist.", target_folder)
            return

        self.logger.info("Starting update of all folders in %s", target_folder)

        # Find all subdirectories that end with numeric IDs (like scrape.sh does)
        try:
            for item in os.listdir(target_folder):
                item_path = os.path.join(target_folder, item)
                if os.path.isdir(item_path):
                    # Check if the folder name ends with a numeric ID
                    if item.isdigit():
                        self.logger.info("Processing folder: %s", item)
                        self.download_from_id(item, target_folder)
                    else:
                        # Try to extract numeric ID from the folder name
                        match = re.search(r"^(\d+)", item)
                        if match:
                            numeric_id = match.group(1)
                            self.logger.info("Processing folder: %s (ID: %s)", item, numeric_id)
                            self.download_from_id(numeric_id, target_folder)
        except Exception as e:
            self.logger.error("Error while updating folders: %s", e)
            self.logger.exception(e)

    def _get_program_title(self, resource_id: str, resource_type: str) -> str | None:
        """Get the program title from the API.

        Args:
            resource_id: The resource ID
            resource_type: The resource type (program, collection, etc.)

        Returns:
            The program title or None if not found

        """
        if resource_type == "episode":
            return self.client.get_episode_title(resource_id)
        elif resource_type in ["program", "collection"]:
            return self.client.get_program_set_title(resource_id)
        return None

    def _determine_resource_type_from_id(self, resource_id: str) -> tuple[str, str] | None:
        """Determine resource type from ID pattern using client."""
        return self.client.determine_resource_type_from_id(resource_id)

    def _parse_url(self, url: str) -> tuple[str, str] | None:
        """Parse Audiothek URL and return (resource_type, id) using client."""
        return self.client.parse_url(url)

    def _download_single_episode(self, episode_id: str, folder: str) -> None:
        """Fetch and store a single episode.

        Args:
            episode_id: The ID of the episode to download
            folder: The output directory to save the downloaded file

        """
        query = load_graphql_query("EpisodeQuery.graphql")
        response_json = self._graphql_get(query, {"id": episode_id})

        node = response_json.get("data", {}).get("result")
        if not node:
            self.logger.error("Episode not found for %s", episode_id)
            return

        self._save_nodes([node], folder)

    @staticmethod
    def _extract_collection_data(results: dict[str, Any]) -> dict[str, Any]:
        """Extract collection data from GraphQL results."""
        return {
            "id": results.get("id"),
            "coreId": results.get("coreId"),
            "title": results.get("title"),
            "synopsis": results.get("synopsis"),
            "summary": results.get("summary"),
            "editorialDescription": results.get("editorialDescription"),
            "image": results.get("image"),
            "sharingUrl": results.get("sharingUrl"),
            "path": results.get("path"),
            "numberOfElements": results.get("numberOfElements"),
            "broadcastDuration": results.get("broadcastDuration"),
        }

    @staticmethod
    def _extract_program_set_data(results: dict[str, Any]) -> dict[str, Any]:
        """Extract program set data from GraphQL results."""
        return {
            "id": results.get("id"),
            "coreId": results.get("coreId"),
            "title": results.get("title"),
            "synopsis": results.get("synopsis"),
            "numberOfElements": results.get("numberOfElements"),
            "image": results.get("image"),
            "editorialCategoryId": results.get("editorialCategoryId"),
            "imageCollectionId": results.get("imageCollectionId"),
            "publicationServiceId": results.get("publicationServiceId"),
            "coreDocument": results.get("coreDocument"),
            "rowId": results.get("rowId"),
            "nodeId": results.get("nodeId"),
        }

    def _fetch_collection_nodes(self, query: str, resource_id: str) -> tuple[list[dict], dict[str, Any]]:
        """Fetch all nodes for a collection using GraphQL pagination.

        Args:
            query: The GraphQL query string
            resource_id: The resource ID to fetch

        Returns:
            Tuple of (nodes list, collection_data dict)


        """
        nodes: list[dict] = []
        collection_data: dict | None = None
        offset = 0
        count = 24

        while True:
            variables = {"id": resource_id, "offset": offset, "count": count}
            response_json = self._graphql_get(query, variables)

            results = response_json.get("data", {}).get("result", {})
            if not results:
                break

            # Store collection data on first iteration
            if collection_data is None:
                collection_data = results

            items = results.get("items", {}) or {}
            page_nodes = items.get("nodes", []) or []
            if isinstance(page_nodes, list):
                nodes.extend(page_nodes)

            page_info = items.get("pageInfo", {}) or {}
            if not page_info.get("hasNextPage"):
                break
            offset += count

        return nodes, collection_data or {}

    def _download_collection(self, resource_id: str, folder: str, is_editorial_collection: bool) -> None:
        """Download episodes from ARD Audiothek.

        Args:
            resource_id: The program set ID extracted from the URL
            folder: The output directory to save downloaded files
            is_editorial_collection: Whether the URL points to an editorial collection

        """
        query_file = "editorialCollection.graphql" if is_editorial_collection else "ProgramSetEpisodesQuery.graphql"
        query = load_graphql_query(query_file)

        nodes, raw_collection_data = self._fetch_collection_nodes(query, resource_id)

        self._save_nodes(nodes, folder)

        if nodes:
            self._save_collection_metadata(raw_collection_data, nodes, folder, is_editorial_collection)

    def _save_collection_metadata(self, raw_data: dict[str, Any], nodes: list[dict], folder: str, is_editorial_collection: bool) -> None:
        """Save collection metadata and cover image."""
        collection_data = self._extract_collection_data(raw_data) if is_editorial_collection else self._extract_program_set_data(raw_data)

        # Get the program folder path from the first node
        first_node = nodes[0]
        program_set = first_node.get("programSet") or {}
        programset_id = program_set.get("id") or collection_data.get("id") or "collection"
        programset_title = program_set.get("title") or collection_data.get("title") or ""

        folder_name = self._program_folder_name(str(programset_id), str(programset_title))
        program_path = os.path.join(folder, folder_name)
        self._save_collection_data(collection_data, program_path, is_editorial_collection)

    def _save_collection_data(self, collection_data: dict, folder: str, is_editorial_collection: bool) -> None:
        """Save collection metadata as <id>.json in the series/collection folder.

        Args:
            collection_data: The collection metadata dictionary
            folder: The series/collection directory to save the JSON file
            is_editorial_collection: Whether this is an editorial collection (True) or program set (False)

        """
        collection_id = collection_data.get("id") or ("collection" if is_editorial_collection else "program_set")

        # Create the output folder if it doesn't exist
        try:
            os.makedirs(folder, exist_ok=True)
        except Exception as e:
            self.logger.error("Couldn't create output directory %s: %s", folder, e)
            return

        # Save the collection data as <id>.json
        collection_file_path = os.path.join(folder, f"{collection_id}.json")

        try:
            # Skip writing if content is the same as existing file
            if self._should_skip_json_write(collection_file_path, collection_data):
                collection_type = "editorial collection" if is_editorial_collection else "program set"
                self.logger.info("Skipped writing %s data (content unchanged): %s", collection_type, collection_file_path)
            else:
                with open(collection_file_path, "w") as f:
                    json.dump(collection_data, f, indent=4)
                collection_type = "editorial collection" if is_editorial_collection else "program set"
                self.logger.info("Saved %s data: %s", collection_type, collection_file_path)
        except Exception as e:
            collection_type = "editorial collection" if is_editorial_collection else "program set"
            self.logger.error("Error saving %s data: %s", collection_type, e)

        # Download and save collection cover image
        image_data = collection_data.get("image") or {}
        image_url_template = image_data.get("url") or ""
        image_url = image_url_template.replace("{width}", "2000") if image_url_template else ""

        if image_url:
            image_file_path = os.path.join(folder, f"{collection_id}.jpg")
            if not os.path.exists(image_file_path):
                try:
                    self._download_to_file(image_url, image_file_path, check_status=True)
                    self.logger.info("Saved %s cover image: %s", collection_type, image_file_path)
                except Exception as e:
                    self.logger.error("Error downloading %s cover image: %s", collection_type, e)

    def _save_nodes(self, nodes: list[dict[str, Any]], folder: str) -> None:
        """Write episode assets (cover, audio, metadata) to disk."""
        for index, node in enumerate(nodes):
            node_id = str(node.get("id") or index)
            title = node.get("title") or node_id

            # get title from infos
            array_filename = re.findall(r"(\w+)", title)
            filename_base = "_".join(array_filename) if array_filename else node_id
            filename = f"{filename_base}_{node_id}"

            # Extract URLs from node
            image_urls = self._extract_image_urls(node)
            mp3_url = self._extract_audio_url(node)
            if not mp3_url:
                self.logger.warning("No audio URL found for node %s", node_id)
                continue

            # Get program information
            program_set = node.get("programSet") or {}
            programset_id = program_set.get("id") or "episode"
            programset_title = program_set.get("title") or ""

            # Create folder name with ID and title: "123456 Show Title"
            folder_name = AudiothekDownloader._program_folder_name(str(programset_id), str(programset_title))
            program_path: str = os.path.join(folder, folder_name)

            # Create directory
            try:
                os.makedirs(program_path, exist_ok=True)
            except Exception as e:
                self.logger.error("[Error] Couldn't create output directory!")
                self.logger.exception(e)
                return

            # Save images and metadata
            self._save_images_and_metadata(
                ImageMetadata(node_id=node_id, title=title, filename=filename, program_path=program_path, program_set=program_set, image_urls=image_urls), node
            )

            # Save audio file
            self._save_audio_file(mp3_url, filename, program_path, index + 1, len(nodes))

    def _extract_image_urls(self, node: dict[str, Any]) -> dict[str, str]:
        """Extract image URLs from node."""
        image = node.get("image") or {}
        image_url_template = image.get("url") or ""
        image_url = image_url_template.replace("{width}", "2000") if image_url_template else ""
        image_url_x1_template = image.get("url1X1") or ""
        image_url_x1 = image_url_x1_template.replace("{width}", "2000") if image_url_x1_template else ""

        return {"image_url": image_url, "image_url_x1": image_url_x1}

    def _extract_audio_url(self, node: dict[str, Any]) -> str:
        """Extract audio URL from node."""
        audios = node.get("audios") or []
        first_audio = audios[0] if audios and isinstance(audios[0], dict) else None
        if first_audio:
            return first_audio.get("downloadUrl") or first_audio.get("url") or ""
        return ""

    def _save_images_and_metadata(self, metadata: ImageMetadata, node: dict[str, Any]) -> None:
        """Save images and metadata files."""
        # Save images
        image_file_path = os.path.join(metadata.program_path, metadata.filename + ".jpg")
        image_file_x1_path = os.path.join(metadata.program_path, metadata.filename + "_x1.jpg")

        if metadata.image_urls["image_url"] and not os.path.exists(image_file_path):
            self._download_to_file(metadata.image_urls["image_url"], image_file_path)

        if metadata.image_urls["image_url_x1"] and not os.path.exists(image_file_x1_path):
            self._download_to_file(metadata.image_urls["image_url_x1"], image_file_x1_path)

        # Save metadata
        meta_file_path = os.path.join(metadata.program_path, metadata.filename + ".json")
        data = {
            "id": metadata.node_id,
            "title": metadata.title,
            "description": node.get("description"),
            "summary": node.get("summary"),
            "duration": node.get("duration"),
            "publishDate": node.get("publishDate"),
            "programSet": {
                "id": metadata.program_set.get("id"),
                "title": metadata.program_set.get("title"),
                "path": metadata.program_set.get("path"),
            },
        }

        # Skip writing if content is the same as existing file
        if self._should_skip_json_write(meta_file_path, data):
            self.logger.info("Skipped writing episode metadata (content unchanged): %s", meta_file_path)
        else:
            with open(meta_file_path, "w") as f:
                json.dump(data, f, indent=4)

    def _save_audio_file(self, mp3_url: str, filename: str, program_path: str, current_index: int, total_count: int) -> None:
        """Save audio file."""
        mp3_file_path = os.path.join(program_path, filename + ".mp3")

        self.logger.info("Download: %s of %s -> %s", current_index, total_count, mp3_file_path)

        # Check if file exists and is complete
        should_download = True
        if os.path.exists(mp3_file_path):
            # Get expected content length via HEAD request
            expected_length = self.client._get_content_length(mp3_url)
            if expected_length:
                # Get current file size
                current_size = os.path.getsize(mp3_file_path)
                if current_size == expected_length:
                    self.logger.info("File already exists and is complete: %s", mp3_file_path)
                    should_download = False
                else:
                    self.logger.info(
                        "File exists but is incomplete (%s/%s bytes), will backup and re-download: %s", current_size, expected_length, mp3_file_path
                    )
                    # Rename old file to .bak
                    backup_path = mp3_file_path + ".bak"
                    try:
                        os.rename(mp3_file_path, backup_path)
                        self.logger.info("Backed up incomplete file to: %s", backup_path)
                    except Exception as e:
                        self.logger.error("Failed to backup file: %s", e)
            else:
                self.logger.info("Could not determine content length, will backup existing file: %s", mp3_file_path)
                # Rename old file to .bak
                backup_path = mp3_file_path + ".bak"
                try:
                    os.rename(mp3_file_path, backup_path)
                    self.logger.info("Backed up existing file to: %s", backup_path)
                except Exception as e:
                    self.logger.error("Failed to backup file: %s", e)

        if should_download:
            self._download_to_file(mp3_url, mp3_file_path)
