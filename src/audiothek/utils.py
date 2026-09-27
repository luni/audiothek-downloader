import json
import logging
import os
import re
import time
from importlib import resources
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .downloader import AudiothekDownloader

REQUEST_TIMEOUT = 30
MAX_FOLDER_NAME_LENGTH = 100
MAX_FILENAME_BYTES = 200
# Transient artifacts are never library content; renaming them is pointless.
TRANSIENT_FILE_SUFFIXES = (".lock", ".bak", ".part", ".tmp", "-temp")
# Artifacts that cleanup removes. .bak files are intentionally kept - they are
# the only recovery path for interrupted re-downloads.
DEAD_FILE_SUFFIXES = (".lock", ".part", ".tmp", "-temp")
# Artifacts younger than this are left alone: they may belong to an in-flight
# download running concurrently.
DEAD_FILE_MIN_AGE_SECONDS = 60


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
    if re.match(r"^[a-zA-Z0-9]+$", resource_id) and any(c.isdigit() for c in resource_id):
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
            except (OSError, ValueError):
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
    # Limit length to avoid filesystem issues; re-strip in case truncation
    # left a trailing space or dot (both illegal at the end on Windows).
    if len(sanitized) > MAX_FOLDER_NAME_LENGTH:
        sanitized = sanitized[:MAX_FOLDER_NAME_LENGTH].rstrip(" .")
    return sanitized


def episode_file_stem(safe_node_id: str, title: str) -> str:
    """Build the filename stem the downloader uses for an episode node.

    Args:
        safe_node_id: Already-sanitized node ID
        title: Resolved episode title

    Returns:
        The filename stem (without extension), capped at MAX_FILENAME_BYTES

    """
    array_filename = re.findall(r"(\w+)", title)
    filename_base = "_".join(array_filename) if array_filename else safe_node_id
    filename = filename_base if filename_base == safe_node_id else f"{filename_base}_{safe_node_id}"

    # Cap the filename so the file (plus extension) stays within filesystem
    # name limits; trim by bytes since names are UTF-8.
    if len(filename.encode("utf-8")) > MAX_FILENAME_BYTES:
        suffix = f"_{safe_node_id}"
        budget = max(0, MAX_FILENAME_BYTES - len(suffix.encode("utf-8")))
        filename_base = filename_base.encode("utf-8")[:budget].decode("utf-8", errors="ignore").rstrip(" _") or "episode"
        filename = f"{filename_base}{suffix}"
    if len(filename.encode("utf-8")) > MAX_FILENAME_BYTES:
        # The node ID alone exceeds the budget; hard-truncate as a last resort.
        filename = filename.encode("utf-8")[:MAX_FILENAME_BYTES].decode("utf-8", errors="ignore").rstrip(" _")
    return filename


def sanitize_file_stem(stem: str) -> str:
    """Normalize an existing file stem to the current naming scheme.

    Mirrors the word-joining and byte cap of episode_file_stem for files whose
    original metadata is unavailable.

    """
    normalized = "_".join(re.findall(r"(\w+)", stem))
    if len(normalized.encode("utf-8")) > MAX_FILENAME_BYTES:
        normalized = normalized.encode("utf-8")[:MAX_FILENAME_BYTES].decode("utf-8", errors="ignore").rstrip(" _")
    return normalized or "file"


def rename_files(folder: str, logger: logging.Logger, dry_run: bool = False) -> bool:
    """Rename existing files and folders to the current naming scheme.

    This lets already-downloaded files be recognized by the downloader, so
    re-running does not fetch them again. Episode metadata JSON files anchor
    the exact target stem; other files get a normalized stem derived from
    their current name.

    Args:
        folder: The output directory to scan
        logger: Logger instance for logging messages
        dry_run: If True, only log what would be renamed

    Returns:
        True if every identified rename succeeded, False otherwise

    """
    if not os.path.isdir(folder):
        logger.error("Output directory %s does not exist.", folder)
        return False

    logger.info("Starting rename scan in %s%s", folder, " (dry run)" if dry_run else "")
    success = True

    def _rename(old_path: str, new_name: str) -> bool:
        if not new_name or new_name == os.path.basename(old_path):
            return True
        new_path = os.path.join(os.path.dirname(old_path), new_name)
        if os.path.exists(new_path):
            # On case-insensitive filesystems the target may be the same file
            # under different case (e.g. .MP3 -> .mp3); the rename is needed.
            try:
                same_file = os.path.samefile(old_path, new_path)
            except OSError:
                same_file = False
            if not same_file:
                logger.warning("Skipping rename, target already exists: %s -> %s", old_path, new_path)
                return False
        if dry_run:
            logger.info("DRY RUN: Would rename %s -> %s", old_path, new_path)
            return True
        try:
            os.rename(old_path, new_path)
            logger.info("Renamed: %s -> %s", old_path, new_path)
            return True
        except OSError as e:
            logger.error("Failed to rename %s: %s", old_path, e)
            return False

    # Phase 1: directories, deepest first so renames never break pending paths.
    # Hidden directories (e.g. .git) are skipped entirely.
    dir_paths: list[str] = []
    for dirpath, dirnames, _ in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        dir_paths.extend(os.path.join(dirpath, d) for d in dirnames)
    for dir_path in sorted(dir_paths, key=lambda p: p.count(os.sep), reverse=True):
        if not _rename(dir_path, sanitize_folder_name(os.path.basename(dir_path))):
            success = False

    # Phase 2: files. Episode metadata JSON files carry id/title and anchor the
    # exact stem the downloader would produce, including for sibling files that
    # share the stem (audio, cover images, the JSON itself).
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        stem_map: dict[str, str] = {}
        for name in filenames:
            if name.startswith(".") or not name.lower().endswith(".json"):
                continue
            try:
                with open(os.path.join(dirpath, name), encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or "programSet" not in data:
                continue
            raw_id = data.get("id")
            if raw_id is None:
                continue
            safe_id = sanitize_folder_name(str(raw_id)) or "episode"
            stem_map[os.path.splitext(name)[0]] = episode_file_stem(safe_id, str(data.get("title") or safe_id))

        for name in filenames:
            if name.startswith(".") or name.lower().endswith(TRANSIENT_FILE_SUFFIXES):
                continue
            stem, ext = os.path.splitext(name)
            if stem in stem_map:
                new_stem = stem_map[stem]
            elif stem.endswith("_x1") and stem[:-3] in stem_map:
                new_stem = f"{stem_map[stem[:-3]]}_x1"
            elif sanitize_folder_name(stem) == stem and ext == ext.lower():
                # Orphan files with already-valid names are left alone:
                # renaming them cannot improve download recognition.
                continue
            else:
                new_stem = sanitize_file_stem(stem)
            if not _rename(os.path.join(dirpath, name), new_stem + ext.lower()):
                success = False

    return success


def cleanup_files(folder: str, logger: logging.Logger, dry_run: bool = False) -> bool:
    """Delete dead artifacts (stale locks, partial downloads) from the output tree.

    Removes ``*.lock``/``*.part``/``*.tmp``/``*-temp`` files. ``*.bak`` backups
    are intentionally kept - they are the recovery path for interrupted
    re-downloads.

    Args:
        folder: The output directory to scan
        logger: Logger instance for logging messages
        dry_run: If True, only log what would be deleted

    Returns:
        True if every deletion succeeded, False otherwise

    """
    if not os.path.isdir(folder):
        logger.error("Output directory %s does not exist.", folder)
        return False

    logger.info("Starting cleanup scan in %s%s", folder, " (dry run)" if dry_run else "")
    success = True
    deleted = 0

    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith(".") or not name.lower().endswith(DEAD_FILE_SUFFIXES):
                continue
            file_path = os.path.join(dirpath, name)
            try:
                age_seconds = time.time() - os.path.getmtime(file_path)
            except OSError:
                continue
            if age_seconds < DEAD_FILE_MIN_AGE_SECONDS:
                logger.debug("Skipping fresh artifact (possibly in use): %s", file_path)
                continue
            if dry_run:
                logger.info("DRY RUN: Would delete %s", file_path)
                deleted += 1
                continue
            try:
                os.remove(file_path)
                deleted += 1
                logger.debug("Deleted artifact: %s", file_path)
            except OSError as e:
                logger.error("Failed to delete %s: %s", file_path, e)
                success = False

    logger.info("Cleanup complete. Deleted: %s", deleted)
    return success


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
            if item.startswith("."):
                continue
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
            if os.path.exists(new_folder_path):
                logger.warning("Skipping migration, target folder already exists: %s", new_folder_path)
                migration_success = False
                continue
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
