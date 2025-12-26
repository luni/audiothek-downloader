import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mutagen._file import File

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

    def download_from_url(self, url: str, folder: str | None = None) -> None:
        """Download content from an ARD Audiothek URL.

        Args:
            url: The URL of the ARD Audiothek show or collection
            folder: The output directory (overrides base_folder if provided)

        """
        target_folder = folder or self.base_folder
        resource = self.client.parse_url(url)
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
        resource = self.client.determine_resource_type_from_id(resource_id)
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

    def remove_lower_quality_files(self, folder: str | None = None, dry_run: bool = False) -> None:
        """Remove lower quality files when higher quality versions exist.

        Args:
            folder: The output directory containing subfolders to process (overrides base_folder if provided)
            dry_run: If True, only show what would be removed without actually deleting files

        """
        target_folder = folder or self.base_folder
        if not os.path.exists(target_folder):
            self.logger.error("Output directory %s does not exist.", target_folder)
            return

        if dry_run:
            self.logger.info("DRY RUN: Showing what would be removed in %s", target_folder)
        else:
            self.logger.info("Starting removal of lower quality files in %s", target_folder)

        # Find all subdirectories
        try:
            for item in os.listdir(target_folder):
                item_path = os.path.join(target_folder, item)
                if os.path.isdir(item_path):
                    self._process_folder_quality(item_path, dry_run)
        except Exception as e:
            self.logger.error("Error while processing folders: %s", e)
            self.logger.exception(e)

    def _process_folder_quality(self, folder_path: str, dry_run: bool = False) -> None:
        """Process a single folder to remove lower quality files."""
        try:
            # Group files by base name (without extension)
            file_groups = {}
            for file in os.listdir(folder_path):
                file_path = os.path.join(folder_path, file)
                if os.path.isfile(file_path):
                    base_name, ext = os.path.splitext(file)
                    ext = ext.lower()

                    if ext in [".mp3", ".mp4", ".aac", ".m4a"]:
                        if base_name not in file_groups:
                            file_groups[base_name] = {}
                        file_groups[base_name][ext] = file_path

            # Process each group of files
            for base_name, files in file_groups.items():
                self._compare_and_remove_files(base_name, files, folder_path, dry_run)

        except Exception as e:
            self.logger.error("Error processing folder %s: %s", folder_path, e)

    def _compare_and_remove_files(self, base_name: str, files: dict[str, str], folder_path: str, dry_run: bool = False) -> None:
        """Compare files with same base name and remove lower quality ones."""
        if len(files) <= 1:
            return  # No comparison needed

        # Get quality information for each file
        file_qualities = {}
        for ext, file_path in files.items():
            quality = self._get_audio_quality(file_path)
            if quality is not None:
                file_qualities[ext] = {"path": file_path, "bitrate": quality}

        if not file_qualities:
            return

        # Determine which files to keep/remove
        files_to_remove = []
        best_file = None
        best_bitrate = 0

        # Find the best quality file
        for ext, info in file_qualities.items():
            bitrate = info["bitrate"]

            # MP4/AAC with >=96kbit is considered better than MP3 128kbit
            if ext in [".mp4", ".aac", ".m4a"]:
                # AAC/MP4 files - prefer higher bitrate, but even 96kbit is better than MP3 128kbit
                if bitrate >= 96:
                    if not best_file or bitrate > best_bitrate or (best_file and best_file.endswith(".mp3")):
                        best_file = info["path"]
                        best_bitrate = bitrate
            elif ext == ".mp3":
                # MP3 files
                if not best_file or (best_file and best_file.endswith(".mp3") and bitrate > best_bitrate):
                    best_file = info["path"]
                    best_bitrate = bitrate

        # If we have a best file, remove lower quality ones
        if best_file:
            for ext, info in file_qualities.items():
                if info["path"] != best_file:
                    # Special logic: MP4/AAC >=96kbit beats MP3 128kbit
                    if ext == ".mp3" and info["bitrate"] <= 128 and any(other_ext in [".mp4", ".aac", ".m4a"] for other_ext in file_qualities.keys()):
                        files_to_remove.append(info["path"])
                    # Otherwise, remove if bitrate is lower
                    elif info["bitrate"] < best_bitrate:
                        files_to_remove.append(info["path"])

        # Remove the files
        for file_path in files_to_remove:
            if dry_run:
                self.logger.info("DRY RUN: Would remove lower quality file: %s", file_path)
            else:
                try:
                    os.remove(file_path)
                    self.logger.info("Removed lower quality file: %s", file_path)
                except Exception as e:
                    self.logger.error("Failed to remove file %s: %s", file_path, e)

    def _get_audio_quality(self, file_path: str) -> int | None:
        """Get audio bitrate from file using mutagen."""
        try:
            audio = File(file_path)
            if audio is not None:
                if hasattr(audio.info, "bitrate"):
                    return audio.info.bitrate
                # For some formats, bitrate might be in different location
                if hasattr(audio, "info") and hasattr(audio.info, "bitrate"):
                    return audio.info.bitrate
        except Exception as e:
            self.logger.debug("Could not read bitrate from %s: %s", file_path, e)
        return None

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

    def _download_single_episode(self, episode_id: str, folder: str) -> None:
        """Fetch and store a single episode.

        Args:
            episode_id: The ID of the episode to download
            folder: The output directory to save the downloaded file

        """
        query = load_graphql_query("EpisodeQuery.graphql")
        response_json = self.client._graphql_get(query, {"id": episode_id})

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
            response_json = self.client._graphql_get(query, variables)

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
        # Use publish date from first node for collection files
        first_node_publish_date = first_node.get("publishDate")
        self._save_collection_data(collection_data, program_path, is_editorial_collection, first_node_publish_date)

    def _save_collection_data(self, collection_data: dict, folder: str, is_editorial_collection: bool, publish_date: str | None = None) -> None:
        """Save collection metadata as <id>.json in the series/collection folder.

        Args:
            collection_data: The collection metadata dictionary
            folder: The series/collection directory to save the JSON file
            is_editorial_collection: Whether this is an editorial collection (True) or program set (False)
            publish_date: Publish date to set for file modification time

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
                if publish_date:
                    self._set_file_modification_time(collection_file_path, publish_date)
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
                    self.client._download_to_file(image_url, image_file_path, check_status=True)
                    if publish_date:
                        self._set_file_modification_time(image_file_path, publish_date)
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
            audio_urls = self._extract_audio_url(node)
            if not audio_urls:
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
                ImageMetadata(node_id=node_id, title=title, filename=filename, program_path=program_path, program_set=program_set, image_urls=image_urls),
                node,
                node.get("publishDate"),
            )

            # Save audio file
            self._save_audio_file(audio_urls, filename, program_path, index + 1, len(nodes), node.get("publishDate"))

    def _extract_image_urls(self, node: dict[str, Any]) -> dict[str, str]:
        """Extract image URLs from node."""
        image = node.get("image") or {}
        image_url_template = image.get("url") or ""
        image_url = image_url_template.replace("{width}", "2000") if image_url_template else ""
        image_url_x1_template = image.get("url1X1") or ""
        image_url_x1 = image_url_x1_template.replace("{width}", "2000") if image_url_x1_template else ""

        return {"image_url": image_url, "image_url_x1": image_url_x1}

    def _extract_audio_url(self, node: dict[str, Any]) -> list[str]:
        """Extract audio URLs from node, returning URLs in priority order.

        Returns:
            List of URLs ordered from highest to lowest priority

        """
        audios = node.get("audios") or []
        if not audios:
            return []

        # Collect all available URLs from all audio elements
        download_urls = []
        streaming_urls = []

        for audio in audios:
            if isinstance(audio, dict):
                download_url = audio.get("downloadUrl")
                streaming_url = audio.get("url")

                if download_url:
                    download_urls.append(download_url)
                if streaming_url:
                    streaming_urls.append(streaming_url)

        # Debug output
        self.logger.debug("Found %d download URLs: %s", len(download_urls), download_urls)
        self.logger.debug("Found %d streaming URLs: %s", len(streaming_urls), streaming_urls)

        # Remove duplicates while preserving order
        download_urls = list(dict.fromkeys(download_urls))
        streaming_urls = list(dict.fromkeys(streaming_urls))

        # If no URLs found, return empty list
        if not download_urls and not streaming_urls:
            return []

        # If only one type of URL available, return all available URLs
        if not download_urls:
            return streaming_urls
        if not streaming_urls:
            return download_urls

        # Get content lengths for all URLs to find the best combination
        url_candidates = []

        # Check download URLs
        for url in download_urls:
            size = self.client._get_content_length(url)
            if size is not None:
                url_candidates.append(("download", url, size))

        # Check streaming URLs
        for url in streaming_urls:
            size = self.client._get_content_length(url)
            if size is not None:
                url_candidates.append(("streaming", url, size))

        # Sort by size (descending) to prefer larger files
        url_candidates.sort(key=lambda x: x[2], reverse=True)

        if not url_candidates:
            # If we couldn't determine sizes, return all available URLs
            all_urls = download_urls + streaming_urls
            return list(dict.fromkeys(all_urls))

        # Create priority list: start with preferred URL, then add remaining URLs sorted by size
        preferred_type, preferred_url, preferred_size = url_candidates[0]
        priority_urls = [preferred_url]

        # Add remaining URLs sorted by size (excluding preferred)
        remaining_candidates = [(url_type, url, size) for url_type, url, size in url_candidates[1:] if url != preferred_url]
        remaining_candidates.sort(key=lambda x: x[2], reverse=True)

        for url_type, url, size in remaining_candidates:
            if url not in priority_urls:
                priority_urls.append(url)

        # Add any URLs that weren't in candidates (couldn't get size)
        all_urls = download_urls + streaming_urls
        for url in all_urls:
            if url not in priority_urls:
                priority_urls.append(url)

        self.logger.debug("Chosen URLs in priority order: %s", priority_urls)
        return priority_urls

    def _save_images_and_metadata(self, metadata: ImageMetadata, node: dict[str, Any], publish_date: str | None = None) -> None:
        """Save images and metadata files."""
        # Save images
        image_file_path = os.path.join(metadata.program_path, metadata.filename + ".jpg")
        image_file_x1_path = os.path.join(metadata.program_path, metadata.filename + "_x1.jpg")

        if metadata.image_urls["image_url"] and not os.path.exists(image_file_path):
            self.client._download_to_file(metadata.image_urls["image_url"], image_file_path)
            if publish_date:
                self._set_file_modification_time(image_file_path, publish_date)

        if metadata.image_urls["image_url_x1"] and not os.path.exists(image_file_x1_path):
            self.client._download_to_file(metadata.image_urls["image_url_x1"], image_file_x1_path)
            if publish_date:
                self._set_file_modification_time(image_file_x1_path, publish_date)

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
            if publish_date:
                self._set_file_modification_time(meta_file_path, publish_date)

    def _save_audio_file(
        self, audio_urls: list[str], filename: str, program_path: str, current_index: int, total_count: int, publish_date: str | None = None
    ) -> None:
        """Save audio file with appropriate extension based on URL format."""
        if not audio_urls:
            self.logger.error("No audio URLs provided")
            return

        # Use the first (highest priority) URL
        preferred_url = audio_urls[0]
        # Use the second URL as fallback if available, otherwise use the first
        fallback_url = audio_urls[1] if len(audio_urls) > 1 else audio_urls[0]
        # Determine file extension based on URL format
        file_extension = self._get_audio_file_extension(preferred_url)
        audio_file_path = os.path.join(program_path, filename + file_extension)

        self.logger.info("Download: %s of %s -> %s", current_index, total_count, audio_file_path)

        # Check if file exists and is complete
        should_download = True
        if os.path.exists(audio_file_path):
            # Check file availability and get content length
            is_available, expected_length = self.client._check_file_availability(preferred_url)
            if not is_available:
                self.logger.warning("Audio file not available (404), keeping existing file: %s", audio_file_path)
                should_download = False
            elif expected_length:
                # Get current file size
                current_size = os.path.getsize(audio_file_path)
                if current_size == expected_length:
                    self.logger.info("File already exists and is complete: %s", audio_file_path)
                    should_download = False
                elif expected_length > current_size:
                    self.logger.info(
                        "New version is larger than existing file (%s/%s bytes), will backup and re-download: %s",
                        current_size,
                        expected_length,
                        audio_file_path,
                    )
                    # Rename old file to .bak
                    backup_path = audio_file_path + ".bak"
                    try:
                        os.rename(audio_file_path, backup_path)
                        self.logger.info("Backed up smaller file to: %s", backup_path)
                    except Exception as e:
                        self.logger.error("Failed to backup file: %s", e)
                else:
                    self.logger.info(
                        "New version is smaller than existing file (%s/%s bytes), will keep existing file: %s", current_size, expected_length, audio_file_path
                    )
                    should_download = False
            else:
                self.logger.info("Could not determine content length, will backup existing file: %s", audio_file_path)
                # Rename old file to .bak
                backup_path = audio_file_path + ".bak"
                try:
                    os.rename(audio_file_path, backup_path)
                    self.logger.info("Backed up existing file to: %s", backup_path)
                except Exception as e:
                    self.logger.error("Failed to backup file: %s", e)

        if should_download:
            download_success = self.client._download_audio_to_file(preferred_url, audio_file_path, fallback_url)
            if download_success:
                # Set file modification time to publish date if available
                if publish_date:
                    self._set_file_modification_time(audio_file_path, publish_date)
            else:
                self.logger.error("Failed to download audio file (file not found or unavailable): %s", preferred_url)
                # Remove any partially downloaded file
                if os.path.exists(audio_file_path):
                    try:
                        os.remove(audio_file_path)
                        self.logger.info("Removed invalid audio file: %s", audio_file_path)
                    except Exception as e:
                        self.logger.error("Failed to remove invalid audio file: %s", e)

                # Restore backup file if it exists
                backup_path = audio_file_path + ".bak"
                if os.path.exists(backup_path):
                    try:
                        os.rename(backup_path, audio_file_path)
                        self.logger.info("Restored original file from backup: %s", audio_file_path)
                    except Exception as e:
                        self.logger.error("Failed to restore backup file: %s", e)

    def _get_audio_file_extension(self, url: str) -> str:
        """Get the appropriate file extension for an audio URL."""
        url_lower = url.lower()
        if url_lower.endswith(".mp4"):
            return ".mp4"
        elif url_lower.endswith(".aac"):
            return ".aac"
        elif url_lower.endswith(".m4a"):
            return ".m4a"
        elif url_lower.endswith(".mp3"):
            return ".mp3"
        elif "aac" in url_lower:
            return ".aac"
        elif "mp4" in url_lower:
            return ".mp4"
        else:
            # Default to .mp3 for backward compatibility
            return ".mp3"

    def _set_file_modification_time(self, file_path: str, publish_date: str) -> None:
        """Set file modification time based on publish date.

        Args:
            file_path: Path to the file to modify
            publish_date: Publish date string from the API

        """
        try:
            # Parse the publish date - ARD Audiothek typically uses ISO 8601 format
            # Example: "2023-12-01T10:00:00.000Z" or "2023-12-01T10:00:00Z"
            if publish_date.endswith("Z"):
                # Handle UTC timestamp
                dt = datetime.fromisoformat(publish_date.replace("Z", "+00:00"))
            else:
                # Handle timestamp without timezone info
                dt = datetime.fromisoformat(publish_date)

            # Convert to timestamp and set file modification time
            timestamp = dt.timestamp()
            os.utime(file_path, (timestamp, timestamp))
            self.logger.debug("Set file modification time for %s to %s", file_path, publish_date)

        except (ValueError, OSError) as e:
            self.logger.warning("Failed to set file modification time for %s: %s", file_path, e)
