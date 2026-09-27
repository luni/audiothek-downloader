import json
import logging
import os
import re
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .downloader import AudiothekDownloader

REQUEST_TIMEOUT = 30
MAX_FOLDER_NAME_LENGTH = 100


def is_valid_resource_id(resource_id: str) -> bool:
    """Return True if the string looks like a usable ARD Audiothek resource ID.

    This is a lightweight local check that mirrors the first layer of
    AudiothekClient.determine_resource_type_from_id without needing a client.
    Pure alphabetic tokens are rejected to avoid treating unrelated folder
    names (e.g. "My Downloads") as resource IDs.
    """
    resource_id = resource_id.strip()
    if not resource_id:
        return False
    if resource_id.startswith("urn:ard:"):
        return True
    if resource_id.isdigit():
        return True
    if re.match(r"^[a-zA-Z0-9_]+$", resource_id) and any(c.isdigit() for c in resource_id):
        return True
    return False


def get_folder_resource_id(folder_path: str) -> str | None:
    """Recover the original resource ID for an existing output folder.

    The ID is recovered from JSON metadata inside the folder if available;
    otherwise the first token of the folder name is used when it is a valid ID.
    """
    folder_name = os.path.basename(folder_path)
    first_token = folder_name.split(" ", 1)[0]

    # Prefer IDs stored in JSON metadata files inside the folder.
    try:
        for filename in os.listdir(folder_path):
            if not filename.endswith(".json"):
                continue
            file_path = os.path.join(folder_path, filename)
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            if not isinstance(data, dict):
                continue

            raw_id = data.get("id")
            if raw_id is not None and sanitize_folder_name(str(raw_id)) == first_token:
                return str(raw_id)

            program_set = data.get("programSet") or {}
            if isinstance(program_set, dict):
                raw_id = program_set.get("id")
                if raw_id is not None and sanitize_folder_name(str(raw_id)) == first_token:
                    return str(raw_id)
    except OSError:
        pass

    # Fallback to the first token of the folder name if it is a valid ID.
    if is_valid_resource_id(first_token):
        return first_token

    return None


def sanitize_folder_name(name: str) -> str:
    """Sanitize a string to be used as a folder name.

    Args:
        name: The string to sanitize

    Returns:
        A sanitized string safe for use as a folder name

    """
    # Remove or replace characters that are problematic in folder names
    # Replace forward slashes and other problematic characters with underscores
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", name)
    # Replace any whitespace (including newlines/tabs) with a single space
    sanitized = re.sub(r"\s+", " ", sanitized)
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(" .")
    # Limit length to avoid filesystem issues
    if len(sanitized) > MAX_FOLDER_NAME_LENGTH:
        sanitized = sanitized[:MAX_FOLDER_NAME_LENGTH].rstrip()
    return sanitized


def load_graphql_query(filename: str) -> str:
    """Load GraphQL query from file.

    Args:
        filename: The GraphQL query filename

    Returns:
        The GraphQL query string

    """
    # Prefer package resources so installed wheels/sdists work reliably.
    try:
        return resources.files("audiothek").joinpath("graphql").joinpath(filename).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError):
        # Fallback for local source-tree execution.
        base_dir = os.path.dirname(os.path.abspath(__file__))
        graphql_dir = os.path.join(base_dir, "graphql")
        query_path = os.path.join(graphql_dir, filename)
        with open(query_path, encoding="utf-8") as f:
            return f.read()


def migrate_folders(folder: str, downloader: "AudiothekDownloader", logger: logging.Logger) -> bool:
    """Migrate existing folders to new naming schema (ID + Title).

    Args:
        folder: The output directory containing folders to migrate
        downloader: The AudiothekDownloader instance for making API requests
        logger: Logger instance for logging messages

    Returns:
        True if migration completed without fatal errors, False otherwise

    """
    if not os.path.exists(folder):
        logger.error("Output directory %s does not exist.", folder)
        return False

    logger.info("Starting folder migration in %s", folder)

    # Track whether every identified migration was carried out successfully.
    migration_success = True

    # Find all subdirectories and migrate them to the sanitized ID + Title schema.
    try:
        for item in os.listdir(folder):
            item_path = os.path.join(folder, item)
            if not os.path.isdir(item_path):
                continue

            # If the folder already follows the new "ID Title" schema, skip it.
            if " " in item:
                first_token, title_part = item.split(" ", 1)
                # Raw URN-style IDs still contain colons and must be migrated.
                if ":" not in first_token and downloader._program_folder_name(first_token, title_part) == item:
                    continue

            resource_id = get_folder_resource_id(item_path)
            if resource_id is None:
                continue

            resource = downloader.client.determine_resource_type_from_id(resource_id)
            if resource is None:
                logger.warning("Could not determine resource type for folder: %s", item)
                continue

            title = downloader.client.get_title(resource.resource_id, resource.resource_type)
            sanitized_title = sanitize_folder_name(title) if title else ""
            if not sanitized_title:
                logger.warning("Could not get title for folder: %s", item)
                migration_success = False
                continue

            new_folder_name = downloader._program_folder_name(resource.resource_id, sanitized_title)
            if new_folder_name == item:
                continue

            new_folder_path = os.path.join(folder, new_folder_name)
            try:
                os.rename(item_path, new_folder_path)
                logger.info("Renamed: %s -> %s", item, new_folder_name)
            except OSError as e:
                logger.error("Failed to rename folder %s: %s", item, e)
                migration_success = False

    except Exception as e:
        logger.error("Error while migrating folders: %s", e)
        logger.exception(e)
        return False

    return migration_success
