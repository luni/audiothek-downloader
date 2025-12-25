"""ARD Audiothek library for downloading audio content."""

import json
import logging
import os
import re
from typing import Any

import requests

REQUEST_TIMEOUT = 30


def _sanitize_folder_name(name: str) -> str:
    """Sanitize a string to be used as a folder name.

    Args:
        name: The string to sanitize

    Returns:
        A sanitized string safe for use as a folder name

    """
    # Remove or replace characters that are problematic in folder names
    # Replace forward slashes and other problematic characters with underscores
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(" .")
    # Replace multiple spaces with single space
    sanitized = re.sub(r"\s+", " ", sanitized)
    # Limit length to avoid filesystem issues
    if len(sanitized) > 100:
        sanitized = sanitized[:100].rstrip()
    return sanitized


class AudiothekDownloader:
    """ARD Audiothek downloader class."""

    def __init__(self, base_folder: str = "./output") -> None:
        """Initialize the downloader.

        Args:
            base_folder: Default output directory for downloaded files

        """
        self.base_folder = base_folder
        self.logger = logging.getLogger(__name__)

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
            self._download_collection(url, resource_id, target_folder, resource_type == "collection")

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
            self._download_collection("", parsed_id, target_folder, resource_type == "collection")

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

    def migrate_folders(self, folder: str | None = None) -> None:
        """Migrate existing folders to new naming schema (ID + Title).

        Args:
            folder: The output directory containing folders to migrate (overrides base_folder if provided)

        """
        target_folder = folder or self.base_folder
        if not os.path.exists(target_folder):
            self.logger.error("Output directory %s does not exist.", target_folder)
            return

        self.logger.info("Starting folder migration in %s", target_folder)

        # Find all subdirectories with numeric IDs
        try:
            for item in os.listdir(target_folder):
                item_path = os.path.join(target_folder, item)
                if os.path.isdir(item_path):
                    # Check if the folder name is a pure numeric ID (old format)
                    if item.isdigit():
                        self.logger.info("Found old format folder: %s", item)

                        # Try to get the program title by making a request
                        resource_result = self._determine_resource_type_from_id(item)
                        if not resource_result:
                            self.logger.warning("Could not determine resource type for folder: %s", item)
                            continue

                        resource_type, parsed_id = resource_result

                        # Get program information to extract the title
                        title = self._get_program_title(parsed_id, resource_type)
                        if title:
                            # Create new folder name with ID and title
                            new_folder_name = f"{item} {_sanitize_folder_name(title)}"
                            new_folder_path = os.path.join(target_folder, new_folder_name)

                            # Rename the folder
                            try:
                                os.rename(item_path, new_folder_path)
                                self.logger.info("Renamed: %s -> %s", item, new_folder_name)
                            except OSError as e:
                                self.logger.error("Failed to rename folder %s: %s", item, e)
                        else:
                            self.logger.warning("Could not get title for folder: %s", item)

        except Exception as e:
            self.logger.error("Error while migrating folders: %s", e)
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
            return self._get_episode_title(resource_id)
        elif resource_type in ["program", "collection"]:
            return self._get_program_set_title(resource_id)
        return None

    def _get_episode_title(self, episode_id: str) -> str | None:
        """Get program set title from episode."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        graphql_dir = os.path.join(base_dir, "graphql")
        query_path = os.path.join(graphql_dir, "EpisodeQuery.graphql")

        try:
            with open(query_path) as f:
                query = f.read()

            response = requests.get(
                "https://api.ardaudiothek.de/graphql",
                params={"query": query, "variables": json.dumps({"id": episode_id})},
                timeout=REQUEST_TIMEOUT,
            )
            response_json = response.json()

            node = response_json.get("data", {}).get("result")
            if node:
                program_set = node.get("programSet") or {}
                return program_set.get("title")
        except Exception as e:
            self.logger.error("Error getting episode title: %s", e)

        return None

    def _get_program_set_title(self, program_id: str) -> str | None:
        """Get program set title directly."""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        graphql_dir = os.path.join(base_dir, "graphql")
        query_path = os.path.join(graphql_dir, "ProgramSetEpisodesQuery.graphql")

        try:
            with open(query_path) as f:
                query = f.read()

            response = requests.get(
                "https://api.ardaudiothek.de/graphql",
                params={"query": query, "variables": json.dumps({"id": program_id, "offset": 0, "count": 1})},
                timeout=REQUEST_TIMEOUT,
            )
            response_json = response.json()

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

    def _determine_resource_type_from_id(self, resource_id: str) -> tuple[str, str] | None:
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

    def _parse_url(self, url: str) -> tuple[str, str] | None:
        """Parse Audiothek URL and return (resource_type, id).

        Args:
            url: The URL to parse

        Returns:
            A tuple of (resource_type, id) where resource_type is one of 'episode', 'collection', or 'program'

        """
        urn_match = re.search(r"/(urn:ard:[^/]+)/?$", url)
        if urn_match:
            urn = urn_match.group(1)
            if urn.startswith("urn:ard:episode:"):
                return "episode", urn
            if urn.startswith("urn:ard:page:"):
                return "collection", urn
            if urn.startswith("urn:ard:show:"):
                return "program", urn
            # fallback: treat other urns as program sets
            return "program", urn

        numeric_match = re.search(r"/(\d+)/?$", url)
        if numeric_match:
            return "program", numeric_match.group(1)

        return None

    def _download_single_episode(self, episode_id: str, folder: str) -> None:
        """Fetch and store a single episode.

        Args:
            episode_id: The ID of the episode to download
            folder: The output directory to save the downloaded file

        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        graphql_dir = os.path.join(base_dir, "graphql")
        query_path = os.path.join(graphql_dir, "EpisodeQuery.graphql")
        with open(query_path) as f:
            query = f.read()

        response = requests.get(
            "https://api.ardaudiothek.de/graphql",
            params={"query": query, "variables": json.dumps({"id": episode_id})},
            timeout=REQUEST_TIMEOUT,
        )
        response_json = response.json()

        node = response_json.get("data", {}).get("result")
        if not node:
            self.logger.error("Episode not found for %s", episode_id)
            return

        self._save_nodes([node], folder)

    def _download_collection(self, url: str, resource_id: str, folder: str, is_editorial_collection: bool) -> None:
        """Download episodes from ARD Audiothek.

        Args:
            url: The URL of the ARD Audiothek show or collection
            resource_id: The program set ID extracted from the URL
            folder: The output directory to save downloaded files
            is_editorial_collection: Whether the URL points to an editorial collection

        """
        base_dir = os.path.dirname(os.path.abspath(__file__))
        graphql_dir = os.path.join(base_dir, "graphql")

        query_file = "editorialCollection.graphql" if is_editorial_collection else "ProgramSetEpisodesQuery.graphql"
        query_path = os.path.join(graphql_dir, query_file)
        with open(query_path) as f:
            query = f.read()

        nodes: list[dict] = []
        collection_data: dict | None = None
        offset = 0
        count = 24
        while True:
            variables = {"id": resource_id, "offset": offset, "count": count}
            response = requests.get(
                "https://api.ardaudiothek.de/graphql",
                params={"query": query, "variables": json.dumps(variables)},
                timeout=REQUEST_TIMEOUT,
            )
            response_json = response.json()

            results = response_json.get("data", {}).get("result", {})
            if not results:
                break

            # Store collection data for editorial collections and program sets (only on first iteration)
            if collection_data is None:
                if is_editorial_collection:
                    collection_data = {
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
                else:
                    # Program set metadata
                    collection_data = {
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

            items = results.get("items", {}) or {}
            page_nodes = items.get("nodes", []) or []
            if isinstance(page_nodes, list):
                nodes.extend(page_nodes)

            page_info = items.get("pageInfo", {}) or {}
            if not page_info.get("hasNextPage"):
                break
            offset += count

        self._save_nodes(nodes, folder)

        # Save collection metadata as <id>.json in the output folder
        if collection_data:
            self._save_collection_data(collection_data, folder, is_editorial_collection)

    def _save_collection_data(self, collection_data: dict, folder: str, is_editorial_collection: bool) -> None:
        """Save collection metadata as <id>.json in the output folder.

        Args:
            collection_data: The collection metadata dictionary
            folder: The output directory to save the JSON file
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
            with open(collection_file_path, "w") as f:
                json.dump(collection_data, f, indent=4)
            collection_type = "editorial collection" if is_editorial_collection else "program set"
            self.logger.info("Saved %s data: %s", collection_type, collection_file_path)
        except Exception as e:
            collection_type = "editorial collection" if is_editorial_collection else "program set"
            self.logger.error("Error saving %s data: %s", collection_type, e)

    def _save_nodes(self, nodes: list[dict[str, Any]], folder: str) -> None:
        """Write episode assets (cover, audio, metadata) to disk."""
        for index, node in enumerate(nodes):
            node_id = str(node.get("id") or index)
            title = node.get("title") or node_id

            # get title from infos
            array_filename = re.findall(r"(\w+)", title)
            filename_base = "_".join(array_filename) if array_filename else node_id
            filename = f"{filename_base}_{node_id}"

            image = node.get("image") or {}
            image_url_template = image.get("url") or ""
            image_url = image_url_template.replace("{width}", "2000") if image_url_template else ""
            image_url_x1_template = image.get("url1X1") or ""
            image_url_x1 = image_url_x1_template.replace("{width}", "2000") if image_url_x1_template else ""

            audios = node.get("audios") or []
            first_audio = audios[0] if audios and isinstance(audios[0], dict) else None
            mp3_url = ""
            if first_audio:
                mp3_url = first_audio.get("downloadUrl") or first_audio.get("url") or ""
            if not mp3_url:
                continue

            program_set = node.get("programSet") or {}
            programset_id = program_set.get("id") or "episode"
            programset_title = program_set.get("title") or ""

            # Create folder name with ID and title: "123456 Show Title"
            if programset_title:
                folder_name = f"{programset_id} {_sanitize_folder_name(programset_title)}"
            else:
                folder_name = programset_id

            program_path: str = os.path.join(folder, folder_name)

            # get information of program
            try:
                os.makedirs(program_path, exist_ok=True)
            except Exception as e:
                self.logger.error("[Error] Couldn't create output directory!")
                self.logger.exception(e)
                return

            # write images
            image_file_path = os.path.join(program_path, filename + ".jpg")
            image_file_x1_path = os.path.join(program_path, filename + "_x1.jpg")

            if image_url and not os.path.exists(image_file_path):
                response_image = requests.get(image_url, timeout=REQUEST_TIMEOUT)
                with open(image_file_path, "wb") as f:
                    f.write(response_image.content)

            if image_url_x1 and not os.path.exists(image_file_x1_path):
                response_image = requests.get(image_url_x1, timeout=REQUEST_TIMEOUT)
                with open(image_file_x1_path, "wb") as f:
                    f.write(response_image.content)

            # write mp3
            mp3_file_path = os.path.join(program_path, filename + ".mp3")

            self.logger.info("Download: %s of %s -> %s", index + 1, len(nodes), mp3_file_path)
            if not os.path.exists(mp3_file_path):
                response_mp3 = requests.get(mp3_url, timeout=REQUEST_TIMEOUT)
                with open(mp3_file_path, "wb") as f:
                    f.write(response_mp3.content)

            # write meta
            meta_file_path = os.path.join(program_path, filename + ".json")
            data = {
                "id": node_id,
                "title": title,
                "description": node.get("description"),
                "summary": node.get("summary"),
                "duration": node.get("duration"),
                "publishDate": node.get("publishDate"),
                "programSet": {
                    "id": programset_id,
                    "title": program_set.get("title"),
                    "path": program_set.get("path"),
                },
            }

            with open(meta_file_path, "w") as f:
                json.dump(data, f, indent=4)
