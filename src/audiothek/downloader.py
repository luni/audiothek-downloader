"""ARD Audiothek downloader class."""

import logging
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from filelock import FileLock, Timeout
from mutagen._file import File

from .cache import GraphQLCache
from .client import AudiothekClient
from .exceptions import FileOperationError
from .file_utils import (
    backup_file,
    compare_json_content,
    ensure_directory_exists,
    restore_backup,
    safe_write_json,
    set_file_modification_time,
)
from .models import DownloadResult, ImageMetadata
from .parallel import parallel_download_nodes
from .utils import sanitize_folder_name


class AudiothekDownloader:
    """ARD Audiothek downloader class."""

    def __init__(
        self,
        base_folder: str = "./output",
        proxy: str | None = None,
        max_workers: int = 4,
        file_lock_timeout: float = 10.0,
        cache_dir: str | None = None,
    ) -> None:
        """Initialize the downloader.

        Args:
            base_folder: Default output directory for downloaded files
            proxy: Proxy URL (e.g. "http://proxy.example.com:8080" or "socks5://proxy.example.com:1080")
            max_workers: Maximum number of parallel download workers
            file_lock_timeout: Seconds to wait when acquiring file locks for assets
            cache_dir: Directory for caching GraphQL responses

        """
        self.base_folder = base_folder
        self.logger = logging.getLogger(__name__)
        cache = GraphQLCache(cache_dir=cache_dir)
        self.client = AudiothekClient(proxy=proxy, cache=cache)
        self.max_workers = max(1, min(max_workers, 16))  # Limit between 1 and 16 workers
        self.file_lock_timeout = max(1.0, float(file_lock_timeout))

    @staticmethod
    def _program_folder_name(programset_id: str, programset_title: str) -> str:
        """Create a folder name from program set ID and title.

        Args:
            programset_id: Program set ID
            programset_title: Program set title

        Returns:
            Folder name with ID and sanitized title

        """
        if programset_title:
            return f"{programset_id} {sanitize_folder_name(programset_title)}"
        return programset_id

    @contextmanager
    def _locked_file_operation(self, file_path: str, operation: str) -> Iterator[None]:
        """Acquire an inter-process file lock for the duration of an operation."""
        lock_path = f"{file_path}.lock"
        lock = FileLock(lock_path, timeout=self.file_lock_timeout)
        try:
            with lock:
                yield
        except Timeout as exc:
            error_msg = f"Timed out acquiring lock for {file_path}"
            self.logger.error(error_msg)
            raise FileOperationError(file_path, operation, error_msg) from exc
        except OSError as exc:
            error_msg = f"Failed to lock {file_path}: {exc}"
            self.logger.error(error_msg)
            raise FileOperationError(file_path, operation, error_msg) from exc
        finally:
            if os.path.exists(lock_path):
                try:
                    os.remove(lock_path)
                except OSError:
                    self.logger.debug("Failed to remove lock file %s", lock_path)

    def download_from_url(self, url: str, folder: str | None = None) -> DownloadResult:
        """Download content from an ARD Audiothek URL.

        Args:
            url: The URL of the ARD Audiothek show or collection
            folder: The output directory (overrides base_folder if provided)

        Returns:
            DownloadResult with success status and message

        """
        target_folder = folder or self.base_folder
        resource = self.client.parse_url(url)
        if not resource:
            error_msg = "Could not determine resource ID from URL."
            self.logger.error(error_msg)
            return DownloadResult(success=False, message=error_msg)

        resource_type, resource_id = resource.resource_type, resource.resource_id
        if resource_type == "episode":
            return self._download_single_episode(resource_id, target_folder)
        else:
            return self._download_collection(resource_id, target_folder, resource_type == "collection")

    def download_from_id(self, resource_id: str, folder: str | None = None) -> DownloadResult:
        """Download content from a resource ID.

        Args:
            resource_id: The direct ID of the resource
            folder: The output directory (overrides base_folder if provided)

        Returns:
            DownloadResult with success status and message

        """
        target_folder = folder or self.base_folder
        resource = self.client.determine_resource_type_from_id(resource_id)
        if not resource:
            error_msg = "Could not determine resource type from ID."
            self.logger.error(error_msg)
            return DownloadResult(success=False, message=error_msg)

        resource_type, parsed_id = resource.resource_type, resource.resource_id
        if resource_type == "episode":
            return self._download_single_episode(parsed_id, target_folder)
        else:
            return self._download_collection(parsed_id, target_folder, resource_type == "collection")

    def update_all_folders(self, folder: str | None = None) -> DownloadResult:
        """Update all subfolders in the output directory by crawling through existing IDs.

        Args:
            folder: The output directory containing subfolders to update (overrides base_folder if provided)

        Returns:
            DownloadResult with success status and message

        """
        target_folder = folder or self.base_folder
        if not os.path.exists(target_folder):
            error_msg = f"Output directory {target_folder} does not exist."
            self.logger.error(error_msg)
            return DownloadResult(success=False, message=error_msg)

        self.logger.info("Starting update of all folders in %s", target_folder)
        updated_count = 0
        error_count = 0

        # Find all subdirectories that end with numeric IDs
        try:
            for item in os.listdir(target_folder):
                item_path = os.path.join(target_folder, item)
                if os.path.isdir(item_path):
                    # Check if the folder name ends with a numeric ID
                    if item.isdigit():
                        self.logger.info("Processing folder: %s", item)
                        result = self.download_from_id(item, target_folder)
                        if result.success:
                            updated_count += 1
                        else:
                            error_count += 1
                    else:
                        # Try to extract numeric ID from the folder name
                        match = re.search(r"^(\d+)", item)
                        if match:
                            numeric_id = match.group(1)
                            self.logger.info("Processing folder: %s (ID: %s)", item, numeric_id)
                            result = self.download_from_id(numeric_id, target_folder)
                            if result.success:
                                updated_count += 1
                            else:
                                error_count += 1
        except Exception as e:
            error_msg = f"Error while updating folders: {e}"
            self.logger.error(error_msg)
            self.logger.exception(e)
            return DownloadResult(
                success=False, message=f"Update partially completed with errors. Updated: {updated_count}, Errors: {error_count + 1}", error=e
            )

        return DownloadResult(success=True, message=f"Update completed. Updated: {updated_count}, Errors: {error_count}")

    def remove_lower_quality_files(self, folder: str | None = None, dry_run: bool = False) -> DownloadResult:
        """Remove lower quality files when higher quality versions exist.

        Args:
            folder: The output directory containing subfolders to process (overrides base_folder if provided)
            dry_run: If True, only show what would be removed without actually deleting files

        Returns:
            DownloadResult with success status and message

        """
        target_folder = folder or self.base_folder
        if not os.path.exists(target_folder):
            error_msg = f"Output directory {target_folder} does not exist."
            self.logger.error(error_msg)
            return DownloadResult(success=False, message=error_msg)

        if dry_run:
            self.logger.info("DRY RUN: Showing what would be removed in %s", target_folder)
        else:
            self.logger.info("Starting removal of lower quality files in %s", target_folder)

        removed_count = 0
        error_count = 0

        # Find all subdirectories
        try:
            for item in os.listdir(target_folder):
                item_path = os.path.join(target_folder, item)
                if os.path.isdir(item_path):
                    result = self._process_folder_quality(item_path, dry_run)
                    removed_count += result.get("removed", 0)
                    error_count += result.get("errors", 0)
        except Exception as e:
            error_msg = f"Error while processing folders: {e}"
            self.logger.error(error_msg)
            self.logger.exception(e)
            return DownloadResult(
                success=False, message=f"Quality cleanup partially completed with errors. Removed: {removed_count}, Errors: {error_count + 1}", error=e
            )

        action = "Would remove" if dry_run else "Removed"
        return DownloadResult(success=True, message=f"Quality cleanup completed. {action}: {removed_count}, Errors: {error_count}")

    def _process_folder_quality(self, folder_path: str, dry_run: bool = False) -> dict[str, int]:
        """Process a single folder to remove lower quality files.

        Args:
            folder_path: Path to the folder to process
            dry_run: If True, only show what would be removed without actually deleting files

        Returns:
            Dictionary with counts of removed files and errors

        """
        removed_count = 0
        error_count = 0

        try:
            # Group files by base name (without extension)
            file_groups: dict[str, dict[str, str]] = {}
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
                result = self._compare_and_remove_files(base_name, files, folder_path, dry_run)
                removed_count += result.get("removed", 0)
                error_count += result.get("errors", 0)

        except Exception as e:
            self.logger.error("Error processing folder %s: %s", folder_path, e)
            error_count += 1

        return {"removed": removed_count, "errors": error_count}

    def _compare_and_remove_files(
        self,
        _base_name: str,
        files: dict[str, str],
        _folder_path: str,
        dry_run: bool = False,
    ) -> dict[str, int]:
        """Compare files with same base name and remove lower quality ones.

        Args:
            files: Dictionary mapping extensions to file paths
            dry_run: If True, only show what would be removed without actually deleting files

        Returns:
            Dictionary with counts of removed files and errors

        """
        removed_count = 0
        error_count = 0

        if len(files) <= 1:
            return {"removed": 0, "errors": 0}  # No comparison needed

        # Get quality information for each file
        file_qualities: dict[str, dict[str, Any]] = {}
        for ext, file_path in files.items():
            quality = self._get_audio_quality(file_path)
            if quality is not None:
                file_qualities[ext] = {"path": file_path, "bitrate": quality}

        if not file_qualities:
            return {"removed": 0, "errors": 0}

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
                removed_count += 1
            else:
                try:
                    os.remove(file_path)
                    self.logger.info("Removed lower quality file: %s", file_path)
                    removed_count += 1
                except Exception as e:
                    self.logger.error("Failed to remove file %s: %s", file_path, e)
                    error_count += 1

        return {"removed": removed_count, "errors": error_count}

    def _get_audio_quality(self, file_path: str) -> int | None:
        """Get audio bitrate from file using mutagen.

        Args:
            file_path: Path to the audio file

        Returns:
            Bitrate in kbps, or None if not available

        """
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

    def _download_single_episode(self, episode_id: str, folder: str) -> DownloadResult:
        """Fetch and store a single episode.

        Args:
            episode_id: The ID of the episode to download
            folder: The output directory to save the downloaded file

        Returns:
            DownloadResult with success status and message

        """
        try:
            node = self.client.get_episode_data(episode_id)
            if not node:
                error_msg = f"Episode not found for {episode_id}"
                self.logger.error(error_msg)
                return DownloadResult(success=False, message=error_msg)

            result = self._save_nodes([node], folder)
            return result
        except Exception as e:
            error_msg = f"Error downloading episode {episode_id}: {str(e)}"
            self.logger.error(error_msg)
            self.logger.exception(e)
            return DownloadResult(success=False, message=error_msg, error=e)

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

    def _download_collection(self, resource_id: str, folder: str, is_editorial_collection: bool) -> DownloadResult:
        """Download episodes from ARD Audiothek.

        Args:
            resource_id: The program set ID extracted from the URL
            folder: The output directory to save downloaded files
            is_editorial_collection: Whether the URL points to an editorial collection

        Returns:
            DownloadResult with success status and message

        """
        try:
            if is_editorial_collection:
                nodes, raw_collection_data = self.client.fetch_editorial_collection(resource_id)
            else:
                nodes = self.client.fetch_program_set_episodes(resource_id)
                raw_collection_data = self.client.get_program_set_data(resource_id) or {}

            if not nodes:
                return DownloadResult(success=True, message=f"No episodes found for {'collection' if is_editorial_collection else 'program'} {resource_id}")

            result = self._save_nodes(nodes, folder)
            if nodes and raw_collection_data:
                self._save_collection_metadata(raw_collection_data, nodes, folder, is_editorial_collection)

            return result
        except Exception as e:
            error_msg = f"Error downloading {'collection' if is_editorial_collection else 'program'} {resource_id}: {str(e)}"
            self.logger.error(error_msg)
            self.logger.exception(e)
            return DownloadResult(success=False, message=error_msg, error=e)

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
        if not ensure_directory_exists(folder, self.logger):
            return

        # Save the collection data as <id>.json
        collection_file_path = os.path.join(folder, f"{collection_id}.json")

        try:
            # Skip writing if content is the same as existing file
            if compare_json_content(collection_file_path, collection_data):
                collection_type = "editorial collection" if is_editorial_collection else "program set"
                self.logger.debug("Skipped writing %s data (content unchanged): %s", collection_type, collection_file_path)
            else:
                result = safe_write_json(collection_file_path, collection_data, self.logger)
                if result.success:
                    if publish_date:
                        set_file_modification_time(collection_file_path, publish_date, self.logger)
                    collection_type = "editorial collection" if is_editorial_collection else "program set"
                    self.logger.debug("Saved %s data: %s", collection_type, collection_file_path)
        except Exception as e:
            collection_type = "editorial collection" if is_editorial_collection else "program set"
            self.logger.error("Error saving %s data: %s", collection_type, e)

        # Define collection type for logging
        collection_type = "editorial collection" if is_editorial_collection else "program set"

        # Download and save collection cover image
        image_data = collection_data.get("image") or {}
        image_url_template = image_data.get("url") or ""
        image_url = image_url_template.replace("{width}", "2000") if image_url_template else ""

        if image_url:
            image_file_path = os.path.join(folder, f"{collection_id}.jpg")
            with self._locked_file_operation(image_file_path, "write"):
                if not os.path.exists(image_file_path):
                    try:
                        self.client._download_to_file(image_url, image_file_path, check_status=True)
                        if publish_date:
                            set_file_modification_time(image_file_path, publish_date, self.logger)
                        self.logger.info("Saved %s cover image: %s", collection_type, image_file_path)
                    except Exception as e:
                        self.logger.error("Error downloading %s cover image: %s", collection_type, e)

    def _save_nodes(self, nodes: list[dict[str, Any]], folder: str) -> DownloadResult:
        """Write episode assets (cover, audio, metadata) to disk.

        Args:
            nodes: List of episode nodes to save
            folder: The output directory to save the files

        Returns:
            DownloadResult with success status and message

        """
        if not nodes:
            return DownloadResult(success=True, message="No episodes to download")

        # Use parallel download if more than one node and max_workers > 1
        if len(nodes) > 1 and self.max_workers > 1:
            self.logger.debug("Using parallel download with %d workers for %d episodes", self.max_workers, len(nodes))
            return parallel_download_nodes(
                nodes, lambda node, index, total: self._process_single_node(node, folder, index, total), self.max_workers, self.logger
            )

        # Otherwise use sequential download
        success_count = 0
        error_count = 0

        for index, node in enumerate(nodes):
            try:
                if self._process_single_node(node, folder, index, len(nodes)):
                    success_count += 1
                else:
                    error_count += 1
            except Exception as e:
                self.logger.error("Error processing node: %s", e)
                error_count += 1

        if error_count > 0:
            return DownloadResult(success=success_count > 0, message=f"Downloaded {success_count} episodes with {error_count} errors")
        return DownloadResult(success=True, message=f"Successfully downloaded {success_count} episodes")

    def _process_single_node(self, node: dict[str, Any], folder: str, index: int, total_count: int) -> bool:
        """Process a single node for download.

        Args:
            node: Node data to process
            folder: Base folder for downloads
            index: Current node index
            total_count: Total number of nodes

        Returns:
            True if successful, False otherwise

        """
        try:
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
                return False

            # Get program information
            program_set = node.get("programSet") or {}
            programset_id = program_set.get("id") or "episode"
            programset_title = program_set.get("title") or ""

            # Create folder name with ID and title: "123456 Show Title"
            folder_name = AudiothekDownloader._program_folder_name(str(programset_id), str(programset_title))
            program_path: str = os.path.join(folder, folder_name)

            # Create directory
            if not ensure_directory_exists(program_path, self.logger):
                return False

            # Save images and metadata
            self._save_images_and_metadata(
                ImageMetadata(
                    node_id=node_id,
                    title=title,
                    filename=filename,
                    program_path=program_path,
                    program_set=program_set,
                    image_urls=image_urls,
                ),
                node,
                node.get("publishDate"),
            )

            # Save audio file
            return self._save_audio_file(audio_urls, filename, program_path, index + 1, total_count, node.get("publishDate"))
        except Exception as e:
            self.logger.error("Error processing node: %s", e)
            return False

    def _extract_image_urls(self, node: dict[str, Any]) -> dict[str, str]:
        """Extract image URLs from node."""
        image = node.get("image") or {}
        image_url_template = image.get("url") or ""
        image_url = image_url_template.replace("{width}", "2000") if image_url_template else ""
        image_url_x1_template = image.get("url1X1") or ""
        image_url_x1 = image_url_x1_template.replace("{width}", "2000") if image_url_x1_template else ""

        return {"image_url": image_url, "image_url_x1": image_url_x1}

    def _extract_audio_url(self, node: dict[str, Any]) -> list[str]:
        """Extract audio URLs from node, returning URLs in priority order."""
        audios = node.get("audios") or []
        if not audios:
            return []

        download_urls, streaming_urls = self._collect_audio_urls(audios)
        download_urls = self._deduplicate_preserve_order(download_urls)
        streaming_urls = self._deduplicate_preserve_order(streaming_urls)

        self.logger.debug("Found %d download URLs: %s", len(download_urls), download_urls)
        self.logger.debug("Found %d streaming URLs: %s", len(streaming_urls), streaming_urls)

        if not download_urls and not streaming_urls:
            return []
        if not download_urls:
            return streaming_urls
        if not streaming_urls:
            return download_urls

        url_candidates = self._build_audio_url_candidates(download_urls, streaming_urls)
        priority_urls = self._prioritize_audio_urls(download_urls, streaming_urls, url_candidates)

        self.logger.debug("Chosen URLs in priority order: %s", priority_urls)
        return priority_urls

    def _collect_audio_urls(self, audios: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
        """Collect download and streaming URLs from audio nodes."""
        download_urls: list[str] = []
        streaming_urls: list[str] = []

        for audio in audios:
            if not isinstance(audio, dict):
                continue

            download_url = audio.get("downloadUrl")
            streaming_url = audio.get("url")

            if download_url:
                download_urls.append(download_url)
            if streaming_url:
                streaming_urls.append(streaming_url)

        return download_urls, streaming_urls

    @staticmethod
    def _deduplicate_preserve_order(urls: list[str]) -> list[str]:
        """Remove duplicates from a list while preserving order."""
        seen: set[str] = set()
        deduplicated: list[str] = []

        for url in urls:
            if url not in seen:
                deduplicated.append(url)
                seen.add(url)

        return deduplicated

    def _build_audio_url_candidates(self, download_urls: list[str], streaming_urls: list[str]) -> list[tuple[str, str, int]]:
        """Collect URL candidates with their content lengths."""
        candidates: list[tuple[str, str, int]] = []

        for url in download_urls:
            size = self.client._get_content_length(url)
            if size is not None:
                candidates.append(("download", url, size))

        for url in streaming_urls:
            size = self.client._get_content_length(url)
            if size is not None:
                candidates.append(("streaming", url, size))

        return candidates

    def _prioritize_audio_urls(
        self,
        download_urls: list[str],
        streaming_urls: list[str],
        url_candidates: list[tuple[str, str, int]],
    ) -> list[str]:
        """Return URLs sorted by the preferred download order."""
        if not url_candidates:
            return self._merge_url_lists(download_urls, streaming_urls)

        sorted_candidates = sorted(url_candidates, key=lambda candidate: candidate[2], reverse=True)
        preferred_url = sorted_candidates[0][1]
        priority_urls = [preferred_url]

        for _, url, _ in sorted_candidates[1:]:
            if url not in priority_urls:
                priority_urls.append(url)

        merged_urls = self._merge_url_lists(download_urls, streaming_urls)
        for url in merged_urls:
            if url not in priority_urls:
                priority_urls.append(url)

        return priority_urls

    @staticmethod
    def _merge_url_lists(*url_lists: list[str]) -> list[str]:
        """Merge multiple URL lists preserving order and uniqueness."""
        merged: list[str] = []
        for urls in url_lists:
            for url in urls:
                if url not in merged:
                    merged.append(url)
        return merged

    def _save_images_and_metadata(self, metadata: ImageMetadata, node: dict[str, Any], publish_date: str | None = None) -> None:
        """Save images and metadata files."""
        # Save images
        image_file_path = os.path.join(metadata.program_path, metadata.filename + ".jpg")
        image_file_x1_path = os.path.join(metadata.program_path, metadata.filename + "_x1.jpg")

        if metadata.image_urls["image_url"]:
            with self._locked_file_operation(image_file_path, "write"):
                if not os.path.exists(image_file_path):
                    try:
                        self.client._download_to_file(metadata.image_urls["image_url"], image_file_path)
                        if publish_date:
                            set_file_modification_time(image_file_path, publish_date, self.logger)
                    except Exception as e:
                        self.logger.error("Failed to download image: %s", e)

        if metadata.image_urls["image_url_x1"]:
            with self._locked_file_operation(image_file_x1_path, "write"):
                if not os.path.exists(image_file_x1_path):
                    try:
                        self.client._download_to_file(metadata.image_urls["image_url_x1"], image_file_x1_path)
                        if publish_date:
                            set_file_modification_time(image_file_x1_path, publish_date, self.logger)
                    except Exception as e:
                        self.logger.error("Failed to download square image: %s", e)

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
        if compare_json_content(meta_file_path, data):
            self.logger.debug("Skipped writing episode metadata (content unchanged): %s", meta_file_path)
        else:
            result = safe_write_json(meta_file_path, data, self.logger)
            if result.success and publish_date:
                set_file_modification_time(meta_file_path, publish_date, self.logger)

    def _save_audio_file(
        self, audio_urls: list[str], filename: str, program_path: str, current_index: int, total_count: int, publish_date: str | None = None
    ) -> bool:
        """Save audio file with appropriate extension based on URL format.

        Args:
            audio_urls: List of audio URLs in priority order
            filename: Base filename to use (without extension)
            program_path: Directory to save the file in
            current_index: Current episode index for logging
            total_count: Total number of episodes for logging
            publish_date: Publish date for setting file modification time

        Returns:
            True if successful, False otherwise

        """
        if not audio_urls:
            self.logger.error("No audio URLs provided")
            return False

        # Use the first (highest priority) URL
        preferred_url = audio_urls[0]
        # Use the second URL as fallback if available, otherwise use the first
        fallback_url = audio_urls[1] if len(audio_urls) > 1 else audio_urls[0]
        # Determine file extension based on URL format
        file_extension = self._get_audio_file_extension(preferred_url)
        audio_file_path = os.path.join(program_path, filename + file_extension)

        self.logger.info("Download: %s of %s -> %s", current_index, total_count, audio_file_path)

        # Check if file exists and is complete
        with self._locked_file_operation(audio_file_path, "write"):
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
                        # Backup old file
                        success, _ = backup_file(audio_file_path, self.logger)
                        if not success:
                            self.logger.error("Failed to backup file, skipping download")
                            return False
                    else:
                        self.logger.info(
                            "New version is smaller than existing file (%s/%s bytes), will keep existing file: %s",
                            current_size,
                            expected_length,
                            audio_file_path,
                        )
                        should_download = False
                else:
                    self.logger.info("Could not determine content length, will backup existing file: %s", audio_file_path)
                    # Backup old file
                    success, _ = backup_file(audio_file_path, self.logger)
                    if not success:
                        self.logger.error("Failed to backup file, skipping download")
                        return False

            if should_download:
                download_success = self.client._download_audio_to_file(preferred_url, audio_file_path, fallback_url)
                if download_success:
                    # Set file modification time to publish date if available
                    if publish_date:
                        set_file_modification_time(audio_file_path, publish_date, self.logger)
                    return True

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
                    if restore_backup(backup_path, audio_file_path, self.logger):
                        self.logger.info("Restored original file from backup: %s", audio_file_path)
                        return True
                return False
            return True

    def _get_audio_file_extension(self, url: str) -> str:
        """Get the appropriate file extension for an audio URL."""
        url_lower = url.lower()
        if url_lower.endswith(".m4a"):
            return ".m4a"
        elif url_lower.endswith(".mp3"):
            return ".mp3"
        elif "aac" in url_lower:
            return ".aac"
        elif "mp4" in url_lower:
            return ".mp4"

        # Default to .mp3 for backward compatibility
        return ".mp3"
