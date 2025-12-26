import logging
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .downloader import AudiothekDownloader

REQUEST_TIMEOUT = 30
MAX_FOLDER_NAME_LENGTH = 100


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
    # Remove leading/trailing whitespace and dots
    sanitized = sanitized.strip(" .")
    # Replace multiple spaces with single space
    sanitized = re.sub(r"\s+", " ", sanitized)
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
    base_dir = os.path.dirname(os.path.abspath(__file__))
    graphql_dir = os.path.join(base_dir, "graphql")
    query_path = os.path.join(graphql_dir, filename)
    with open(query_path) as f:
        return f.read()


def migrate_folders(folder: str, downloader: "AudiothekDownloader", logger: logging.Logger) -> None:
    """Migrate existing folders to new naming schema (ID + Title).

    Args:
        folder: The output directory containing folders to migrate
        downloader: The AudiothekDownloader instance for making API requests
        logger: Logger instance for logging messages

    """
    if not os.path.exists(folder):
        logger.error("Output directory %s does not exist.", folder)
        return

    logger.info("Starting folder migration in %s", folder)

    # Find all subdirectories with numeric IDs
    try:
        for item in os.listdir(folder):
            item_path = os.path.join(folder, item)
            if os.path.isdir(item_path):
                # Check if the folder name is a pure numeric ID (old format)
                if item.isdigit():
                    logger.info("Found old format folder: %s", item)

                    # Try to get the program title by making a request
                    resource_result = downloader.client.determine_resource_type_from_id(item)
                    if not resource_result:
                        logger.warning("Could not determine resource type for folder: %s", item)
                        continue

                    # Extract resource type and ID from ResourceInfo object
                    resource_type = resource_result.resource_type
                    parsed_id = resource_result.resource_id

                    # Get program information to extract the title
                    title = downloader.client.get_title(parsed_id, resource_type)
                    if title:
                        # Create new folder name with ID and title
                        new_folder_name = f"{item} {sanitize_folder_name(title)}"
                        new_folder_path = os.path.join(folder, new_folder_name)

                        # Rename the folder
                        try:
                            os.rename(item_path, new_folder_path)
                            logger.info("Renamed: %s -> %s", item, new_folder_name)
                        except OSError as e:
                            logger.error("Failed to rename folder %s: %s", item, e)
                    else:
                        logger.warning("Could not get title for folder: %s", item)

    except Exception as e:
        logger.error("Error while migrating folders: %s", e)
        logger.exception(e)
